"""Docker mode as separate processes: virtual nodes, ingest worker and API talk only through MQTT and TimescaleDB.

    python -m kami.live.procs nodes  --speed 600         publishes one reading per node per step to MQTT
    python -m kami.live.procs ingest                     subscribes to the readings and writes them to TimescaleDB
    python -m kami.live.procs api    --port 8200         live assessment, alerts, dashboard, API; reads history from TimescaleDB

    [virtual nodes] --kami/nodes/<id>/readings--> [Mosquitto] --> [ingest worker] --> [TimescaleDB]
          ^   |                                       |                                    ^
          |   +--kami/status/replay------------------>+--> [API process: live processor, --+ (reads readings, writes
          +------kami/control/replay, kami/control/inject <-----  dashboard, alert push]       assessments and tickets)

The API process never touches the nodes directly: replay speed, pause and event injection go over MQTT control topics,
and the replay position comes back on a status topic. Started together by `scripts/run_demo.py --mode docker`
(see launch.launch_docker). The fallback mode (one process, in-process bus, SQLite) is unchanged.
"""
from __future__ import annotations

import argparse
import threading
import time
import uuid

from .. import config
from ..simulator.scenarios import EVENT_TYPES

TOPIC_REPLAY_CONTROL = "kami/control/replay"  # {"speed": float} and/or {"paused": bool}
TOPIC_INJECT = "kami/control/inject"  # {"id": str, "type": str, "node": str}
TOPIC_INJECT_RESULT = "kami/control/inject/result"  # {"id": str, "ok": bool, "record": {...} | "error": str}
TOPIC_REPLAY_STATUS = "kami/status/replay"  # {"speed", "paused", "step", "ts", "done", "published", "injections"}
TOPIC_INGEST_STATUS = "kami/status/ingest"  # {"accepted", "rejected"}
STATUS_EVERY = 0.5


def _mqtt():
    from ..ingest.bus import MqttBus

    return MqttBus("localhost", config.MQTT_PORT)


def _wait_forever(stop: threading.Event, tick, every: float = STATUS_EVERY) -> None:
    try:
        while not stop.is_set():
            tick()
            stop.wait(every)
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------- role: virtual nodes
def run_nodes(speed: float = 600.0, max_steps: int | None = None, n_nodes: int = 8) -> None:
    from ..simulator.inject import Injector
    from ..simulator.node import NodeFleet, build_node_frames, find_clean_start

    frames = build_node_frames(n_nodes)
    start = find_clean_start(frames)
    bus = _mqtt()
    inj = Injector(frames)
    fleet = NodeFleet(bus, frames, speed, start=start, max_steps=max_steps, modifier=inj.modifier)

    def on_replay(_topic, msg):
        if isinstance(msg.get("speed"), (int, float)) and not isinstance(msg.get("speed"), bool):
            fleet.speed = max(0.0, float(msg["speed"]))
        if isinstance(msg.get("paused"), bool):
            fleet.paused = msg["paused"]

    def on_inject(_topic, msg):
        rid = msg.get("id")
        try:
            rec = inj.inject(str(msg.get("type")), str(msg.get("node")), fleet.step, fleet.last_ts)
            bus.publish(TOPIC_INJECT_RESULT, {"id": rid, "ok": True, "record": rec})
        except (ValueError, KeyError) as e:
            bus.publish(TOPIC_INJECT_RESULT, {"id": rid, "ok": False, "error": type(e).__name__})

    bus.subscribe(TOPIC_REPLAY_CONTROL, on_replay)
    bus.subscribe(TOPIC_INJECT, on_inject)
    time.sleep(0.5)  # subscriptions in place before the first reading goes out
    fleet.start()
    print(f"nodes: {n_nodes} virtual nodes publishing to MQTT on port {config.MQTT_PORT}, start step {start}, speed x{speed:g}", flush=True)
    stop = threading.Event()
    _wait_forever(stop, lambda: bus.publish(TOPIC_REPLAY_STATUS, {"speed": fleet.speed, "paused": fleet.paused, "step": fleet.step, "ts": fleet.last_ts,
                                                                  "done": fleet.done, "published": fleet.published, "injections": inj.status()}))
    fleet.stop()
    bus.close()


# ---------------------------------------------------------------- role: ingest worker
def run_ingest() -> None:
    from ..ingest.worker import IngestWorker
    from ..store.timescale_store import TimescaleStore

    bus, store = _mqtt(), TimescaleStore(config.PG_DSN)
    store.init()
    worker = IngestWorker(bus, store)
    worker.start()
    print(f"ingest: MQTT port {config.MQTT_PORT} -> TimescaleDB port {config.PG_PORT}", flush=True)
    _wait_forever(threading.Event(), lambda: bus.publish(TOPIC_INGEST_STATUS, {"accepted": worker.accepted, "rejected": worker.rejected}), every=1.0)
    bus.close()
    store.close()


