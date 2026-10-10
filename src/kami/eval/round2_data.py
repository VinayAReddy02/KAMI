"""Round 2 helpers: evidence + temporal features for arbitrary scenario frames, and event tables."""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd

from ..data.splits import assign_split, load_splits
from ..features.causal import compute_features_by_node
from ..features.temporal import DEFAULT, temporal_features
from .data import PROC, RES, scored_mask

T_COLS = ("suddenness", "persist_steps", "persist_frac", "recurrence")


def featurize(raw: pd.DataFrame, split_file: str = "scenarios.json") -> pd.DataFrame:
    df = raw.sort_values(["node_id", "ts"]).reset_index(drop=True)
    df = pd.concat([df, compute_features_by_node(df)], axis=1)
    df["split"] = assign_split(df.ts, load_splits(RES / "splits" / split_file)).to_numpy()
    return df


def load_modules() -> dict:
    return {d: joblib.load(PROC / "models" / f"evidence_scenarios_{d}.joblib") for d in ("infra", "quality")}


def attach_evidence(df: pd.DataFrame, split: str, modules: dict | None = None) -> pd.DataFrame:
    """Rows of `split` with p_infra, p_quality (final calibrators) and causal temporal features of each stream.
    Unscored rows get p = NaN (treated as no evidence by the temporal features)."""
    modules = modules or load_modules()
    sub = df[df.split == split].copy()
    for d, m in modules.items():
        mask = scored_mask(df, d).loc[sub.index].to_numpy()
        p = np.full(len(sub), np.nan)
        if mask.any():
            p[mask] = m["module"].predict_proba_array(sub.loc[mask, m["columns"]].to_numpy(float))
        sub[f"p_{d}"] = p
    parts = []
    for _, g in sub.groupby("node_id", sort=False):
        g = g.sort_values("ts")
        for d in ("infra", "quality"):
            t = temporal_features(g[f"p_{d}"].to_numpy(), DEFAULT, prefix=f"{d}_")
            t.index = g.index
            g = pd.concat([g, t], axis=1)
        parts.append(g)
    out = pd.concat(parts).sort_index()
    out["y"] = out.infra_flag.astype(int) + 2 * out.quality_flag.astype(int)
    out["any_flag"] = out.infra_flag | out.quality_flag
    return out


def any_events_from_frame(df: pd.DataFrame) -> pd.DataFrame:
    e = df[df.any_flag & (df.event_id != "")]
    g = e.groupby(["node_id", "event_id"]).agg(type=("event_type", "first"), start=("ts", "min"), end=("ts", "max"))
    return g.reset_index()


def battledim_frame() -> pd.DataFrame:
    """BattLeDIM frame for Round 2: features, split, p_infra and its temporal features, p_quality = 0.

    Round 1 stored p_infra = NaN on `ambiguous` rows (the 24 h after each labelled leak window, a label-derived mask) and
    computed the temporal features with those rows counted as "no evidence". The temporal features of later rows then
    depended on where the true leak windows ended. Here the probability is predicted on EVERY row with valid features
    (no label involved), so the temporal features are label-free; `ambiguous` is applied only when scoring
    (fusion_tune.fusion_mask). On the rows Round 1 scored, p_infra is identical to Round 1 (tested): validation rows use
    calibrators cross-fitted over the same four time blocks and fitted on the same scored rows, test rows use the final
    calibrator. Train rows stay NaN (in-sample for the evidence model).
    """
    from sklearn.isotonic import IsotonicRegression

    from ..models.evidence import N_BLOCKS
    from .data import load_dataset

    full = load_dataset("battledim").copy()
    m = joblib.load(PROC / "models" / "evidence_battledim_infra.joblib")
    mod, cols = m["module"], m["columns"]
    fv = full[cols].notna().all(axis=1).to_numpy()
    scored = fv & ~full.ambiguous.to_numpy(bool)
    raw = np.full(len(full), np.nan)
    raw[fv] = mod.raw(full[fv])
    p = np.full(len(full), np.nan)
    y = full.infra_flag.to_numpy(float)
    ts = full.ts.astype("int64").to_numpy()
    is_val, is_test = (full.split == "val").to_numpy(), (full.split == "test").to_numpy()
    vs = is_val & scored
    edges = np.quantile(ts[vs], np.linspace(0, 1, N_BLOCKS + 1)[1:-1])  # same block edges as evidence.time_blocks
    block = np.searchsorted(edges, ts, side="right")
    for b in range(N_BLOCKS):
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw[vs & (block != b)], y[vs & (block != b)])
        te = is_val & fv & (block == b)
        p[te] = iso.predict(raw[te])
    p[is_test & fv] = mod.calibrator.predict(raw[is_test & fv])
    full["p_infra"] = p
    full["p_quality"] = np.where(np.isnan(p), np.nan, 0.0)
    parts = []
    for _, g in full.groupby("node_id", sort=False):
        g = g.sort_values("ts")
        t = temporal_features(g["p_infra"].to_numpy(), DEFAULT, prefix="infra_")
        t.index = g.index
        parts.append(pd.concat([g, t], axis=1))
    out = pd.concat(parts).sort_index()
    for c in T_COLS:
        out[f"quality_{c}"] = 0.0
    out["y"] = out.infra_flag.astype(int) + 2 * out.quality_flag.astype(int)
    out["any_flag"] = out.infra_flag | out.quality_flag
    return out
