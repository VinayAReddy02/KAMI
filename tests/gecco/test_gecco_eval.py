"""GECCO evaluation pieces (Round 7, G3/G4): variant A is the frozen rule itself, variant B's rule, the scoring."""
import json

import numpy as np
import pandas as pd

from kami import config
from kami.gecco import evaluate as E
from kami.models.fusion import reliability


def seq(p):
    n = len(p)
    return pd.DataFrame({"ts": pd.date_range("2017-10-01", periods=n, freq="5min"), "node_id": "gecco", "ambiguous": False,
                         "quality_flag": False, "event_id": "", "event_type": ""}), np.asarray(p, float)


def test_variant_a_rule_is_the_frozen_quality_decision():
    rng = np.random.default_rng(0)
    p = np.clip(np.cumsum(rng.normal(0, 0.08, 3000)), 0, 1)  # slow random walk: runs of high and low evidence
    p[100:110] = np.nan
    s, p = seq(p)
    cfg = json.loads((config.ROOT / "results" / "fusion" / "frozen_config.json").read_text(encoding="utf-8"))
    rm, tp, lam, _, gq = cfg["designs"]["F-B"]["final_params"]
    from kami.live.frozen import FrozenRule

    t = E.with_temporal(s, p)
    cat = FrozenRule().predict(t)
    expected = np.nan_to_num(reliability(t.quality_persist_steps, t.quality_recurrence, rm, tp, lam) * np.nan_to_num(p)) >= gq
    assert (np.isin(cat, (2, 3)) == (expected & ~np.isnan(p))).all() and np.isin(cat, (2, 3)).any() and not (cat == 1).any()
    assert (E.alert_b(s, p, (rm, tp, lam, gq)) == np.isin(cat, (2, 3))).all()  # B with A's parameters gives A's decision


def test_score_counts_events_and_false_alarms():
    s, _ = seq(np.zeros(3 * 288))
    s.loc[100:105, "quality_flag"] = True
    s.loc[100:105, ["event_id", "event_type"]] = ["gecco-val-001", "real_quality_event"]
    pred = np.zeros(len(s), bool)
    pred[102:104] = True  # detects the event 10 minutes after its start
    pred[400:403] = True  # one false alarm
    m = E.score(s, pred, np.ones(len(s), bool))
    assert m["event"]["events"] == 1 and m["event"]["detected"] == 1 and m["event"]["false_alert_segments"] == 1
    assert abs(m["latency_h"]["median"] - 10 / 60) < 1e-9 and m["objective"]["f1_event_counted"] == 2 / 3
    assert E.key(m)[0] == 1  # 1 false alarm in about 3 days is within the cap of 0.5 per day
