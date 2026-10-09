import json

import numpy as np
import pandas as pd
import pytest

from kami.models.fusion import (CATS, FusionB, assess, dempster_shafer, explain, priority, priority_points,
                                reliability)


def test_dempster_shafer_hand_computed():
    # r = 0.5 for both, p_infra = 1, p_quality = 0: Ai=.5 Bi=0 Ui=.5 ; Aq=0 Bq=.5 Uq=.5
    # m(I)=.25 m(IC)=.25 m(NI)=.25 m(Theta)=.25  ->  BetP = [N .1875, I .5625, Q .0625, C .1875]
    b = dempster_shafer([1.0], [0.0], [0.5], [0.5])[0]
    np.testing.assert_allclose(b, [0.1875, 0.5625, 0.0625, 0.1875])
    assert b.sum() == pytest.approx(1.0)
    full = dempster_shafer([1.0], [1.0], [1.0], [1.0])[0]
    np.testing.assert_allclose(full, [0, 0, 0, 1])
    rng = np.random.default_rng(0)
    p = dempster_shafer(rng.random(50), rng.random(50), rng.random(50), rng.random(50))
    np.testing.assert_allclose(p.sum(1), 1.0)


def test_reliability_grows_with_persistence_and_recurrence():
    r0 = reliability([0], [0], 0.4, 6, 0.3)
    r1 = reliability([12], [0], 0.4, 6, 0.3)
    r2 = reliability([12], [3], 0.4, 6, 0.3)
    assert r0 == pytest.approx(0.4) and r0 < r1 < r2 <= 1.0
    assert r1 == pytest.approx(0.4 + 0.6 * (1 - np.exp(-2)))


def test_fusion_b_decision_rule():
    df = pd.DataFrame({"p_infra": [0.9, 0.9, 0.2, 0.9], "p_quality": [0.1, 0.9, 0.9, 0.9],
                       "infra_persist_steps": [100, 100, 100, 0], "quality_persist_steps": [0, 100, 100, 100],
                       "infra_recurrence": [1, 1, 1, 1], "quality_recurrence": [0, 1, 1, 1]})
    m = FusionB(True, True)
    m.params = (0.4, 6, 0.0, 0.5)
    got = m.predict(df)
    # row 3: infra transient (persist 0 -> r = 0.4, Bel = 0.36 < 0.5) is not reported; quality is
    assert list(got) == [1, 3, 2, 2]
    assert [CATS[i] for i in got] == ["Infrastructure", "Combined", "Quality", "Quality"]


def test_priority_rule():
    assert priority("Normal", 500, 1.0, 5) == "Low"
    assert priority("Infrastructure", 0, 0.5, 0) == "Low"
    assert priority("Quality", 12, 0.5, 0) == "Medium"
    assert priority("Infrastructure", 12, 0.95, 0) == "High"
    assert priority("Combined", 80, 0.95, 2) == "Critical"
    assert priority_points("Combined", 80, 0.95, 2) == 5
    # persistence and intensity never lower the priority
    base = ["Low", "Medium", "High", "Critical"]
    for cat in CATS:
        ranks = [base.index(priority(cat, s, 0.5, 0)) for s in (0, 12, 72, 200)]
        assert ranks == sorted(ranks)
        ranks = [base.index(priority(cat, 12, i, 0)) for i in (0.1, 0.5, 0.9, 1.0)]
        assert ranks == sorted(ranks)


ROW = {"p_infra": 0.93, "p_quality": 0.61, "infra_suddenness": 0.78, "quality_suddenness": 0.12,
       "infra_persist_steps": 30, "quality_persist_steps": 6, "infra_recurrence": 2, "quality_recurrence": 1}


def test_explanation_quotes_real_values():
    a = assess(ROW, np.array([0.05, 0.1, 0.05, 0.8]))
    assert a["category"] == "Combined" and a["confidence"] == pytest.approx(0.8)
    e = a["explanation"]
    assert e and "0.93" in e and "0.61" in e and "2.5 h" in e and "0.78" in e and "2 episode" in e
    n = explain({**ROW, "p_infra": 0.04, "infra_persist_steps": 0}, "Normal", 0.9, "Low")
    assert "0.04" in n and "currently below threshold" in n
    q = assess(ROW, np.array([0.1, 0.1, 0.7, 0.1]))
    assert q["category"] == "Quality" and "0.93" not in q["explanation"] and "0.61" in q["explanation"]
    k = assess(ROW, np.array([0.1, 0.1, 0.7, 0.1]), k=1)  # explicit decision overrides argmax
    assert k["category"] == "Infrastructure"


def test_fusion_outputs_and_test_split_opened_once():
    from kami.eval.data import RES

    log = json.loads((RES / "fusion" / "test_eval_log.json").read_text(encoding="utf-8"))
    keys = [r["key"] for r in log]
    assert len(keys) == len(set(keys)) == 17  # 8 models x 2 datasets + sample assessments
    s = json.loads((RES / "fusion" / "sample_assessments.json").read_text(encoding="utf-8"))
    assert s and all(x["explanation"] and 0 <= x["confidence"] <= 1 and x["priority"] in
                     ("Low", "Medium", "High", "Critical") for x in s)
