"""Evaluation datasets with causal features, split labels and scoring masks (cached to data/processed)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..data.splits import assign_split, load_splits
from ..features.causal import compute_features_by_node, feature_names

ROOT = Path(__file__).resolve().parents[3]
PROC = ROOT / "data" / "processed"
RES = ROOT / "results"
DATASETS = {
    "battledim": ("battledim_network_semi_synthetic.parquet", "battledim.json", ["infra"]),
    "scenarios": ("scenarios_semi_synthetic.parquet", "scenarios.json", ["infra", "quality"]),
}
RAW_SIGNALS = ["flow", "pressure", "turbidity", "tds"]
DOMAIN_SIGNALS = {"infra": ["flow", "pressure"], "quality": ["turbidity", "tds"], "joint": RAW_SIGNALS}


def domain_features(domain: str, available) -> list[str]:
    """Raw signals plus causal feature columns for a domain (only those present in `available`)."""
    sig = DOMAIN_SIGNALS[domain]
    want = list(sig) + feature_names(signals=sig)
    return [c for c in want if c in available]


def load_dataset(name: str, refresh: bool = False) -> pd.DataFrame:
    fname, split_file, _ = DATASETS[name]
    cache = PROC / f"{name}_features.parquet"
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)
    df = pd.read_parquet(PROC / fname).sort_values(["node_id", "ts"]).reset_index(drop=True)
    df = pd.concat([df, compute_features_by_node(df)], axis=1)
    df["split"] = assign_split(df.ts, load_splits(RES / "splits" / split_file)).to_numpy()
    df.to_parquet(cache)
    return df


def scored_mask(df: pd.DataFrame, domain: str) -> pd.Series:
    """Rows usable for fitting and scoring a domain: signals present, not ambiguous, features finite."""
    cols = domain_features(domain, df.columns)
    return df[cols].notna().all(axis=1) & ~df.ambiguous
