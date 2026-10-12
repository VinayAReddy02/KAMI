"""Docker mode (Round 6, Part B). The first tests need no Docker: they run the control protocol of the separate
processes over the in-process bus. The last ones talk to the real Mosquitto and TimescaleDB and are skipped when the
stack is not up."""
import threading
import time

import pytest

from kami import config
from kami.ingest.bus import InProcessBus
from kami.ingest.worker import IngestWorker
from kami.live import procs
from kami.store import SqliteStore

STACK_DOWN = pytest.mark.skipif(not config.stack_up(), reason="MQTT broker and TimescaleDB not running (no Docker)")
R = {"node_id": "n1", "ts": "2018-01-07T16:50:00", "flow": 1.0, "pressure": 2.0, "turbidity": None, "tds": 4.0}


def test_listen_only_worker_notifies_but_does_not_store():
    bus, store = InProcessBus(), SqliteStore(":memory:")
    store.init()
    seen = []
    w = IngestWorker(bus, store, write=False)  # the API process of the docker mode
    w.listeners.append(seen.append)
    w.start()
    bus.publish("kami/nodes/n1/readings", R)
    bus.publish("kami/nodes/n1/readings", {**R, "flow": "bad"})
    assert (w.accepted, w.rejected, store.count()) == (1, 1, 0) and seen[0]["node_id"] == "n1"
    writer = IngestWorker(bus, store)  # the ingest process
    writer.start()
    bus.publish("kami/nodes/n1/readings", R)
    assert store.count() == 1


def test_store_clear_empties_readings_assessments_and_complaints():
    s = SqliteStore(":memory:")
    s.init()
    s.write_reading(R)
    s.write_assessment({"node_id": "n1", "ts": R["ts"], "category": "Normal"})
    assert s.write_complaint({"status": "open"}) == 1
    s.clear()
    assert s.count() == 0 and s.read_assessments() == [] and s.read_complaints() == []


def test_remote_fleet_and_injector_speak_the_control_protocol():
    """What the API process sees of the nodes process: status in, control out, an injection as request and answer."""
    bus = InProcessBus()
    fleet = procs.RemoteFleet(bus, start=1870)
    inj = procs.RemoteInjector(bus, ["node-1", "node-2"], fleet, timeout=0.5)
    assert (fleet.step, fleet.last_ts, fleet.done, fleet.speed, fleet.paused) == (1870, None, False, 0.0, False)
    sent = []
    bus.subscribe(procs.TOPIC_REPLAY_CONTROL, lambda t, m: sent.append(m))
    fleet.speed = 1200
    fleet.paused = True
    assert sent == [{"speed": 1200.0}, {"paused": True}] and fleet.speed == 1200.0 and fleet.paused is True
    bus.publish(procs.TOPIC_REPLAY_STATUS, {"speed": 600.0, "paused": False, "step": 1900, "ts": "2018-01-07T14:20:00", "done": False, "published": 240,
                                            "injections": [{"id": "inject-001"}]})
    assert (fleet.step, fleet.last_ts, fleet.speed, fleet.paused, fleet.published) == (1900, "2018-01-07T14:20:00", 600.0, False, 240)
    assert inj.status() == [{"id": "inject-001"}]
    with pytest.raises(ValueError):
        inj.inject("nope", "node-1")
    with pytest.raises(KeyError):
        inj.inject("infra_burst", "node-99")
    with pytest.raises(RuntimeError, match="did not confirm"):  # no nodes process is answering
        inj.inject("infra_burst", "node-1")

    def nodes_side(_topic, msg):  # what run_nodes does with an injection request
        ok = msg["node"] == "node-1"
        bus.publish(procs.TOPIC_INJECT_RESULT, {"id": msg["id"], "ok": ok, "record": {"id": "inject-002", "node_id": msg["node"], "type": msg["type"]}} if ok
                    else {"id": msg["id"], "ok": False, "error": "KeyError"})

    bus.subscribe(procs.TOPIC_INJECT, nodes_side)
    assert inj.inject("infra_burst", "node-1") == {"id": "inject-002", "node_id": "node-1", "type": "infra_burst"}
    with pytest.raises(RuntimeError):
        inj.inject("infra_burst", "node-2")  # refused by the nodes process


def test_mode_is_fallback_unless_asked_for_or_the_stack_is_up(monkeypatch):
    monkeypatch.setenv("KAMI_MODE", "fallback")
    assert config.resolve_mode() == "fallback"
    monkeypatch.setenv("KAMI_MODE", "docker")
    assert config.resolve_mode() == "docker"
    monkeypatch.delenv("KAMI_MODE")
    monkeypatch.setattr(config, "stack_up", lambda: False)
    assert config.resolve_mode() == "fallback"  # a running Docker Desktop without the containers changes nothing
    monkeypatch.setattr(config, "stack_up", lambda: True)
    assert config.resolve_mode() == "docker"
    assert config.port_open(9, timeout=0.2) is False


