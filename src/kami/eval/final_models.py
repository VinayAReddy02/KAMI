"""Round 2: rebuild every model of the ablation table from the FROZEN configuration (no tuning happens here).

Each model is a function `predict(df) -> int category per row (0 N, 1 I, 2 Q, 3 C)` for frames that carry the
causal features and (for fusion/voting) the evidence columns from `round2_data.attach_evidence`.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from ..models.baselines import FixedThreshold, IsoForest, OCSVMDetector
from .data import DOMAIN_SIGNALS, RES, domain_features, load_dataset, scored_mask
from .fusion_tune import FusionADesign, FusionBDesign, VotingDesign

DESIGNS = {"F-A": lambda: FusionADesign(True), "F-B": lambda: FusionBDesign(True),
           "F-A (no temporal)": lambda: FusionADesign(False), "F-B (no temporal)": lambda: FusionBDesign(False),
           "threshold voting (no fusion)": lambda: VotingDesign()}
BASELINES = ("fixed_threshold", "isolation_forest", "ocsvm")


def fusion_models(frozen: dict, val_frame: pd.DataFrame) -> dict:
    """Fusion designs and voting with their frozen parameters. F-A's regression is fitted on the validation frame
    (the same rows and procedure as in R2)."""
    val = val_frame.reset_index(drop=True)
    out = {}
    for name, mk in DESIGNS.items():
        d = mk()
        d.fit(val, val.y.to_numpy())
        params = tuple(frozen["designs"][name]["final_params"])
        out[name] = (lambda df, d=d, p=params: d.decide(df, p))
    return out


def baseline_models(dataset: str, full: pd.DataFrame, domains: list[str]) -> dict:
    """Refit the three baselines with their tuned parameters (results/baselines/*.json) on the training rows."""
    train = full[full.split == "train"]
    out = {}
    for model in BASELINES:
        dets = {}
        for d in domains:
            params = json.loads((RES / "baselines" / f"{dataset}__{d}__{model}.json").read_text(encoding="utf-8"))["params"]
            m_tr = scored_mask(full, d).loc[train.index].to_numpy()
            if model == "fixed_threshold":
                dets[d] = FixedThreshold(DOMAIN_SIGNALS[d], params["k"]).fit(train[m_tr])
            elif model == "isolation_forest":
                tr = train[m_tr]
                if len(tr) > 150_000:
                    tr = tr.sample(150_000, random_state=0).sort_index()
                dets[d] = IsoForest(domain_features(d, full.columns), params["n_estimators"], params["max_samples"],
                                    params["quantile"]).fit(tr)
            else:
                normal = train[m_tr & ~train[f"{d}_flag"].to_numpy(bool)]
                dets[d] = OCSVMDetector(domain_features(d, full.columns), params["nu"], params["gamma_mult"],
                                        params["quantile"]).fit(normal)

        def predict(df, dets=dets):
            a_i = dets["infra"].predict(df)
            a_q = dets["quality"].predict(df) if "quality" in dets else np.zeros(len(df), bool)
            return a_i.astype(int) + 2 * a_q.astype(int)
        out[f"baseline: {model}"] = predict
    return out


def joint_model(full: pd.DataFrame, dataset: str):
    """Single multi-class gradient-boosting model on all raw signals and features (no separated evidence)."""
    train = full[full.split == "train"]
    d = "infra" if dataset == "battledim" else "joint"
    cols = domain_features(d, full.columns)
    y = train.infra_flag.astype(int) + 2 * train.quality_flag.astype(int)
    m = scored_mask(full, d).loc[train.index].to_numpy()
    tr, ytr = train[m], y[m]
    if len(tr) > 250_000:
        idx = tr.sample(250_000, random_state=0).sort_index().index
        ytr, tr = ytr.loc[idx], tr.loc[idx]
    clf = HistGradientBoostingClassifier(max_depth=6, max_iter=150, random_state=0, class_weight="balanced")
    clf.fit(tr[cols].to_numpy(float), ytr.to_numpy())

    def predict(df):
        X = df[cols].to_numpy(float)
        out = np.zeros(len(df), int)
        ok = np.isfinite(X).all(axis=1)
        if ok.any():
            out[ok] = clf.predict(X[ok])
        return out
    return predict


def scenario_models(frozen: dict, val_frame: pd.DataFrame) -> dict:
    full = load_dataset("scenarios")  # train rows identical to scenarios_v2
    models = fusion_models(frozen, val_frame)
    models["single joint model (no separated evidence)"] = joint_model(full, "scenarios")
    models.update(baseline_models("scenarios", full, ["infra", "quality"]))
    return models
