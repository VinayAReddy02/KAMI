import numpy as np
import pandas as pd
import pytest

from kami.data.loaders import COLUMNS, build_battledim_network, build_scenario_background
from kami.data.splits import assign_split, check_no_straddle, make_splits
from kami.features.causal import compute_features, feature_names, signal_features
from kami.simulator.scenarios import EVENT_TYPES, frame_hash, generate_scenarios


def _series(n=900, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    return pd.DataFrame({
        "flow": 50 + 10 * np.sin(t / 40) + rng.normal(0, 1, n),
        "pressure": 45 + rng.normal(0, 0.3, n),
        "turbidity": np.abs(rng.normal(3, 1, n)),
        "tds": 200 + rng.normal(0, 5, n),
    })


def test_no_lookahead_property():
    df = _series()
    base = compute_features(df)
    for cut in (400, 650):
        pert = df.copy()
        pert.iloc[cut + 1:] = pert.iloc[cut + 1:] * 7 + 100  # wildly change the future
        got = compute_features(pert)
        pd.testing.assert_frame_equal(base.iloc[: cut + 1], got.iloc[: cut + 1])
    assert not base.iloc[-1].isna().any()
    assert list(base.columns) == feature_names()


def test_known_feature_values():
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 7.0])
    f = signal_features(x, "s", windows=(3,))
    assert f["s_m3"].iloc[-1] == pytest.approx((4 + 5 + 7) / 3)
    assert f["s_roc3"].iloc[-1] == pytest.approx((7 - 3) / 3)  # x_t=7, x_{t-3}=3
    assert f["s_sl3"].iloc[-1] == pytest.approx(np.polyfit([0, 1, 2], [4, 5, 7], 1)[0])
    assert f["s_diff1"].iloc[-1] == 2.0
    assert np.isnan(f["s_m3"].iloc[1])  # not enough history yet


def test_slope_matches_polyfit():
    x = _series(400)["pressure"]
    f = signal_features(x, "p", windows=(72,))
    i = 300
    assert f["p_sl72"].iloc[i] == pytest.approx(np.polyfit(np.arange(72), x.iloc[i - 71:i + 1], 1)[0], abs=1e-9)


@pytest.fixture(scope="module")
def built():
    bd, ev, _ = build_battledim_network()
    bg, _ = build_scenario_background()
    return bd, ev, bg


def test_schema_and_flags(built):
    bd, ev, bg = built
    assert list(bd.columns) == COLUMNS and list(bg.columns) == COLUMNS
    assert bd.semi_synthetic.all() and bg.semi_synthetic.all()
    assert bd.infra_flag.any() and not bd.quality_flag.any()
    assert (bd.source == "battledim_simulated").all()


def test_splits_chronological_and_no_straddle(built):
    bd, ev, bg = built
    spans = ev[["event_id", "start", "end"]]
    sp = make_splits(bd, spans=spans)
    assert sp["start"] < sp["train_end"] < sp["val_end"] < sp["end"]
    assert check_no_straddle(bd, sp, spans)
    s = assign_split(bd.ts, sp)
    assert bd.ts[s == "train"].max() < bd.ts[s == "val"].min() <= bd.ts[s == "val"].max() < bd.ts[s == "test"].min()
    assert set(s) == {"train", "val", "test"}


def test_scenarios_deterministic_and_counts(built):
    _, _, bg = built
    sp = make_splits(bg)
    a, ea = generate_scenarios(bg, sp, seed=7, per_type=2)
    b, eb = generate_scenarios(bg, sp, seed=7, per_type=2)
    c, _ = generate_scenarios(bg, sp, seed=8, per_type=2)
    assert frame_hash(a) == frame_hash(b) != frame_hash(c)
    counts = ea.groupby(["split", "type"]).size()
    assert (counts == 2 * 3).all() and set(ea.type) == set(EVENT_TYPES)  # 3 nodes x 2 per type
    assert a.semi_synthetic.all() and (a.source == "scenario_semi_synthetic").all()
    assert check_no_straddle(a, sp)
    comb = a[a.event_type == "combined"]
    assert comb.infra_flag.any() and comb.quality_flag.any()
    q = a[a.event_type == "quality_turbidity_surge"]
    assert q.quality_flag.any() and not q.infra_flag.any()
    # events only change data inside their window
    assert (a.loc[a.event_id == "", "flow"].dropna() == bg.loc[a.event_id == "", "flow"].dropna()).all()
