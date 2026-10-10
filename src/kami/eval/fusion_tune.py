"""Round 2: decision rules for the fusion designs and their constrained tuning on VALIDATION ONLY.

Objective (user decision): maximise event F1 (any alert vs any event) subject to false alarms per day <= CAP.
If no setting satisfies the cap, the lowest-false-alarm setting is taken (and reported as infeasible).
Tuning is out-of-fold over the contiguous validation time blocks used in Round 1: for each block, parameters are
chosen on the other blocks and applied to the held-out block; the concatenated out-of-fold predictions give the
reported validation numbers. The frozen parameters are chosen on the whole validation split.
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from ..models.evidence import N_BLOCKS, time_blocks
from ..models.fusion import FusionA, reliability
from .fast_eval import AnyEvaluator

CAP = 0.5
TIE = 0.005
G9 = [round(float(x), 2) for x in np.arange(0.1, 0.95, 0.1)] + [0.95, 0.98]  # coarse grid incl. the strict end
G19 = [round(float(x), 2) for x in np.arange(0.05, 0.96, 0.05)] + [0.98]


def fusion_mask(df: pd.DataFrame) -> np.ndarray:
    return (df.p_infra.notna() & df.p_quality.notna()).to_numpy()


def _key(m: dict):
    if m["fa_per_day"] <= CAP:
        return (1, m["f1"], -m["fa_per_day"])
    return (0, -m["fa_per_day"], m["f1"])


class Design:
    name = ""
    temporal = False
    interpretability = 0  # higher = more interpretable (used only to break ties)

    def fit(self, df, y):
        return self

    def grid(self) -> list[tuple]:
        raise NotImplementedError

    def _decide_ok(self, df, params) -> np.ndarray:
        raise NotImplementedError

    def decide(self, df: pd.DataFrame, params: tuple) -> np.ndarray:
        """Category index per row (0 N, 1 I, 2 Q, 3 C); rows without evidence are Normal."""
        out = np.zeros(len(df), int)
        ok = fusion_mask(df)
        if ok.any():
            out[ok] = self._decide_ok(df[ok], params)
        return out


class VotingDesign(Design):
    name = "threshold voting (no fusion)"
    interpretability = 3

    def grid(self):
        return list(itertools.product(G19, G19))

    def _decide_ok(self, df, params):
        ti, tq = params
        return (df.p_infra.to_numpy() >= ti).astype(int) + 2 * (df.p_quality.to_numpy() >= tq).astype(int)


class FusionBDesign(Design):
    """Dempster-Shafer discounting: stream active when reliability * p >= gamma_stream (see models/fusion.py)."""

    def __init__(self, temporal: bool):
        self.temporal = temporal
        self.name = "F-B" if temporal else "F-B (no temporal)"
        self.interpretability = 2

    def grid(self):
        gs = list(itertools.product(G9, G9))
        if not self.temporal:
            return [(1.0, 1.0, 0.0, gi, gq) for gi, gq in gs]
        return [(rm, tp, lam, gi, gq) for rm in (0.4, 0.7) for tp in (6, 24) for lam in (0.0, 0.3) for gi, gq in gs]

    def _decide_ok(self, df, params):
        rm, tp, lam, gi, gq = params
        if self.temporal:
            ri = reliability(df["infra_persist_steps"], df["infra_recurrence"], rm, tp, lam)
            rq = reliability(df["quality_persist_steps"], df["quality_recurrence"], rm, tp, lam)
        else:
            ri = rq = 1.0
        return ((ri * df.p_infra.to_numpy() >= gi).astype(int) + 2 * (rq * df.p_quality.to_numpy() >= gq).astype(int))


class FusionADesign(Design):
    """Multinomial log-odds model (class-balanced); a component is active when its posterior >= its threshold."""

    def __init__(self, temporal: bool):
        self.temporal = temporal
        self.name = "F-A" if temporal else "F-A (no temporal)"
        self.interpretability = 1
        self.model: FusionA | None = None

    def fit(self, df, y):
        ok = fusion_mask(df)
        self.model = FusionA(self.temporal).fit(df[ok], np.asarray(y)[ok])
        return self

    def grid(self):
        return list(itertools.product(G9, G9))

    def _decide_ok(self, df, params):
        ti, tq = params
        pr = self.model.predict_proba(df)
        return ((pr[:, 1] + pr[:, 3] >= ti).astype(int) + 2 * (pr[:, 2] + pr[:, 3] >= tq).astype(int))


def all_designs() -> list[Design]:
    return [FusionADesign(True), FusionBDesign(True), FusionADesign(False), FusionBDesign(False), VotingDesign()]


def best_params(design: Design, df: pd.DataFrame, events: pd.DataFrame) -> tuple[tuple, dict]:
    ev = AnyEvaluator(df, events, fusion_mask(df))
    best = None
    for params in design.grid():
        m = ev(design.decide(df, params))
        if best is None or _key(m) > _key(best[1]):
            best = (params, m)
    return best


def oof_tune(design: Design, val: pd.DataFrame, events: pd.DataFrame) -> dict:
    """Out-of-fold tuning on validation. `val` must carry y, any_flag, p_* and temporal columns."""
    val = val.reset_index(drop=True)
    blocks = time_blocks(val.ts, N_BLOCKS)
    y = val.y.to_numpy()
    oof = np.zeros(len(val), int)
    fold_params = []
    for b in range(N_BLOCKS):
        tr, te = blocks != b, blocks == b
        d_tr = val[tr].reset_index(drop=True)
        design.fit(d_tr, y[tr])
        params, _ = best_params(design, d_tr, events)
        fold_params.append(params)
        oof[te] = design.decide(val[te].reset_index(drop=True), params)
    ev = AnyEvaluator(val, events, fusion_mask(val))
    oof_metrics = ev(oof)
    design.fit(val, y)
    final_params, in_sample = best_params(design, val, events)
    return {"oof_pred": oof, "oof": oof_metrics, "fold_params": fold_params, "final_params": final_params,
            "in_sample": in_sample, "feasible": bool(oof_metrics["fa_per_day"] <= CAP)}


def select(results: dict[str, dict], candidates: tuple[str, ...] = ("F-A", "F-B")) -> tuple[str, str]:
    """Best constrained OOF validation event F1; ties within TIE go to the more interpretable design."""
    ranked = sorted(candidates, key=lambda n: _key(results[n]["oof"]), reverse=True)
    best = ranked[0]
    interp = {"F-A": 1, "F-B": 2}
    reason = "best constrained validation event F1"
    for other in ranked[1:]:
        a, b = results[best]["oof"], results[other]["oof"]
        feasible_both = a["fa_per_day"] <= CAP and b["fa_per_day"] <= CAP
        if feasible_both and abs(a["f1"] - b["f1"]) <= TIE and interp[other] > interp[best]:
            best, reason = other, f"tie within {TIE}: more interpretable design"
    return best, reason
