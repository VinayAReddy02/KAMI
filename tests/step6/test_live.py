import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from kami.api.app import create_app
from kami.features.causal import SIGNALS, compute_features, compute_last
from kami.ingest.bus import InProcessBus
from kami.live.processor import BUF, LiveProcessor, _Node
from kami.live.system import build_live
from kami.runtime import Stack
from kami.simulator.inject import Injector
from kami.store import SqliteStore


@pytest.fixture(scope="module")
def scenario_node():
    sc = pd.read_parquet("data/processed/scenarios_semi_synthetic.parquet")
    return sc[sc.node_id == "scn-node-1"].sort_values("ts").iloc[30000:31500].reset_index(drop=True)


def test_streaming_features_equal_batch_features(scenario_node):
    n = scenario_node
    batch = compute_features(n)
    checked = 0
    for i in range(400, 1500, 37):
        live = compute_last({s: n[s].to_numpy()[: i + 1][-BUF:] for s in SIGNALS})
        for k, v in live.items():
            b = batch[k].iloc[i]
            if np.isnan(b):
                assert np.isnan(v), k
                continue
            assert v == pytest.approx(b, rel=1e-3, abs=2e-4), (k, i)
            checked += 1
    assert checked > 1500


def test_processor_probabilities_match_batch_pipeline():
    from kami.eval.data import domain_features  # noqa: F401
    from kami.simulator.node import build_node_frames, find_clean_start

    frames = build_node_frames(3)
    start = find_clean_start(frames)
    f = frames["node-1"]
    proc = LiveProcessor()
    proc.prime("node-1", f.iloc[start - BUF:start])
    got = []
    for j in range(start, start + 40):
        row = f.iloc[j]
        a = proc.on_reading({"node_id": "node-1", "ts": row.ts.isoformat(), "flow": row.flow, "pressure": row.pressure,
                             "turbidity": row.turbidity, "tds": row.tds})
        got.append((a["p_infra"], a["p_quality"]))
    window = f.iloc[start - BUF:start + 40].reset_index(drop=True)
    feats = pd.concat([window, compute_features(window)], axis=1)
    for d, col in (("infra", 0), ("quality", 1)):
        mod = proc.modules[d]
        want = mod.predict_proba_array(feats[proc.columns[d]].to_numpy()[BUF:])
        np.testing.assert_allclose([g[col] for g in got], want, atol=2e-3)


def test_injector_modifies_only_inside_the_event():
    n = 600
    frames = {"n": pd.DataFrame({"flow": 50 + np.sin(np.arange(n) / 40), "pressure": 45 + 0.2 * np.cos(np.arange(n) / 30)})}
    inj = Injector(frames)
    rec = inj.inject("infra_burst", "n", step=100)
    base = {"node_id": "n", "ts": "t", "flow": 50.0, "pressure": 45.0, "turbidity": 3.0, "tds": 200.0}
    before = inj.modifier("n", 99, base)
    during = inj.modifier("n", 110, base)
    assert before == base
    assert during["pressure"] < 45.0 and during["flow"] > 50.0 and during["turbidity"] == 3.0
    after = inj.modifier("n", 100 + rec["length_steps"] + 5, base)
    assert after == base
    with pytest.raises(ValueError):
        inj.inject("bogus", "n", 0)
    with pytest.raises(KeyError):
        inj.inject("combined", "zzz", 0)


def test_alert_lifecycle():
    proc = LiveProcessor()
    n = _Node()

    def a(cat, pri, i):
        return {"node_id": "n", "ts": f"2018-01-01T00:{i:02d}:00", "category": cat, "priority": pri,
                "confidence": 0.7, "explanation": f"{cat} at {i}"}

    assert proc._update_alert(n, a("Normal", "Low", 0)) is None
    ev = proc._update_alert(n, a("Infrastructure", "Low", 1))
    assert ev["status"] == "active" and ev["category"] == "Infrastructure"
    assert proc._update_alert(n, a("Infrastructure", "Low", 2)) is None  # unchanged
    ev = proc._update_alert(n, a("Combined", "High", 3))  # escalation is announced
    assert ev["category"] == "Combined" and ev["max_priority"] == "High"
    closed = None
    for i in range(4, 20):
        closed = proc._update_alert(n, a("Normal", "Low", i)) or closed
    assert closed and closed["status"] == "closed" and closed["end_ts"]
    assert len(proc.alerts) == 1 and proc.list_alerts(status="closed")[0]["id"] == 1
    assert proc.list_alerts(category="Quality") == []


def test_api_endpoints():
    stack = Stack.create(mode="fallback", store=SqliteStore(":memory:"), bus=InProcessBus())
    app = create_app(stack)
    live = build_live(stack, speed=0)
    with TestClient(app) as c:
        net = c.get("/network").json()
        assert len(net["nodes"]) == 8 and net["label"].startswith("Demo network")
        assert c.get("/nodes/node-1/state").status_code == 404  # nothing processed yet
        row = live.frames["node-1"].iloc[live.start]
        stack.bus.publish("kami/nodes/node-1/readings", {"node_id": "node-1", "ts": row.ts.isoformat(), "flow": float(row.flow),
                                                         "pressure": float(row.pressure), "turbidity": float(row.turbidity), "tds": float(row.tds)})
        st = c.get("/nodes/node-1/state").json()
        assert st["latest"]["status"] == "ok" and st["series"] and st["latest"]["explanation"]
        assert c.post("/demo/inject", json={"type": "nope", "node": "node-1"}).status_code == 422
        assert c.post("/demo/inject", json={"type": "combined", "node": "node-99"}).status_code == 404
        assert c.post("/demo/inject", json={"type": "combined", "node": "node-1"}).status_code == 200
        s = c.post("/demo/control", json={"speed": 1200, "paused": True}).json()
        assert s["speed"] == 1200 and s["paused"] is True
        assert c.get("/alerts", params={"category": "Quality"}).json() == []
