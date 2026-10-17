"""FastAPI app: /health, /nodes, /readings, live state, alerts, demo controls, /notifications/status, /ws."""
from __future__ import annotations

import asyncio
import json

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import config
from ..live.labels import node_fields
from ..runtime import Stack
from ..simulator.scenarios import EVENT_TYPES

DIST = config.ROOT / "frontend" / "dist"


class InjectBody(BaseModel):
    type: str
    node: str


class ControlBody(BaseModel):
    speed: float | None = None
    paused: bool | None = None


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


def _numbered(d: dict, key: str = "node_id") -> dict:
    """Round 7: a copy of an object that names a node, with the node's number, ward and labels added (existing fields unchanged)."""
    f = node_fields(d.get(key))
    return {**d, "node_number": f["number"], "ward": f["ward"], "node_label": f["label"], "node_short": f["short"]}


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

    @app.get("/ready")
    def ready():
        """Readiness probe: 200 once readings arrive (in docker mode the API listens before the nodes process replays)."""
        n = stack.worker.accepted
        return JSONResponse({"ready": n > 0, "accepted": n}, status_code=200 if n else 503)

    @app.get("/nodes")
    def nodes():
        return stack.store.nodes()

    @app.get("/readings")
    def readings(node: str | None = None, since: str | None = None, limit: int = 1000):
        return stack.store.read_readings(node=node, since=since, limit=min(max(limit, 1), 20000))

    def live():
        lv = stack.extras.get("live")
        if lv is None:
            raise HTTPException(503, "live pipeline not running")
        return lv

    @app.get("/network")
    def network():
        from ..live.system import load_nodes_config

        cfg = load_nodes_config()
        lv = stack.extras.get("live")
        for n in cfg["nodes"]:
            n["latest"] = lv.processor.latest(n["id"]) if lv else None
            n.update(node_fields(n["id"]))  # number, ward, ward_name, label, short (Round 7)
        cfg["counts"] = lv.processor.counts() if lv else {}
        cfg["event_types"] = EVENT_TYPES
        return cfg

    @app.get("/nodes/{node_id}/state")
    def node_state(node_id: str, limit: int = 288):
        lv = live()
        latest = lv.processor.latest(node_id)
        if latest is None:
            raise HTTPException(404, f"no state for {node_id} yet")
        return _numbered({"node_id": node_id, "latest": latest, "series": lv.processor.series(node_id, min(max(limit, 1), 600)),
                          "alerts": [_numbered(a) for a in lv.processor.list_alerts(node=node_id, limit=20)]})

    @app.get("/alerts")
    def alerts(category: str | None = None, priority: str | None = None, node: str | None = None,
               status: str | None = None, limit: int = 200):
        return [_numbered(a) for a in live().processor.list_alerts(category, priority, node, status, min(max(limit, 1), 1000))]

    @app.post("/demo/inject")
    def demo_inject(body: InjectBody):
        lv = live()
        if body.type not in EVENT_TYPES:
            raise HTTPException(422, f"type must be one of {EVENT_TYPES}")
        if body.node not in lv.frames:
            raise HTTPException(404, f"unknown node {body.node}")
        try:
            return lv.injector.inject(body.type, body.node, lv.fleet.step, lv.fleet.last_ts)
        except RuntimeError as e:  # docker mode: the nodes process did not answer
            raise HTTPException(503, str(e)) from None

    @app.post("/demo/control")
    def demo_control(body: ControlBody):
        lv = live()
        if body.speed is not None:
            lv.fleet.speed = max(0.0, float(body.speed))
        if body.paused is not None:
            lv.fleet.paused = bool(body.paused)
        return demo_status()

    @app.get("/demo/status")
    def demo_status():
        lv = live()
        return {"speed": lv.fleet.speed, "paused": lv.fleet.paused, "step": lv.fleet.step, "ts": lv.fleet.last_ts,
                "done": lv.fleet.done, "injections": lv.injector.status(), "mode": stack.mode,
                "data_kind": "semi_synthetic", "method": lv.processor.fusion.describe()}

    @app.get("/notifications/status")
    def notifications_status():
        """Alert push: mode (dry_run or telegram), counts, last send time, limits. Never the bot token or the chat id."""
        mgr = stack.extras.get("notifications")
        if mgr is None:
            raise HTTPException(503, "notifications not running")
        return mgr.status()

    @app.get("/complaints")
    def complaints(limit: int = 200):
        """Citizen pipe-damage tickets (Round 6), newest first. No chat id, no name, no file path."""
        from ..citizen.tickets import public_view

        return [_numbered(public_view(t), "nearest_node_id") for t in stack.store.read_complaints(min(max(limit, 1), 500))]

    @app.get("/complaints/{ticket_id}/thumb")
    def complaint_thumb(ticket_id: int):
        """The small copy of a ticket photo (a re-encoded JPEG without metadata)."""
        from pathlib import Path

        from fastapi.responses import FileResponse

        from ..citizen.settings import work_dir

        svc = stack.extras.get("citizen")
        uploads = svc.tickets.uploads if svc is not None else work_dir() / "uploads"
        t = next((x for x in stack.store.read_complaints(500) if x["id"] == ticket_id), None)
        name = Path(str(t.get("thumb_file", ""))).name if t else ""
        if not name.endswith("_thumb.jpg") or not (uploads / name).is_file():
            raise HTTPException(404, "no photo for this ticket")
        return FileResponse(uploads / name, media_type="image/jpeg")

    @app.get("/citizen/status")
    def citizen_status():
        """Citizen interface: on or off, counts, model names. Never the token, a chat id or a message."""
        svc = stack.extras.get("citizen")
        return svc.status() if svc is not None else {"enabled": False, "detail": "citizen interface not started", "data": "demo_fictional"}

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

    if DIST.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(DIST), html=True), name="frontend")
    return app
