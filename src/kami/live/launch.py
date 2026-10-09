"""Start the whole system in one process: bus, store, worker, processor, virtual nodes, API (+ built frontend)."""
from __future__ import annotations

import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import uvicorn

from .. import config
from ..api.app import create_app
from ..runtime import Stack
from ..store import SqliteStore
from .system import LiveSystem, build_live


@dataclass
class Handle:
    stack: Stack
    live: LiveSystem
    server: uvicorn.Server
    port: int

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.live.fleet.stop()
        self.server.should_exit = True
        time.sleep(0.3)


def launch(speed: float = 600.0, port: int | None = None, mode: str | None = None, temp_store: bool = False,
           start: int | None = None, max_steps: int | None = None) -> Handle:
    port = port or config.API_PORT
    mode = mode or config.resolve_mode()
    if mode == "docker":
        stack = Stack.create(mode="docker")
    else:
        path = Path(tempfile.mkdtemp()) / "kami.sqlite" if temp_store else config.SQLITE_PATH
        if not temp_store and path.exists():
            path.unlink()  # a demo run starts from an empty database (single generated file)
        store = SqliteStore(path)
        store.init()
        stack = Stack.create(mode="fallback", store=store)
    app = create_app(stack)
    live = build_live(stack, speed=speed, start=start, max_steps=max_steps)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, name="uvicorn", daemon=True).start()
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    live.fleet.start()
    return Handle(stack, live, server, port)
