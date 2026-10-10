import json

import numpy as np
import pandas as pd
import pytest

from kami.eval.access import SplitData, TestSplitLocked, final_evaluation, is_logged, mark_completed
from kami.eval.bootstrap import METRICS, intervals, paired_diff, replicates
from kami.eval.fast_eval import AnyEvaluator
from kami.eval.fusion_tune import CAP, FusionADesign, FusionBDesign, VotingDesign, _key, fusion_mask, select
from kami.eval.metrics import evaluate
from kami.eval.verdict import decide


def toy(n=3000, kinds=("infra_leak", "quality_tds_shift", "combined")):
    """One node, four events of 80 rows. Combined events: the quality part covers only the first 20 rows."""
    ts = pd.date_range("2020-01-01", periods=n, freq="5min")
    infra, qual = np.zeros(n, bool), np.zeros(n, bool)
    eid = np.full(n, "", dtype=object)
    et = np.full(n, "normal", dtype=object)
    for i, a in enumerate((300, 900, 1500, 2200)):
        k = kinds[i % len(kinds)]
        eid[a:a + 80] = f"e{i}"
        et[a:a + 80] = k
        if k.startswith("infra"):
            infra[a:a + 80] = True
        elif k.startswith("quality"):
            qual[a:a + 80] = True
        else:
            infra[a:a + 80] = True
            qual[a:a + 20] = True
    df = pd.DataFrame({"ts": ts, "node_id": "n", "infra_flag": infra, "quality_flag": qual, "any_flag": infra | qual,
                       "event_id": eid, "event_type": et})
    df["y"] = df.infra_flag.astype(int) + 2 * df.quality_flag.astype(int)
    ev = df[df.any_flag].groupby("event_id").agg(type=("event_type", "first"), start=("ts", "min"), end=("ts", "max")).reset_index()
    ev["node_id"] = "n"
    return df, ev


# ------------------------------------------------------------------ metrics
def test_fast_evaluator_equals_reference_metrics():
    df, ev = toy()
    rng = np.random.default_rng(1)
    for _ in range(8):
        pred = rng.random(len(df)) < 0.03
        pred[310:330] = True
        scored = rng.random(len(df)) > 0.05
        ref = evaluate(df, pred, "any", events=ev, scored=scored)
        got = AnyEvaluator(df, ev, scored)(pred)
        for a, b in (("f1", "f1"), ("precision", "precision"), ("recall", "recall"),
                     ("f1_event_counted", "f1_event_counted"), ("precision_event_counted", "precision_event_counted")):
            assert got[a] == pytest.approx(ref["event"][b])
        assert got["fa_per_day"] == pytest.approx(ref["false_alarms_per_day"])
        assert got["segments"] == ref["event"]["alert_segments"] and got["false_segments"] == ref["event"]["false_alert_segments"]
        assert got["latency_median_h"] == pytest.approx(ref["latency_h"]["median"])
        assert got["latency_p90_h"] == pytest.approx(ref["latency_h"]["p90"])


def test_event_counted_precision_ignores_fragmentation():
    """An alert that breaks into three pieces inside one event must not look better than a solid one."""
    df, ev = toy()
    e = AnyEvaluator(df, ev, np.ones(len(df), bool))
    solid, frag = np.zeros(len(df), bool), np.zeros(len(df), bool)
    for a in (300, 900, 1500, 2200):
        solid[a + 5:a + 75] = True
        frag[a + 5:a + 15] = frag[a + 35:a + 45] = frag[a + 65:a + 75] = True  # gaps of 20 rows > merge gap of 12
    for p in (solid, frag):
        p[2000:2010] = p[2700:2710] = True  # two false alarms
    s, f = e(solid, details=True), e(frag, details=True)
    assert s["true_segments"] == 4 and f["true_segments"] == 12 and s["false_segments"] == f["false_segments"] == 2
    assert f["precision"] > s["precision"]  # the segment-based number rewards the fragments ...
    assert f["precision_event_counted"] == s["precision_event_counted"] == pytest.approx(4 / 6)  # ... this one does not
    assert f["f1_event_counted"] == s["f1_event_counted"]
    assert list(f["detail"]["event_true_segments"]) == [3, 3, 3, 3]
    assert f["detail"]["day_false_segments"].sum() == 2
    assert s["alert_fraction"] > f["alert_fraction"] > 0 and f["normal_alert_fraction"] == pytest.approx(20 / (3000 - 320))


