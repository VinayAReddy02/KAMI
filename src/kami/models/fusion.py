"""Staged contextual fusion of the two calibrated evidence streams.

Input per row: p_infra, p_quality and the causal temporal features of each stream
(`infra_suddenness`, `infra_persist_steps`, `infra_persist_frac`, `infra_recurrence`, same for `quality_`).

F-A  multinomial log-odds model: category log-odds are a linear combination of logit(p_infra), logit(p_quality)
     and temporal modifiers (log1p persistence, persistence fraction, suddenness, log1p recurrence).
F-B  Dempster-Shafer: each stream gives a mass function over the category frame {N,I,Q,C}; its reliability is
     discounted by temporal context (short transients are less reliable, recurring episodes more); combined with
     Dempster's rule and read out with the pignistic transform.
Outputs (see `assess`): category, priority, confidence, explanation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

CATS = ["Normal", "Infrastructure", "Quality", "Combined"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
STREAMS = ("infra", "quality")
TEMP = ("suddenness", "persist_steps", "persist_frac", "recurrence")
EPS = 1e-4


def logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def stream_cols(s: str) -> list[str]:
    return [f"{s}_{t}" for t in TEMP]


def design_matrix(df: pd.DataFrame, streams=STREAMS, temporal: bool = True) -> np.ndarray:
    cols = []
    for s in streams:
        cols.append(logit(df[f"p_{s}"].to_numpy()))
        if temporal:
            cols += [np.log1p(df[f"{s}_persist_steps"].to_numpy(float)), df[f"{s}_persist_frac"].to_numpy(float),
                     df[f"{s}_suddenness"].to_numpy(float), np.log1p(df[f"{s}_recurrence"].to_numpy(float))]
    return np.column_stack(cols)


def _full_proba(clf, X, n_classes: int) -> np.ndarray:
    pr = clf.predict_proba(X)
    out = np.zeros((len(X), n_classes))
    out[:, clf.classes_] = pr
    return out


class FusionA:
    name = "F-A"

    def __init__(self, temporal: bool = True, streams=STREAMS, C: float = 1.0):
        self.temporal, self.streams, self.C = temporal, streams, C
        self.clf = None

    def fit(self, df: pd.DataFrame, y: np.ndarray) -> "FusionA":
        self.clf = make_pipeline(StandardScaler(), LogisticRegression(C=self.C, class_weight="balanced", max_iter=500))
        self.clf.fit(design_matrix(df, self.streams, self.temporal), y)
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        return _full_proba(self.clf, design_matrix(df, self.streams, self.temporal), len(CATS))

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.predict_proba(df).argmax(1)


def reliability(persist, rec, r_min: float, tau_p: float, lam: float) -> np.ndarray:
    """Reliability of a stream from its temporal context: grows with persistence and with recurrence."""
    r = r_min + (1 - r_min) * (1 - np.exp(-np.asarray(persist, float) / tau_p))
    return 1 - (1 - r) * np.exp(-lam * np.maximum(np.asarray(rec, float) - 1, 0))


def dempster_shafer(p_i, p_q, r_i, r_q) -> np.ndarray:
    """Pignistic probabilities over [N, I, Q, C] after combining the two sources (Dempster's rule, K = 0)."""
    p_i, p_q, r_i, r_q = (np.asarray(x, float) for x in (p_i, p_q, r_i, r_q))
    Ai, Bi, Ui = r_i * p_i, r_i * (1 - p_i), 1 - r_i
    Aq, Bq, Uq = r_q * p_q, r_q * (1 - p_q), 1 - r_q
    mC, mI, mQ, mN = Ai * Aq, Ai * Bq, Bi * Aq, Bi * Bq
    mIC, mNQ, mQC, mNI, mT = Ai * Uq, Bi * Uq, Ui * Aq, Ui * Bq, Ui * Uq
    betN = mN + mNQ / 2 + mNI / 2 + mT / 4
    betI = mI + mIC / 2 + mNI / 2 + mT / 4
    betQ = mQ + mNQ / 2 + mQC / 2 + mT / 4
    betC = mC + mIC / 2 + mQC / 2 + mT / 4
    return np.column_stack([betN, betI, betQ, betC])


GAMMAS = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)