@STACK_DOWN
def test_timescale_returns_the_same_time_format_as_sqlite_and_keeps_tickets():
    from kami.store.timescale_store import TimescaleStore

    s = TimescaleStore(config.PG_DSN)
    s.init()
    s.clear()
    s.write_reading({**R, "node_id": "t-node"})
    s.write_reading({**R, "node_id": "t-node", "ts": "2018-01-07T16:55:00"})
    rows = s.read_readings(node="t-node")
    assert [r["ts"] for r in rows] == ["2018-01-07T16:50:00", "2018-01-07T16:55:00"]  # exactly as the replay wrote them
    assert s.read_readings(node="t-node", since="2018-01-07T16:55:00")[0]["ts"] == "2018-01-07T16:55:00"
    assert s.nodes() == [{"node_id": "t-node", "n": 2, "first_ts": "2018-01-07T16:50:00", "last_ts": "2018-01-07T16:55:00"}]
    s.write_assessment({"node_id": "t-node", "ts": R["ts"], "category": "Normal"})
    assert s.read_assessments("t-node")[0]["category"] == "Normal"
    first, second = s.write_complaint({"status": "open", "lat": 12.9, "node_name": "X"}), s.write_complaint({"status": "open"})
    got = s.read_complaints()
    assert (first, second) == (1, 2) and [c["id"] for c in got] == [2, 1] and got[1]["node_name"] == "X"
    s.clear()
    assert s.count() == 0 and s.read_complaints() == [] and s.read_assessments() == [] and s.write_complaint({"status": "open"}) == 1
    s.clear()
    s.close()


@STACK_DOWN
def test_two_mqtt_clients_exchange_control_messages_through_the_broker():
    """The API process and the nodes process are separate MQTT clients: a request from one reaches the other."""
    api_side, nodes_side = procs._mqtt(), procs._mqtt()
    try:
        fleet = procs.RemoteFleet(api_side, start=0)
        inj = procs.RemoteInjector(api_side, ["node-1"], fleet, timeout=5.0)
        got = threading.Event()
        nodes_side.subscribe(procs.TOPIC_REPLAY_CONTROL, lambda t, m: got.set() if m == {"paused": True} else None)
        nodes_side.subscribe(procs.TOPIC_INJECT, lambda t, m: nodes_side.publish(procs.TOPIC_INJECT_RESULT, {"id": m["id"], "ok": True, "record": {"node_id": m["node"]}}))
        time.sleep(0.5)
        fleet.paused = True
        assert got.wait(5)
        assert inj.inject("infra_burst", "node-1") == {"node_id": "node-1"}
        nodes_side.publish(procs.TOPIC_REPLAY_STATUS, {"step": 77, "ts": "2018-01-07T00:00:00"})
        for _ in range(50):
            if fleet.step == 77:
                break
            time.sleep(0.1)
        assert fleet.step == 77 and fleet.last_ts == "2018-01-07T00:00:00"
    finally:
        api_side.close()
        nodes_side.close()


@STACK_DOWN
def test_the_three_process_demo_takes_an_injection_as_soon_as_it_is_launched(tmp_path):
    """launch_docker returns only when the nodes are replaying: a client may inject at once (the browser tests do)."""
    import os

    import httpx

    from kami.live.launch import launch_docker
    from kami.notify.settings import CHAT, ENABLE, TOKEN

    env = {k: v for k, v in os.environ.items() if k not in (TOKEN, CHAT, ENABLE, "KAMI_CITIZEN_ENABLE", "CITIZEN_ALLOWED_CHAT_IDS")}
    env.update({"KAMI_NOTIFY_ENV_FILE": str(tmp_path / "no_such.env"), "KAMI_NOTIFY_DIR": str(tmp_path / "notifications"),
                "KAMI_CITIZEN_DIR": str(tmp_path / "citizen")})  # no bot settings; the API process is locked to dry run as well
    h = launch_docker(speed=3000, port=8231, lock=True, env=env)
    try:
        r = httpx.post(h.url + "/demo/inject", json={"type": "infra_burst", "node": "node-2"}, timeout=15)
        health = httpx.get(h.url + "/health", timeout=10).json()
        alive = h.alive()
    finally:
        gone = h.stop()
    assert r.status_code == 200 and r.json()["node_id"] == "node-2"
    assert health["mode"] == "docker" and health["accepted"] > 0
    assert all(alive.values()) and all(gone.values())


def test_ready_answers_503_until_the_first_reading_arrives():
    """The readiness probe of the browser tests and of the docker launcher: the API alone is not a running demo."""
    from fastapi.testclient import TestClient

    from kami.api.app import create_app
    from kami.runtime import Stack

    stack = Stack.create(mode="fallback", store=SqliteStore(":memory:"), bus=InProcessBus())
    with TestClient(create_app(stack)) as c:
        assert c.get("/health").status_code == 200
        r = c.get("/ready")
        assert r.status_code == 503 and r.json()["ready"] is False
        stack.bus.publish("kami/nodes/n1/readings", R)
        r = c.get("/ready")
        assert r.status_code == 200 and r.json() == {"ready": True, "accepted": 1}