def test_category_accuracy_is_one_for_a_prediction_equal_to_the_labels():
    """Regression test for the review finding: the old 'most frequent category in the window' rule marked a perfect
    prediction wrong on combined events whose quality part is short."""
    df, ev = toy()
    e = AnyEvaluator(df, ev, np.ones(len(df), bool))
    ok, types = e.category_correct(df.y.to_numpy())
    assert list(types) == ["infra_leak", "quality_tds_shift", "combined", "infra_leak"]
    assert ok.all()
    # an undetected event is wrong; reporting only one stream of a combined event is wrong; an extra stream is wrong
    pred = df.y.to_numpy().copy()
    pred[300:380] = 0  # event 0 missed
    pred[1500:1520] = 1  # combined event: quality part reported as infrastructure only
    pred[2250] = 3  # infra-only event: one row claims quality as well
    ok, _ = e.category_correct(pred)
    assert list(ok) == [False, True, False, False]
    # unscored rows do not count as reports
    scored = np.ones(len(df), bool)
    scored[2250] = False
    assert list(AnyEvaluator(df, ev, scored).category_correct(pred)[0]) == [False, True, False, True]


# ------------------------------------------------------------------ tuning objective
def _m(f1, fa, frac=0.1):
    return {"f1_event_counted": f1, "fa_per_day": fa, "alert_fraction": frac, "f1": 0.0}


def test_constrained_key_prefers_feasible_then_lowest_false_alarms_then_fewest_alert_rows():
    assert CAP == 0.5
    ok_low, ok_high, bad, worse = _m(0.5, 0.4), _m(0.7, 0.5), _m(0.95, 2.0), _m(0.99, 3.0)
    assert _key(ok_high) > _key(ok_low) > _key(bad) > _key(worse)
    # exact ties on the objective go to the rule that alerts on fewer rows (the stricter one)
    assert _key(_m(0.7, 0.2, frac=0.05)) > _key(_m(0.7, 0.2, frac=0.60))
    # the segment-based F1 plays no role in the objective
    a, b = _m(0.7, 0.2), _m(0.7, 0.2)
    b["f1"] = 0.99
    assert _key(a) == _key(b)


def test_selection_tie_goes_to_interpretable_design():
    r = {"F-A": {"oof": _m(0.800, 0.2)}, "F-B": {"oof": _m(0.797, 0.2)}}
    assert select(r)[0] == "F-B"
    r["F-A"]["oof"] = _m(0.81, 0.2)
    assert select(r)[0] == "F-A"
    r["F-A"]["oof"] = _m(0.9, 0.9)  # infeasible A loses to feasible B
    assert select(r)[0] == "F-B"


def _evidence_frame(n=600, seed=0, quality=True):
    rng = np.random.default_rng(seed)
    p_i = rng.random(n)
    p_q = rng.random(n) if quality else np.zeros(n)
    d = {"p_infra": p_i, "p_quality": p_q}
    for s, p in (("infra", p_i), ("quality", p_q)):
        d[f"{s}_persist_steps"] = (rng.integers(0, 60, n) * (p >= 0.5)).astype(float)
        d[f"{s}_persist_frac"] = rng.random(n) * (p >= 0.5)
        d[f"{s}_suddenness"] = rng.random(n) * (p >= 0.5)
        d[f"{s}_recurrence"] = rng.integers(0, 4, n).astype(float) if (quality or s == "infra") else np.zeros(n)
    return pd.DataFrame(d)


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


def test_fusion_mask_excludes_ambiguous_rows():
    df = pd.DataFrame({"p_infra": [0.9, 0.9, np.nan], "p_quality": [0.0, 0.0, 0.0], "ambiguous": [False, True, False]})
    assert list(fusion_mask(df)) == [True, False, False]
    assert list(fusion_mask(df.drop(columns="ambiguous"))) == [True, True, False]


