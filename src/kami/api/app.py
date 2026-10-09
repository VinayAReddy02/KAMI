"""FastAPI app: /health, /nodes, /readings, /ws."""
from __future__ import annotations

import asyncio
import json

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from ..runtime import Stack


class Hub:
    """Fans messages out from worker threads to connected WebSocket clients."""

    def __init__(self):
        self.clients: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def push(self, msg: dict) -> None:
        if self.loop is None:
            return
        text = json.dumps(msg)
        for q in list(self.clients):
            self.loop.call_soon_threadsafe(self._offer, q, text)

    @staticmethod
    def _offer(q: asyncio.Queue, text: str) -> None:
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(text)


def create_app(stack: Stack) -> FastAPI:
    hub = Hub()

    @asynccontextmanager
    async def lifespan(_app):
        hub.loop = asyncio.get_running_loop()
        yield

    app = FastAPI(title="KAMI API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.state.stack = stack
    app.state.hub = hub
    stack.extras["hub"] = hub
    stack.worker.listeners.append(lambda r: hub.push({"type": "reading", "data": r}))

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": stack.mode, "readings": stack.store.count(),
                "accepted": stack.worker.accepted, "rejected": stack.worker.rejected}

    @app.get("/nodes")
    def nodes():
        return stack.store.nodes()

    @app.get("/readings")
    def readings(node: str | None = None, since: str | None = None, limit: int = 1000):
        return stack.store.read_readings(node=node, since=since, limit=min(max(limit, 1), 20000))

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        hub.clients.add(q)
        try:
            while True:
                await sock.send_text(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.clients.discard(q)

    return app
