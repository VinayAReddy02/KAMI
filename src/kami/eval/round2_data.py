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