def test_fb_without_temporal_is_exactly_threshold_voting():
    df = _evidence_frame()
    for gi, gq in ((0.3, 0.7), (0.98, 0.8), (0.5, 0.5)):
        assert (FusionBDesign(False).decide(df, (1.0, 1.0, 0.0, gi, gq)) == VotingDesign().decide(df, (gi, gq))).all()
    c = FusionBDesign(True).decide(df, (0.4, 6, 0.0, 0.5, 0.5))
    assert (c != VotingDesign().decide(df, (0.5, 0.5))).any()


def test_fusion_a_works_on_single_stream_data():
    """BattLeDIM has no quality stream: p_quality = 0 everywhere and only classes Normal/Infrastructure exist."""
    df = _evidence_frame(quality=False)
    y = (df.p_infra.to_numpy() > 0.6).astype(int)
    for temporal in (True, False):
        out = FusionADesign(temporal).fit(df, y).decide(df, (0.5, 0.5))
        assert set(np.unique(out)) <= {0, 1} and (out == y).mean() > 0.9


# ------------------------------------------------------------------ bootstrap and verdict
def _detail(pred, df, ev):
    e = AnyEvaluator(df, ev, np.ones(len(df), bool))
    d = e(pred > 0, details=True)
    ok, _ = e.category_correct(pred)
    return d, ok


def test_bootstrap_is_deterministic_paired_and_keeps_fragments_with_their_event():
    df, ev = toy()
    y = df.y.to_numpy()
    a = y.copy()
    a[300:380] = 0  # misses event 0
    a[2000:2010] = 1  # one false alarm
    b = y.copy()
    b[2000:2010] = b[2700:2710] = 1  # detects everything, two false alarms
    (da, oka), (db, okb) = _detail(a, df, ev), _detail(b, df, ev)
    ra, ra2, rb = replicates(da["detail"], oka, n=400, seed=7), replicates(da["detail"], oka, n=400, seed=7), replicates(db["detail"], okb, n=400, seed=7)
    assert set(ra) == set(METRICS) and all((ra[k] == ra2[k]).all() for k in METRICS)
    ci = intervals(ra)
    assert ci["recall"][0] <= da["recall"] <= ci["recall"][1] and ci["recall"][0] < ci["recall"][1]
    assert ci["fa_per_day"][0] <= da["fa_per_day"] <= ci["fa_per_day"][1]
    # same model against itself: the paired difference is exactly zero in every replicate
    same = paired_diff(ra, ra2)
    assert all(v["ci95"] == [0.0, 0.0] and not v["excludes_zero"] for v in same.values())
    # b detects a superset of a's events in every resample: paired recall difference is never positive for a - b
    d = paired_diff(ra, rb)
    assert d["recall"]["ci95"][1] <= 0
    assert (ra["recall"] <= rb["recall"]).all()  # paired draws: holds replicate by replicate, not just on average
    # a model whose events all agree gets a zero-width interval (no variation among units, not certainty)
    assert intervals(rb)["recall"] == [1.0, 1.0]
    # edge cases do not raise
    never = replicates(_detail(np.zeros(len(df), int), df, ev)[0]["detail"], np.zeros(4, bool), n=50, seed=1)
    assert (never["f1"] == 0).all() and (never["fa_per_day"] == 0).all()


