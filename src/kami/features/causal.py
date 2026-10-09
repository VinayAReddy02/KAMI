"""Causal (past-only) features. Every window ends at the current row, so the feature at t never
depends on observations after t. Windows are in steps (5 min each) and recorded in WINDOWS.

For each signal s and window w:
  m{w}   rolling mean of the last w values
  sd{w}  rolling std of the last w values
  roc{w} rate of change (x_t - x_{t-w}) / w
  sl{w}  least-squares slope over the last w values (units per step)
  dv{w}  deviation from the rolling baseline, (x_t - m{w}) / (sd{w} + eps)
Plus diff1 (x_t - x_{t-1}) and lag24h deviation d24 = x_t - x_{t-288} (same time yesterday).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SIGNALS = ["flow", "pressure", "turbidity", "tds"]
WINDOWS = (12, 72, 288)  # 1 h, 6 h, 24 h at 5-minute steps
DAY = 288
EPS = 1e-9


def _slope(x: pd.Series, w: int) -> pd.Series:
    """Rolling OLS slope against time index, using only the last w values."""
    i = pd.Series(np.arange(len(x), dtype=float), index=x.index)
    s1 = x.rolling(w, min_periods=w).sum()
    s2 = (i * x).rolling(w, min_periods=w).sum()
    sum_i = w * i - w * (w - 1) / 2.0
    sum_i2 = w * i**2 - i * w * (w - 1) + (w - 1) * w * (2 * w - 1) / 6.0
    return (w * s2 - sum_i * s1) / (w * sum_i2 - sum_i**2)


def signal_features(x: pd.Series, name: str, windows=WINDOWS) -> pd.DataFrame:
    out = {}
    out[f"{name}_diff1"] = x.diff()
    out[f"{name}_d24"] = x - x.shift(DAY)
    for w in windows:
        m = x.rolling(w, min_periods=w).mean()
        sd = x.rolling(w, min_periods=w).std()
        out[f"{name}_m{w}"] = m
        out[f"{name}_sd{w}"] = sd
        out[f"{name}_roc{w}"] = (x - x.shift(w)) / w
        out[f"{name}_sl{w}"] = _slope(x, w)
        out[f"{name}_dv{w}"] = (x - m) / (sd + EPS)
    return pd.DataFrame(out, index=x.index)


def compute_features(df: pd.DataFrame, signals=SIGNALS, windows=WINDOWS) -> pd.DataFrame:
    """Features for ONE node's time-ordered frame (columns = signals). Signals that are entirely NaN
    are skipped. Rows keep the input index."""
    parts = []
    for s in signals:
        if s in df and df[s].notna().any():
            parts.append(signal_features(df[s].astype(float), s, windows))
    return pd.concat(parts, axis=1)


def compute_features_by_node(df: pd.DataFrame, signals=SIGNALS, windows=WINDOWS) -> pd.DataFrame:
    """Apply per node (input must be sorted by ts within node). Returns frame aligned with df.index."""
    outs = []
    for _, g in df.groupby("node_id", sort=False):
        outs.append(compute_features(g.sort_values("ts"), signals, windows))
    return pd.concat(outs).reindex(df.index)


def feature_names(signals=SIGNALS, windows=WINDOWS) -> list[str]:
    cols = []
    for s in signals:
        cols += [f"{s}_diff1", f"{s}_d24"]
        for w in windows:
            cols += [f"{s}_{k}{w}" for k in ("m", "sd", "roc", "sl", "dv")]
    return cols


def compute_last(history: dict[str, np.ndarray], windows=WINDOWS) -> dict[str, float]:
    """Features of the LAST step only, computed with plain numpy from the tail of each signal.

    Must equal `compute_features(...)` at the last row (tested). `history[s]` holds the most recent values of
    signal s (oldest first) and needs at least DAY + 1 entries for the 24 h lag feature. Used by the live
    pipeline because it is much cheaper than recomputing rolling windows with pandas on every message.
    """
    out: dict[str, float] = {}
    for s, x in history.items():
        x = np.asarray(x, float)
        n = len(x)
        out[f"{s}_diff1"] = x[-1] - x[-2] if n >= 2 else np.nan
        out[f"{s}_d24"] = x[-1] - x[-1 - DAY] if n > DAY else np.nan
        for w in windows:
            if n < w or np.isnan(x[-w:]).any():
                for k in ("m", "sd", "roc", "sl", "dv"):
                    out[f"{s}_{k}{w}"] = np.nan
                continue
            seg = x[-w:]
            m = seg.mean()
            sd = seg.std(ddof=1)
            t = np.arange(w) - (w - 1) / 2.0
            out[f"{s}_m{w}"] = m
            out[f"{s}_sd{w}"] = sd
            out[f"{s}_roc{w}"] = (x[-1] - x[-1 - w]) / w if n > w else np.nan
            out[f"{s}_sl{w}"] = float(t @ seg / (t @ t))
            out[f"{s}_dv{w}"] = (x[-1] - m) / (sd + EPS)
    return out
