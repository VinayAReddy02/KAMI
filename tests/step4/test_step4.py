import json

import numpy as np
import pytest

from kami.features.temporal import TemporalParams, temporal_features
from kami.models.evidence import reliability, time_blocks

P = TemporalParams(theta=0.5, k=2, window=4, frac_window=4, gap=3, rec_window=10)
SERIES = [0, 0, 0.8, 0.9, 0.2, 0.1, 0, 0, 0.6, 0.7]


def test_temporal_hand_computed():
    t = temporal_features(SERIES, P)
    np.testing.assert_allclose(t.suddenness, [0, 0, .8, .9, .9, .9, .9, 0, .6, .7], atol=1e-12)
    np.testing.assert_allclose(t.persist_steps, [0, 0, 1, 2, 0, 0, 0, 0, 1, 2])
    np.testing.assert_allclose(t.persist_frac, [0, 0, 1 / 3, .5, .5, .5, .25, 0, .25, .5], atol=1e-12)
    np.testing.assert_allclose(t.recurrence, [0, 0, 1, 1, 1, 1, 1, 1, 2, 2])


def test_recurrence_gap_rule():
    b = [1, 0, 0, 1]
    assert temporal_features(b, TemporalParams(gap=2, rec_window=10)).recurrence.iloc[-1] == 2
    assert temporal_features(b, TemporalParams(gap=3, rec_window=10)).recurrence.iloc[-1] == 1


def test_recurrence_window_forgets_old_episodes():
    p = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert temporal_features(p, TemporalParams(gap=2, rec_window=5)).recurrence.iloc[-1] == 0


def test_temporal_is_causal_and_missing_is_no_evidence():
    base = temporal_features(SERIES, P)
    changed = temporal_features(SERIES[:6] + [1, 1, 1, 1], P)
    np.testing.assert_allclose(base.iloc[:6].to_numpy(), changed.iloc[:6].to_numpy())
    t = temporal_features([0.9, np.nan, 0.9], P)
    assert t.persist_steps.tolist() == [1, 0, 1]


def test_reliability_bins_and_blocks():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.05, 0.15, 0.85, 0.95])
    r = reliability(y, p, bins=10)
    assert [b["bin"] for b in r] == [0, 1, 8, 9] and r[3]["frac_pos"] == 1.0
    import pandas as pd

    ids = time_blocks(pd.Series(pd.date_range("2020", periods=100, freq="h")), 4)
    assert set(ids) == {0, 1, 2, 3} and (np.diff(ids) >= 0).all()


def test_evidence_results_exist_and_calibrated():
    from kami.eval.data import RES

    files = sorted((RES / "evidence").glob("*__*.json"))
    assert len(files) == 3
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        assert 0 <= d["val"]["brier"] <= 1 and 0 <= d["test"]["brier"] <= 1
        assert d["reliability_val"] and d["reliability_test"]