def test_verdict_rule():
    def reps(f1):
        r = {k: np.full(200, 0.5) for k in METRICS}
        r["f1_event_counted"] = np.asarray(f1, float)
        return r

    def metrics(fa):
        return {"event": {"f1": 0.8, "f1_event_counted": 0.8, "precision": 0.8, "recall": 0.8, "fa_per_day": fa},
                "category_accuracy_event": 0.7}

    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.01, 200)
    base = np.full(200, 0.70) + noise
    assert decide(metrics(0.2), metrics(0.2), reps(base + 0.10), reps(base), 0.5)["outcome"] == "beats"
    assert decide(metrics(0.9), metrics(0.2), reps(base + 0.10), reps(base), 0.5)["outcome"] == "higher_f1_but_above_cap"
    assert decide(metrics(0.2), metrics(0.2), reps(base - 0.10), reps(base), 0.5)["outcome"] == "worse"
    out = decide(metrics(0.2), metrics(0.9), reps(base + rng.normal(0, 0.05, 200)), reps(base), 0.5)
    assert out["outcome"] == "no_detectable_difference" and out["selected_within_cap"] and not out["voting_within_cap"]
    # the verdict reads the event-counted F1, not the segment-based one
    r_sel, r_vote = reps(base), reps(base)
    r_sel["f1"] = base + 0.3
    assert decide(metrics(0.2), metrics(0.2), r_sel, r_vote, 0.5)["outcome"] == "no_detectable_difference"


# ------------------------------------------------------------------ lock and freeze
def test_held_out_sets_are_locked(tmp_path, monkeypatch):
    """Regression test for the 2026-10-10 incident (baseline runner scored test_v2 before the freeze)."""
    from kami.eval import data as kd
    from kami.eval import freeze
    from kami.eval.run_baselines import BASELINE_DATASETS

    assert not set(kd.DATASETS) & set(kd.LOCKED_DATASETS)
    assert not set(BASELINE_DATASETS) & set(kd.LOCKED_DATASETS)
    for name in kd.LOCKED_DATASETS:
        with pytest.raises(TestSplitLocked):  # any log other than the designated one is refused
            with final_evaluation("m", name, tmp_path / "other.json"):
                pass
        assert name in kd.LOCKED_LOGS
    df = pd.DataFrame({"split": ["train", "test"], "x": [1, 2]})
    locked = SplitData(df, "scenarios_v3")
    with pytest.raises(TestSplitLocked):
        locked.test()
    with final_evaluation("m", "scenarios", tmp_path / "v1.json"):  # another dataset's evaluation does not unlock it
        assert len(SplitData(df).test()) == 1
        with pytest.raises(TestSplitLocked):
            locked.test()
    df.attrs["kami_dataset"] = "scenarios_v2"
    assert SplitData(df).dataset == "scenarios_v2"

    # with the designated log, access still needs a frozen configuration that verifies
    designated = tmp_path / "designated.json"
    monkeypatch.setitem(kd.LOCKED_LOGS, "scenarios_v3", designated)

    def no_freeze():
        raise SystemExit("frozen config does not match")
    monkeypatch.setattr(freeze, "verify", no_freeze)
    with pytest.raises(TestSplitLocked):
        with final_evaluation("m", "scenarios_v3", designated):
            pass
    assert not designated.exists()
    with pytest.raises(TestSplitLocked):  # the file cannot even be loaded before the freeze verifies
        kd.load_dataset("scenarios_v3")
    monkeypatch.setattr(freeze, "verify", lambda: {})
    with final_evaluation("m", "scenarios_v3", designated):
        assert len(locked.test()) == 1
    assert is_logged("m", "scenarios_v3", designated) and not is_logged("other", "scenarios_v3", designated)
    with pytest.raises(TestSplitLocked):  # once per model
        with final_evaluation("m", "scenarios_v3", designated):
            pass
    mark_completed("m", "scenarios_v3", designated, rows=1)
    entry = json.loads(designated.read_text(encoding="utf-8"))[0]
    assert entry["count"] == 1 and "utc" in entry and "completed_utc" in entry and entry["rows"] == 1