class FusionB:
    """Dempster-Shafer fusion. Each stream's mass is discounted by its temporal reliability r. The decision uses
    the discounted belief that a stream's anomaly is present, Bel_s = r_s * p_s (the total mass supporting it), and
    reports a stream as active when Bel_s >= gamma. Category = (infra active, quality active). The pignistic
    probabilities give the confidence. gamma and the reliability parameters are tuned on validation."""

    name = "F-B"
    GRID_T = [(rm, tp, lam, g) for rm in (0.4, 0.6, 0.8) for tp in (6, 12, 24) for lam in (0.0, 0.3) for g in GAMMAS]
    GRID_C = [(1.0, 1.0, 0.0, g) for g in GAMMAS]

    def __init__(self, temporal: bool = True, quality: bool = True):
        self.temporal, self.quality = temporal, quality  # quality=False: no quality stream (BattLeDIM)
        self.params: tuple | None = None

    def _r(self, df, params):
        rm, tp, lam, _ = params
        if self.temporal:
            ri = reliability(df["infra_persist_steps"], df["infra_recurrence"], rm, tp, lam)
            rq = reliability(df["quality_persist_steps"], df["quality_recurrence"], rm, tp, lam)
        else:
            ri = rq = np.full(len(df), rm)
        if not self.quality:
            rq = np.ones(len(df))  # no quality sensor: certain that there is no quality anomaly
        return np.asarray(ri), np.asarray(rq)

    def _decide(self, df, params) -> np.ndarray:
        ri, rq = self._r(df, params)
        g = params[3]
        on_i = ri * df["p_infra"].to_numpy() >= g
        on_q = (rq * df["p_quality"].to_numpy() >= g) if self.quality else np.zeros(len(df), bool)
        return on_i.astype(int) + 2 * on_q.astype(int)

    def fit(self, df: pd.DataFrame, y: np.ndarray) -> "FusionB":
        best = None
        for params in (self.GRID_T if self.temporal else self.GRID_C):
            f = macro_f1(y, self._decide(df, params))
            if best is None or f > best[0] + 1e-9:
                best = (f, params)
        self.params = best[1]
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self._decide(df, self.params)

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        ri, rq = self._r(df, self.params)
        return dempster_shafer(df["p_infra"].to_numpy(), df["p_quality"].to_numpy(), ri, rq)


def macro_f1(y, pred, labels=None) -> float:
    """Macro F1 over the classes present in the truth (or `labels`)."""
    y, pred = np.asarray(y), np.asarray(pred)
    labels = np.unique(y) if labels is None else labels
    fs = []
    for c in labels:
        tp = np.sum((y == c) & (pred == c))
        fp = np.sum((y != c) & (pred == c))
        fn = np.sum((y == c) & (pred != c))
        fs.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)
    return float(np.mean(fs))


# ---------------------------------------------------------------- priority, confidence, explanation
def priority_points(category: str, persist_steps: float, intensity: float, recurrence: float) -> int:
    """Escalation rule (Normal has no alert and is Low). One point each for: Combined category, persistence of
    at least 1 h (12 steps), persistence of at least 6 h (72 steps), intensity (max fused evidence) >= 0.9,
    at least 2 recurring episodes in 7 days. Points 0 -> Low, 1 -> Medium, 2 -> High, >= 3 -> Critical."""
    if category == "Normal":
        return 0
    pts = int(category == "Combined") + int(persist_steps >= 12) + int(persist_steps >= 72)
    pts += int(intensity >= 0.9) + int(recurrence >= 2)
    return pts


def priority(category: str, persist_steps: float, intensity: float, recurrence: float) -> str:
    pts = priority_points(category, persist_steps, intensity, recurrence)
    return PRIORITIES[min(pts, 3)]


def assess(row: dict, proba: np.ndarray, k: int | None = None) -> dict:
    """Full assessment for one row: category (index `k`, default argmax), confidence (probability of that
    category), priority, explanation."""
    k = int(np.argmax(proba)) if k is None else int(k)
    cat = CATS[k]
    conf = float(proba[k])
    persist = max(row["infra_persist_steps"] if cat in ("Infrastructure", "Combined") else 0,
                  row["quality_persist_steps"] if cat in ("Quality", "Combined") else 0)
    intensity = max(row["p_infra"] if cat in ("Infrastructure", "Combined") else 0.0,
                    row["p_quality"] if cat in ("Quality", "Combined") else 0.0)
    rec = max(row["infra_recurrence"] if cat in ("Infrastructure", "Combined") else 0,
              row["quality_recurrence"] if cat in ("Quality", "Combined") else 0)
    pr = priority(cat, persist, intensity, rec)
    return {"category": cat, "confidence": conf, "priority": pr,
            "explanation": explain(row, cat, conf, pr)}


def explain(row: dict, cat: str, conf: float, pr: str) -> str:
    def stream(label, s):
        p = row[f"p_{s}"]
        steps = row[f"{s}_persist_steps"]
        return (f"{label} evidence {p:.2f}, "
                f"{'above threshold for ' + format(steps * 5 / 60, '.1f') + ' h' if steps > 0 else 'currently below threshold'}, "
                f"suddenness {row[f'{s}_suddenness']:.2f}, {int(row[f'{s}_recurrence'])} episode(s) in the last 7 days")

    if cat == "Normal":
        return (f"Normal (confidence {conf:.2f}): " + "; ".join([stream("infrastructure", "infra"), stream("quality", "quality")]) + ".")
    parts = []
    if cat in ("Infrastructure", "Combined"):
        parts.append(stream("infrastructure", "infra"))
    if cat in ("Quality", "Combined"):
        parts.append(stream("quality", "quality"))
    return f"{cat} anomaly, priority {pr} (confidence {conf:.2f}): " + "; ".join(parts) + "."