# ---------------------------------------------------------------- role: API (the nodes are reached over MQTT only)
class RemoteFleet:
    """Stands in for NodeFleet inside the API process: the same attributes, kept current from the status topic; setting
    `speed` or `paused` sends a control message to the nodes process."""

    def __init__(self, bus, start: int):
        self._bus = bus
        self._s = {"speed": 0.0, "paused": False, "step": start, "ts": None, "done": False, "published": 0, "injections": []}
        self.last_seen = 0.0
        bus.subscribe(TOPIC_REPLAY_STATUS, self._on_status)

    def _on_status(self, _topic, msg):
        if isinstance(msg, dict):
            self._s.update({k: msg[k] for k in self._s if k in msg})
            self.last_seen = time.time()

    step = property(lambda self: int(self._s["step"]))
    last_ts = property(lambda self: self._s["ts"])
    done = property(lambda self: bool(self._s["done"]))
    published = property(lambda self: int(self._s["published"]))
    injections = property(lambda self: list(self._s["injections"]))

    @property
    def speed(self) -> float:
        return float(self._s["speed"])

    @speed.setter
    def speed(self, v: float) -> None:
        self._s["speed"] = float(v)
        self._bus.publish(TOPIC_REPLAY_CONTROL, {"speed": float(v)})

    @property
    def paused(self) -> bool:
        return bool(self._s["paused"])

    @paused.setter
    def paused(self, v: bool) -> None:
        self._s["paused"] = bool(v)
        self._bus.publish(TOPIC_REPLAY_CONTROL, {"paused": bool(v)})

    def start(self) -> None:  # the nodes run in their own process
        pass

    def stop(self) -> None:
        pass


class RemoteInjector:
    """Stands in for Injector inside the API process: an injection is a request to the nodes process and its answer."""

    def __init__(self, bus, node_ids, fleet: RemoteFleet, timeout: float = 5.0):
        self._bus, self._nodes, self._fleet, self._timeout = bus, set(node_ids), fleet, timeout
        self._waiting: dict = {}
        bus.subscribe(TOPIC_INJECT_RESULT, self._on_result)

    def _on_result(self, _topic, msg):
        slot = self._waiting.get(msg.get("id")) if isinstance(msg, dict) else None
        if slot is not None:
            slot[1] = msg
            slot[0].set()

    def inject(self, kind: str, node: str, step: int | None = None, ts: str | None = None) -> dict:
        if kind not in EVENT_TYPES:
            raise ValueError(f"unknown event type {kind}")
        if node not in self._nodes:
            raise KeyError(node)
        rid = uuid.uuid4().hex
        slot = [threading.Event(), None]
        self._waiting[rid] = slot
        try:
            self._bus.publish(TOPIC_INJECT, {"id": rid, "type": kind, "node": node})
            if not slot[0].wait(self._timeout) or not slot[1].get("ok"):
                raise RuntimeError("the nodes process did not confirm the injection")
            return slot[1]["record"]
        finally:
            self._waiting.pop(rid, None)

    def status(self) -> list[dict]:
        return self._fleet.injections


def run_api(port: int, notifications: str = "dry_run", citizen: str = "off", lock: bool = False) -> None:
    if lock:  # test servers and checks: this process cannot reach Telegram or any other machine
        from ..notify.lock import lock_to_dry_run

        lock_to_dry_run()
    import uvicorn

    from ..api.app import create_app
    from ..ingest.worker import IngestWorker
    from ..runtime import Stack
    from ..store.timescale_store import TimescaleStore
    from .system import build_live

    bus, store = _mqtt(), TimescaleStore(config.PG_DSN)
    store.init()
    worker = IngestWorker(bus, store, write=False)  # readings are stored by the ingest process; here they only drive the live assessment
    worker.start()
    stack = Stack("docker", bus, store, worker)
    app = create_app(stack)
    build_live(stack, notifications=notifications, citizen=citizen, remote=True)
    stack.extras["citizen"].start()
    print(f"api: http://127.0.0.1:{port} (MQTT port {config.MQTT_PORT}, TimescaleDB port {config.PG_PORT})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main() -> None:
    ap = argparse.ArgumentParser(description="One role of the docker-mode demo (see scripts/run_demo.py --mode docker).")
    ap.add_argument("role", choices=["nodes", "ingest", "api"])
    ap.add_argument("--speed", type=float, default=600.0)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--port", type=int, default=config.API_PORT)
    ap.add_argument("--notifications", default="dry_run", choices=["dry_run", "auto"])
    ap.add_argument("--citizen", default="off", choices=["off", "auto"])
    ap.add_argument("--lock", action="store_true", help="refuse every HTTP request that leaves this machine (tests and checks)")
    a = ap.parse_args()
    if a.role == "nodes":
        run_nodes(a.speed, a.steps)
    elif a.role == "ingest":
        run_ingest()
    else:
        run_api(a.port, a.notifications, a.citizen, a.lock)


if __name__ == "__main__":
    main()
