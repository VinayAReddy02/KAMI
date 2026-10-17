"""GECCO loader (Round 7, G2): signal mapping, 5-minute resampling, events, chronology, causal features and the test-label
lock. Uses small generated files in a temporary folder, never the real GECCO labels."""
import numpy as np
import pandas as pd
import pytest

from kami.eval.access import TestSplitLocked, final_evaluation
from kami.gecco import data as G


def write_files(root, days=(2, 1, 1), events=None):
    """Three consecutive minute files in the GECCO layout; `events` = {split: [(first minute, last minute), ...]}."""
    start = pd.Timestamp("2017-07-01")
    out = {}
    for split, n_days in zip(("train", "val", "test"), days):
        t = pd.date_range(start, periods=n_days * 1440, freq="1min")
        start = t[-1] + pd.Timedelta("1min")
        i = np.arange(len(t))
        df = pd.DataFrame({"Unnamed: 0": i, "Time": t.strftime("%Y-%m-%d %H:%M:%S"), "Tp": 8.0, "pH": 8.5, "Cond": 0.0211,
                           "Turb": 0.128 + 0.001 * (i % 7), "SAC": 4.1, "PFM": 70.0, "Event": False})
        for a, b in (events or {}).get(split, []):
            df.loc[a:b, "Event"] = True
        df.to_csv(root / G.FILES[split], index=False)
        out[split] = df
    return out


def test_signal_mapping_and_dropouts():
    raw = pd.DataFrame({"Time": ["2017-07-01 00:00:00", "2017-07-01 00:01:00"], "Tp": [8.0, 0.0], "pH": [8.5, 0.0],
                        "Cond": [0.0211, 0.0], "Turb": [0.128, 0.0], "SAC": [4.1, 0.0], "Event": [False, True]})
    m = G.map_signals(raw)
    assert m.turbidity[0] == pytest.approx(0.128) and m.tds[0] == pytest.approx(0.0211 * 10_000 * 0.64)  # 135.04 mg/L
    assert np.isnan(m.turbidity[1]) and np.isnan(m.tds[1]) and bool(m.event[1])  # dropout: values missing, label kept


def test_five_minute_median_and_any_minute_event():
    t = pd.date_range("2017-07-01 00:00", periods=10, freq="1min")
    m = pd.DataFrame({"ts": t, "turbidity": [1, 2, 3, 100, 5, 1, 1, 1, 1, np.nan], "tds": 100.0,
                      "event": [False] * 4 + [True] + [False] * 5})
    s = G.resample(m)
    assert list(s.ts) == [pd.Timestamp("2017-07-01 00:00"), pd.Timestamp("2017-07-01 00:05")]  # clock aligned, labelled by start
    assert s.turbidity.tolist() == [3.0, 1.0] and s.quality_flag.tolist() == [True, False]  # median ignores the spike and NaN


def test_events_are_runs_of_event_steps():
    s = pd.DataFrame({"quality_flag": [False, True, True, False, True, False]})
    e = G.label_events(s, "val")
    assert e.event_id.tolist() == ["", "gecco-val-001", "gecco-val-001", "", "gecco-val-002", ""]
    assert set(e.event_type) == {"", G.EVENT_TYPE}


def test_frame_is_chronological_real_and_hides_test_labels(tmp_path):
    files = write_files(tmp_path, events={"train": [(600, 640)], "val": [(100, 104)], "test": [(50, 60)]})
    df = G.build_frame(tmp_path)
    assert df.ts.is_monotonic_increasing and list(dict.fromkeys(df.split)) == ["train", "val", "test"]
    assert (df.data_kind == "real").all() and (df.node_id == "gecco").all() and not df.infra_flag.any()
    assert df.loc[df.split == "test", "quality_flag"].isna().all() and (df.loc[df.split == "test", "event_id"] == "").all()
    assert df.loc[df.split == "train", "event_id"].nunique() == 2 and df.loc[df.split == "val", "quality_flag"].astype(bool).sum() == 1
    assert {"turbidity_dv288", "tds_m12", "turbidity", "tds"} <= set(df.columns)
    with pytest.raises(TestSplitLocked):
        G.attach_test_labels(df, tmp_path)
    with pytest.raises(TestSplitLocked):
        G.read_minutes("test", tmp_path, labels=True)
    assert "Event" in files["test"]  # the label is in the file; only the loader hides it


def test_test_labels_only_inside_the_guarded_access(tmp_path):
    write_files(tmp_path, events={"test": [(50, 60)]})
    df = G.build_frame(tmp_path)
    log = tmp_path / "log.json"
    with final_evaluation("unit-test-model", G.DATASET, log_path=log):
        full = G.attach_test_labels(df, tmp_path)
    test = full[full.split == "test"]
    assert test.quality_flag.astype(bool).sum() == 3 and test.event_id.nunique() == 2  # minutes 50-60 = steps 10, 11, 12
    with pytest.raises(TestSplitLocked):  # a second read of the same model is refused
        with final_evaluation("unit-test-model", G.DATASET, log_path=log):
            pass


def test_features_are_causal(tmp_path):
    write_files(tmp_path)
    a = G.build_frame(tmp_path)
    p = tmp_path / G.FILES["test"]
    raw = pd.read_csv(p)
    raw.loc[len(raw) // 2:, "Turb"] = 5.0  # change only the second half of the last file
    raw.to_csv(p, index=False)
    b = G.build_frame(tmp_path)
    cut = a.index[(a.split == "test")][len(a[a.split == "test"]) // 2 - 1]
    cols = [c for c in a.columns if c.startswith(("turbidity", "tds"))]
    pd.testing.assert_frame_equal(a.loc[:cut, cols], b.loc[:cut, cols])
