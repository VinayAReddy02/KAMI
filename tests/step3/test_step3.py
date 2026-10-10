import numpy as np
import pandas as pd
import pytest

from kami.eval.access import SplitData, TestSplitLocked, final_evaluation
from kami.eval.metrics import evaluate, merge_runs, runs
from kami.models.baselines import FixedThreshold


def toy(n=1000, events=((200, 260), (600, 650))):
    ts = pd.date_range("2020-01-01", periods=n, freq="5min")
    flag = np.zeros(n, bool)
    eid = np.full(n, "", dtype=object)
    for i, (a, b) in enumerate(events):
        flag[a:b + 1] = True
        eid[a:b + 1] = f"e{i}"
    return pd.DataFrame({"ts": ts, "node_id": "n", "infra_flag": flag, "quality_flag": False,
                         "event_id": eid, "event_type": np.where(flag, "infra_leak", "normal")})


def test_perfect_detector():
    df = toy()
    m = evaluate(df, df.infra_flag.to_numpy(), "infra")
    assert m["point"]["f1"] == 1.0 and m["event"]["f1"] == 1.0 and m["event"]["recall"] == 1.0
    assert m["false_alarms_per_day"] == 0.0 and m["latency_h"]["median"] == 0.0


def test_never_alerting():
    df = toy()
    m = evaluate(df, np.zeros(len(df), bool), "infra")
    assert m["event"]["recall"] == 0.0 and m["point"]["recall"] == 0.0 and m["event"]["f1"] == 0.0
    assert m["latency_h"]["median"] is None


def test_late_alert_latency_and_false_alarm():
    df = toy()
    pred = np.zeros(len(df), bool)
    pred[212:230] = True   # 12 steps late = 1 hour, event 0
    pred[600:605] = True   # on time, event 1
    pred[800:810] = True   # false alarm
    m = evaluate(df, pred, "infra")
    assert m["event"]["recall"] == 1.0
    assert m["latency_h"]["median"] == pytest.approx((1.0 + 0.0) / 2)
    assert m["event"]["alert_segments"] == 3 and m["event"]["false_alert_segments"] == 1
    assert m["event"]["precision"] == pytest.approx(2 / 3)
    days = (len(df) - 61 - 51) * 5 / 1440
    assert m["false_alarms_per_day"] == pytest.approx(1 / days)


def test_unscored_rows_ignored():
    df = toy()
    pred = np.zeros(len(df), bool)
    pred[800:810] = True
    scored = np.ones(len(df), bool)
    scored[800:810] = False  # e.g. ambiguous rows
    m = evaluate(df, pred, "infra", scored=scored)
    assert m["event"]["false_alert_segments"] == 0


def test_run_helpers():
    b = np.array([0, 1, 1, 0, 0, 1, 0, 1], bool)
    assert runs(b) == [(1, 2), (5, 5), (7, 7)]
    assert merge_runs(runs(b), 2) == [(1, 7)]
    assert merge_runs(runs(b), 1) == [(1, 2), (5, 7)]


def test_fixed_threshold_known():
    tr = pd.DataFrame({"x": [0.0, 2.0] * 50})
    m = FixedThreshold(["x"], k=3).fit(tr)  # mean 1, std ~1.005
    assert list(m.predict(pd.DataFrame({"x": [1.0, 5.0, -3.0]}))) == [False, True, True]


def test_test_split_is_locked(tmp_path):
    df = pd.DataFrame({"split": ["train", "val", "test"], "x": [1, 2, 3]})
    sd = SplitData(df)
    assert len(sd.train()) == 1 and len(sd.val()) == 1
    with pytest.raises(TestSplitLocked):
        sd.test()
    log = tmp_path / "log.json"
    with final_evaluation("m", "d", log):
        assert len(sd.test()) == 1
    with pytest.raises(TestSplitLocked):
        sd.test()
    with pytest.raises(TestSplitLocked):  # second evaluation of the same model/dataset is refused
        with final_evaluation("m", "d", log):
            pass
    with final_evaluation("m2", "d", log):
        pass


def test_baseline_run_opened_test_once_per_model():
    import json

    from kami.eval.run_baselines import LOG

    log = json.loads(LOG.read_text(encoding="utf-8"))
    keys = [r["key"] for r in log]
    assert len(keys) == len(set(keys)) and len(keys) == 10