def test_freeze_verify_detects_changed_files_and_changed_parameters(tmp_path, monkeypatch):
    import hashlib

    from kami.eval import freeze
    from kami.eval.hashing import sha256_file

    f = tmp_path / "a.py"
    f.write_bytes(b"x = 1\n")
    monkeypatch.setattr(freeze, "ROOT", tmp_path)
    monkeypatch.setattr(freeze, "GLOBS", ["*.py"])
    monkeypatch.setattr(freeze, "CONFIG", tmp_path / "frozen.json")
    monkeypatch.setattr(freeze, "_derived", lambda: {"designs": {"F-B": [1, 2]}})
    files = {"a.py": sha256_file(f)}

    def write(**over):
        cfg = {"files_sha256": files, "designs": {"F-B": [1, 2]}, "verdict_rule": freeze.VERDICT_RULE,
               "files_list_sha256": hashlib.sha256("\n".join(f"{k} {v}" for k, v in sorted(files.items())).encode()).hexdigest()}
        cfg.update(over)
        (tmp_path / "frozen.json").write_text(json.dumps(cfg), encoding="utf-8")

    write()
    assert freeze.verify()["designs"] == {"F-B": [1, 2]}
    f.write_bytes(b"x = 1\r\n")  # a checkout with other line endings is not a change
    assert freeze.verify()
    f.write_bytes(b"x = 2\n")
    with pytest.raises(SystemExit):
        freeze.verify()
    f.write_bytes(b"x = 1\n")
    (tmp_path / "new.py").write_bytes(b"")  # a new input file is a change
    with pytest.raises(SystemExit):
        freeze.verify()
    (tmp_path / "new.py").unlink()
    write(designs={"F-B": [9, 9]})  # an edited parameter block no longer matches its source
    with pytest.raises(SystemExit):
        freeze.verify()
    write(verdict_rule={"beats": "always"})
    with pytest.raises(SystemExit):
        freeze.verify()
    write(files_list_sha256="0" * 64)
    with pytest.raises(SystemExit):
        freeze.verify()


def test_hash_normalises_line_endings_for_text_only(tmp_path):
    from kami.eval.hashing import sha256_file

    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_bytes(b"x = 1\ny = 2\n")
    b.write_bytes(b"x = 1\r\ny = 2\r\n")
    assert sha256_file(a) == sha256_file(b)
    c, d = tmp_path / "c.parquet", tmp_path / "d.parquet"
    c.write_bytes(b"x\n")
    d.write_bytes(b"x\r\n")
    assert sha256_file(c) != sha256_file(d)


def test_held_out_dataset_properties():
    from kami.eval.data import RES

    seeds = {"v2": 20261010, "v3": 20261011}
    hashes = {}
    for v, seed in seeds.items():
        info = json.loads((RES / "splits" / f"test_{v}_info.json").read_text(encoding="utf-8"))
        assert info[f"seed_{v}"] == seed and info["same_seed_identical"] and info["no_straddle"]
        assert info["train_val_identical_to_v1"] and info["test_events_differ_from_v1"]
        assert info["v1_identical_events"] == 0
        assert set(info["events_per_type"].values()) == {12}
        hashes[v] = info[f"hash_{v}"]
    assert hashes["v2"] != hashes["v3"]
    v3 = json.loads((RES / "splits" / "test_v3_info.json").read_text(encoding="utf-8"))
    assert v3["v2_identical_events"] == 0 and v3["v2_same_node_type_start"] == 0
    # one v3 event happens to start at the same time on the same node as a v1 event of the same type (chance,
    # about 1 in 100 for a pair of seeds); it is a different event (kind, size, length). Recorded, seed not re-rolled.
    assert v3["v1_same_node_type_start"] <= 1


def test_battledim_frame_is_label_free_and_matches_round1_on_scored_rows():
    """BattLeDIM is not a held-out set (its test split was exposed in Round 1); this only reads probabilities."""
    from kami.eval.data import PROC
    from kami.eval.round2_data import battledim_frame

    f = battledim_frame()
    old = pd.read_parquet(PROC / "evidence_battledim.parquet")
    m = old.p_infra.notna().to_numpy()
    np.testing.assert_allclose(f.p_infra.to_numpy()[m], old.p_infra.to_numpy()[m], atol=1e-12)
    amb = f.ambiguous.to_numpy(bool) & (f.split != "train").to_numpy()
    assert amb.sum() > 0 and f.p_infra[amb].notna().all()  # evidence exists on the label-derived rows as well ...
    assert not fusion_mask(f)[amb].any()  # ... but they are still excluded from scoring
    assert f.p_infra[(f.split == "train").to_numpy()].isna().all()
