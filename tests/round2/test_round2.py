import numpy as np
import pandas as pd
import pytest

from kami.eval.access import SplitData, TestSplitLocked, final_evaluation
from kami.eval.bootstrap import bootstrap_any
from kami.eval.fast_eval import AnyEvaluator
from kami.eval.fusion_tune import CAP, FusionBDesign, VotingDesign, _key, select
from kami.eval.metrics import evaluate


def toy(n=3000, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2020-01-01", periods=n, freq="5min")
    flag = np.zeros(n, bool)
    eid = np.full(n, "", dtype=object)
    types = ["infra_leak", "quality_tds_shift", "combined"]
    et = np.full(n, "normal", dtype=object)
    for i, a in enumerate((300, 900, 1500, 2200)):
        flag[a:a + 80] = True
        eid[a:a + 80] = f"e{i}"
        et[a:a + 80] = types[i % 3]
    df = pd.DataFrame({"ts": ts, "node_id": "n", "any_flag": flag, "infra_flag": flag, "quality_flag": False,
                       "event_id": eid, "event_type": et})
    ev = df[df.any_flag].groupby("event_id").agg(type=("event_type", "first"), start=("ts", "min"), end=("ts", "max")).reset_index()
    ev["node_id"] = "n"
    return df, ev


def test_fast_evaluator_equals_reference_metrics():
    df, ev = toy()
    rng = np.random.default_rng(1)
    for _ in range(8):
        pred = rng.random(len(df)) < 0.03
        pred[310:330] = True
        scored = rng.random(len(df)) > 0.05
        ref = evaluate(df, pred, "any", events=ev, scored=scored)
        got = AnyEvaluator(df, ev, scored)(pred)
        assert got["f1"] == pytest.approx(ref["event"]["f1"])
        assert got["precision"] == pytest.approx(ref["event"]["precision"])
        assert got["recall"] == pytest.approx(ref["event"]["recall"])
        assert got["fa_per_day"] == pytest.approx(ref["false_alarms_per_day"])


def test_constrained_key_prefers_feasible_then_lowest_false_alarms():
    ok_low = {"f1": 0.5, "fa_per_day": 0.4}
    ok_high = {"f1": 0.7, "fa_per_day": 0.5}
    bad = {"f1": 0.95, "fa_per_day": 2.0}
    assert _key(ok_high) > _key(ok_low) > _key(bad)
    worse = {"f1": 0.99, "fa_per_day": 3.0}
    assert _key(bad) > _key(worse)  # nothing feasible: fewer false alarms wins
    assert CAP == 0.5


def test_selection_tie_goes_to_interpretable_design():
    r = {"F-A": {"oof": {"f1": 0.800, "fa_per_day": 0.2}}, "F-B": {"oof": {"f1": 0.797, "fa_per_day": 0.2}}}
    assert select(r)[0] == "F-B"
    r["F-A"]["oof"]["f1"] = 0.81
    assert select(r)[0] == "F-A"
    r["F-A"]["oof"] = {"f1": 0.9, "fa_per_day": 0.9}  # infeasible A loses to feasible B
    assert select(r)[0] == "F-B"


def test_decision_rules():
    df = pd.DataFrame({"p_infra": [0.99, 0.2, 0.99, 0.1], "p_quality": [0.1, 0.99, 0.99, np.nan],
                       "infra_persist_steps": [50, 0, 50, 0], "quality_persist_steps": [0, 50, 50, 0],
                       "infra_recurrence": [1, 0, 1, 0], "quality_recurrence": [0, 1, 1, 0]})
    assert list(VotingDesign().decide(df, (0.5, 0.5))) == [1, 2, 3, 0]  # last row has no evidence -> Normal
    d = FusionBDesign(True)
    assert list(d.decide(df, (0.4, 6, 0.0, 0.9, 0.9))) == [1, 2, 3, 0]
    # a transient (persistence 0) stream is discounted by r_min and no longer clears the same threshold
    t = df.assign(infra_persist_steps=[0, 0, 0, 0])
    assert list(d.decide(t, (0.4, 6, 0.0, 0.9, 0.9)))[0] == 0


def test_bootstrap_is_deterministic_and_brackets_the_estimate():
    df, ev = toy()
    pred = np.zeros(len(df), bool)
    pred[305:330] = pred[905:920] = pred[1505:1520] = True
    pred[2000:2010] = True  # a false alarm
    e = AnyEvaluator(df, ev, np.ones(len(df), bool))
    d = e(pred, details=True)
    ok, _ = e.category_correct(np.where(pred, 1, 0))
    a, b = bootstrap_any(d, ok, n=300, seed=3), bootstrap_any(d, ok, n=300, seed=3)
    assert a == b
    assert a["recall"][0] <= d["recall"] <= a["recall"][1] and a["recall"][0] < a["recall"][1]
    assert a["fa_per_day"][0] <= d["fa_per_day"] * 3 and len(a["category_accuracy"]) == 2


def test_category_correctness_by_modal_prediction():
    df, ev = toy()
    e = AnyEvaluator(df, ev, np.ones(len(df), bool))
    pred = np.zeros(len(df), int)
    pred[300:380] = 1  # event 0 is infra_leak -> correct
    pred[900:980] = 1  # event 1 is quality_tds_shift -> wrong category
    ok, types = e.category_correct(pred)
    assert list(types) == ["infra_leak", "quality_tds_shift", "combined", "infra_leak"]
    assert list(ok) == [True, False, False, False]


def test_held_out_sets_are_locked(tmp_path):
    """Regression test for the 2026-10-10 incident (baseline runner scored test_v2 before the freeze)."""
    from kami.eval.data import DATASETS, LOCKED_DATASETS, LOCKED_LOGS
    from kami.eval.run_baselines import BASELINE_DATASETS

    assert not set(DATASETS) & set(LOCKED_DATASETS)
    assert not set(BASELINE_DATASETS) & set(LOCKED_DATASETS)
    for name in LOCKED_DATASETS:
        # a locked set cannot be opened with any log other than its designated one
        with pytest.raises(TestSplitLocked):
            with final_evaluation("m", name, tmp_path / "other.json"):
                pass
        assert name in LOCKED_LOGS
    df = pd.DataFrame({"split": ["train", "test"], "x": [1, 2]})
    locked = SplitData(df, "scenarios_v3")
    with pytest.raises(TestSplitLocked):
        locked.test()
    # opening a different (exposed) dataset must not unlock a held-out frame
    with final_evaluation("m", "scenarios", tmp_path / "v1.json"):
        assert len(SplitData(df).test()) == 1
        with pytest.raises(TestSplitLocked):
            locked.test()
    df.attrs["kami_dataset"] = "scenarios_v2"
    assert SplitData(df).dataset == "scenarios_v2"


def test_freeze_detects_changes(tmp_path, monkeypatch):
    import json

    from kami.eval import freeze

    f = tmp_path / "a.txt"
    f.write_text("one")
    cfg = tmp_path / "frozen.json"
    cfg.write_text(json.dumps({"files_sha256": {"a.txt": freeze._sha(f)}}))
    monkeypatch.setattr(freeze, "ROOT", tmp_path)
    monkeypatch.setattr(freeze, "CONFIG", cfg)
    monkeypatch.setattr(freeze, "_files", lambda: [f])
    assert freeze.verify()
    f.write_text("two")
    with pytest.raises(SystemExit):
        freeze.verify()


def test_v2_dataset_properties():
    import json

    from kami.eval.data import RES

    info = json.loads((RES / "splits" / "test_v2_info.json").read_text(encoding="utf-8"))
    assert info["seed_v2"] == 20261010 and info["same_seed_identical"] and info["no_straddle"]
    assert info["v1_v2_test_events_overlap"] == 0 and info["train_val_identical_to_v1"] and info["test_events_differ_from_v1"]
    assert set(info["events_per_type"].values()) == {12}
