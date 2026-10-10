"""Evaluation datasets with causal features, split labels and scoring masks (cached to data/processed)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..data.splits import assign_split, load_splits
from ..features.causal import compute_features_by_node, feature_names

ROOT = Path(__file__).resolve().parents[3]
PROC = ROOT / "data" / "processed"
RES = ROOT / "results"
# Datasets that generic runners (baselines, evidence, Round-1 fusion) may loop over. Their test splits are EXPOSED.
DATASETS = {
    "battledim": ("battledim_network_semi_synthetic.parquet", "battledim.json", ["infra"]),
    "scenarios": ("scenarios_semi_synthetic.parquet", "scenarios.json", ["infra", "quality"]),  # test = test_v1
}
# Round 2 held-out sets: same train/validation rows as "scenarios", fresh events in the test period.
# They are deliberately NOT in DATASETS: on 2026-10-10 the baseline runner looped over DATASETS and scored
# test_v2 before the freeze (see results/round2/incident_test_v2 and docs/decisions.md). The test split of a
# locked set can only be opened by `final_evaluation` with its designated log, after the frozen config verifies.
LOCKED_DATASETS = {
    "scenarios_v2": ("scenarios_v2_semi_synthetic.parquet", "scenarios.json", ["infra", "quality"]),
    "scenarios_v3": ("scenarios_v3_semi_synthetic.parquet", "scenarios.json", ["infra", "quality"]),
}
LOCKED_LOGS = {
    "scenarios_v2": RES / "round2" / "test_v2_eval_log.json",
    "scenarios_v3": RES / "round2" / "test_v3_eval_log.json",
}
RAW_SIGNALS = ["flow", "pressure", "turbidity", "tds"]
DOMAIN_SIGNALS = {"infra": ["flow", "pressure"], "quality": ["turbidity", "tds"], "joint": RAW_SIGNALS}


def domain_features(domain: str, available) -> list[str]:
    """Raw signals plus causal feature columns for a domain (only those present in `available`)."""
    sig = DOMAIN_SIGNALS[domain]
    want = list(sig) + feature_names(signals=sig)
    return [c for c in want if c in available]


def load_dataset(name: str, refresh: bool = False) -> pd.DataFrame:
    fname, split_file, _ = {**DATASETS, **LOCKED_DATASETS}[name]
    cache = PROC / f"{name}_features.parquet"
    if cache.exists() and not refresh:
        df = pd.read_parquet(cache)
    else:
        df = pd.read_parquet(PROC / fname).sort_values(["node_id", "ts"]).reset_index(drop=True)
        df = pd.concat([df, compute_features_by_node(df)], axis=1)
        df["split"] = assign_split(df.ts, load_splits(RES / "splits" / split_file)).to_numpy()
        df.to_parquet(cache)
    df.attrs["kami_dataset"] = name  # lets SplitData enforce the per-dataset lock
    return df


def scored_mask(df: pd.DataFrame, domain: str) -> pd.Series:
    """Rows usable for fitting and scoring a domain: signals present, not ambiguous, features finite."""
    cols = domain_features(domain, df.columns)
    return df[cols].notna().all(axis=1) & ~df.ambiguous
