import socket

import pytest
from fastapi.testclient import TestClient

from kami.api.app import create_app
from kami.ingest.bus import InProcessBus, topic_matches
from kami.runtime import Stack
from kami.store import SqliteStore, validate_reading


def _port_open(port):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        return s.connect_ex(("localhost", port)) == 0
    finally:
        s.close()


def _stores():
    out = [pytest.param(lambda: SqliteStore(":memory:"), id="sqlite")]

    def ts():
        from kami import config
        from kami.store.timescale_store import TimescaleStore

        return TimescaleStore(config.PG_DSN)

    out.append(pytest.param(ts, id="timescale",
                            marks=pytest.mark.skipif(not _port_open(5432), reason="TimescaleDB not running (no Docker)")))
    return out


def _buses():
    def mq():
        from kami.ingest.bus import MqttBus

        return MqttBus("localhost", 1883)

    return [pytest.param(InProcessBus, id="inproc"),
            pytest.param(mq, id="mqtt", marks=pytest.mark.skipif(not _port_open(1883), reason="Mosquitto not running (no Docker)"))]


R = {"node_id": "n1", "ts": "2018-01-01T00:00:00", "flow": 1.0, "pressure": 2.0, "turbidity": None, "tds": 4.0}


@pytest.mark.parametrize("mk", _stores())
def test_store_contract(mk):
    s = mk()
    s.init()
    base = s.count()
    s.write_reading(R)
    s.write_reading({**R, "node_id": "n2", "ts": "2018-01-01T00:05:00"})
    assert s.count() == base + 2
    rows = s.read_readings(node="n1")
    assert rows[-1]["pressure"] == 2.0 and rows[-1]["turbidity"] is None
    assert {n["node_id"] for n in s.nodes()} >= {"n1", "n2"}
    assert all(r["ts"] >= "2018-01-01T00:05" for r in s.read_readings(node="n2", since="2018-01-01T00:05:00"))
    s.write_assessment({"node_id": "n1", "ts": R["ts"], "category": "Normal"})
    assert s.read_assessments("n1")[0]["category"] == "Normal"
    s.close()


@pytest.mark.parametrize("mk", _buses())
def test_bus_contract(mk):
    import time

    bus = mk()
    got = []
    bus.subscribe("kami/nodes/+/readings", lambda t, p: got.append((t, p)))
    time.sleep(0.3)
    bus.publish("kami/nodes/a/readings", {"x": 1})
    bus.publish("kami/other", {"x": 2})
    for _ in range(30):
        if got:
            break
        time.sleep(0.1)
    assert got == [("kami/nodes/a/readings", {"x": 1})]
    bus.close()


def test_topic_matching():
    assert topic_matches("kami/nodes/+/readings", "kami/nodes/n1/readings")
    assert not topic_matches("kami/nodes/+/readings", "kami/nodes/n1/x")
    assert topic_matches("kami/#", "kami/a/b")
    assert not topic_matches("kami/nodes/+", "kami/nodes/a/b")


def test_validate_reading():
    assert validate_reading(R)["flow"] == 1.0
    for bad in ({}, {**R, "node_id": ""}, {**R, "flow": "x"}, {**R, "pressure": float("nan")}, {**R, "ts": None}, [1]):
        with pytest.raises(ValueError):
            validate_reading(bad)


def test_worker_and_api():
    stack = Stack.create(mode="fallback", store=SqliteStore(":memory:"), bus=InProcessBus())
    with TestClient(create_app(stack)) as c:
        stack.bus.publish("kami/nodes/n1/readings", R)
        stack.bus.publish("kami/nodes/n1/readings", {**R, "flow": "bad"})
        assert stack.worker.accepted == 1 and stack.worker.rejected == 1
        assert c.get("/health").json()["status"] == "ok"
        assert c.get("/nodes").json()[0]["node_id"] == "n1"
        assert len(c.get("/readings", params={"node": "n1"}).json()) == 1
        with c.websocket_connect("/ws") as ws:
            stack.bus.publish("kami/nodes/n1/readings", {**R, "ts": "2018-01-01T00:10:00"})
            msg = ws.receive_json()
            assert msg["type"] == "reading" and msg["data"]["ts"].endswith("00:10:00")
