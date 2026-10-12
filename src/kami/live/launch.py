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
        if self.stack.extras.get("notifications") is not None:
            self.stack.extras["notifications"].stop()
        if self.stack.extras.get("citizen") is not None:
            self.stack.extras["citizen"].stop()
        self.server.should_exit = True
        time.sleep(0.3)


def launch(speed: float = 600.0, port: int | None = None, mode: str | None = None, temp_store: bool = False,
           start: int | None = None, max_steps: int | None = None, notifications: str = "dry_run", citizen: str = "off") -> Handle:
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
    live = build_live(stack, speed=speed, start=start, max_steps=max_steps, notifications=notifications, citizen=citizen)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, name="uvicorn", daemon=True).start()
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    live.fleet.start()
    stack.extras["citizen"].start()  # does nothing unless inbound handling was allowed and is switched on
    return Handle(stack, live, server, port)


# ---------------------------------------------------------------- docker mode: three processes around MQTT and TimescaleDB
ROLES = ("ingest", "api", "nodes")  # start order: the store writer, then the API (which must be listening before readings flow), then the nodes


@dataclass
class DockerHandle:
    """The docker-mode demo: one operating-system process per role. `procs` maps role -> subprocess.Popen."""

    procs: dict
    port: int
    log_dir: Path

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def alive(self) -> dict:
        return {role: p.poll() is None for role, p in self.procs.items()}

    def stop(self) -> dict:
        """Stop the three processes (nodes first). Returns role -> True if the process is gone."""
        for role in reversed(ROLES):
            p = self.procs.get(role)
            if p is not None and p.poll() is None:
                p.terminate()
        gone = {}
        for role, p in self.procs.items():
            try:
                p.wait(timeout=10)
            except Exception:
                p.kill()
                p.wait(timeout=5)
            gone[role] = p.poll() is not None
        return gone


def launch_docker(speed: float = 600.0, port: int | None = None, notifications: str = "dry_run", citizen: str = "off", lock: bool = False,
                  max_steps: int | None = None, clear: bool = True, env: dict | None = None) -> DockerHandle:
    """Start the virtual nodes, the ingest worker and the API as three separate processes that talk only through the MQTT
    broker and TimescaleDB of docker-compose.yml (which must be up: `docker compose up -d`)."""
    import os
    import subprocess
    import sys

    from ..store.timescale_store import TimescaleStore

    if not config.stack_up():
        raise RuntimeError("the MQTT broker and TimescaleDB are not reachable: start them with `docker compose up -d`")
    port = port or config.API_PORT
    if clear:  # a demo run starts from an empty database, as in the fallback mode
        store = TimescaleStore(config.PG_DSN)
        store.init()
        store.clear()
        store.close()
    child_env = dict(os.environ if env is None else env)
    child_env["KAMI_MODE"] = "docker"
    child_env["PYTHONPATH"] = str(config.ROOT / "src") + os.pathsep + child_env.get("PYTHONPATH", "")
    child_env["PYTHONUNBUFFERED"] = "1"
    log_dir = config.ROOT / "data" / "processed" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    args = {"ingest": [], "api": ["--port", str(port), "--notifications", notifications, "--citizen", citizen] + (["--lock"] if lock else []),
            "nodes": ["--speed", str(speed)] + (["--steps", str(max_steps)] if max_steps else [])}
    procs = {}

    def start(role: str) -> None:
        log = open(log_dir / f"docker_{role}.log", "w", encoding="utf-8")
        procs[role] = subprocess.Popen([sys.executable, "-m", "kami.live.procs", role, *args[role]], cwd=config.ROOT, env=child_env,
                                       stdout=log, stderr=subprocess.STDOUT)

    handle = DockerHandle(procs, port, log_dir)
    try:
        start("ingest")
        start("api")
        for _ in range(600):  # the API process loads the models and the replay data before it listens
            if procs["api"].poll() is not None:
                raise RuntimeError(f"the API process ended early: see {log_dir / 'docker_api.log'}")
            try:
                httpx.get(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("the API process did not start listening")
        start("nodes")
        for _ in range(600):  # ready only when readings arrive: the nodes process has loaded the replay data and listens for control messages
            if procs["nodes"].poll() is not None:
                raise RuntimeError(f"the nodes process ended early: see {log_dir / 'docker_nodes.log'}")
            try:
                if httpx.get(f"http://127.0.0.1:{port}/ready", timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("no reading reached the API process in 2 minutes")
    except Exception:
        handle.stop()
        raise
    return handle

