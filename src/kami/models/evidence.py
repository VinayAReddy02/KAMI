"""Calibrated per-domain evidence modules: p_infra from flow/pressure features, p_quality from turbidity/TDS.

Model type is chosen on the validation split (average precision) among logistic regression and a
histogram gradient-boosting classifier. Probabilities are calibrated with isotonic regression fitted on
validation. To report honest validation numbers, validation probabilities are produced by *cross-fitting*
the calibrator over contiguous time blocks of the validation split (each block calibrated by the others).
The calibrator used for the test split is fitted on the whole validation split.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SEED = 0
N_BLOCKS = 4
CANDIDATES = {
    "logreg_C0.1": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.1, class_weight="balanced", max_iter=300)),
    "logreg_C1": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=1.0, class_weight="balanced", max_iter=300)),
    "hgb_d3": lambda: HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.1, random_state=SEED),
    "hgb_d6": lambda: HistGradientBoostingClassifier(max_depth=6, max_iter=150, learning_rate=0.1, random_state=SEED),
}


def _raw(model, X):
    return model.predict_proba(X)[:, 1]


def time_blocks(ts: pd.Series, n: int = N_BLOCKS) -> np.ndarray:
    """Contiguous time-block ids (0..n-1) of a validation frame."""
    edges = np.quantile(ts.astype("int64").to_numpy(), np.linspace(0, 1, n + 1)[1:-1])
    return np.searchsorted(edges, ts.astype("int64").to_numpy(), side="right")


class EvidenceModule:
    def __init__(self, columns: list[str], label: str):
        self.columns, self.label = columns, label
        self.model_name: str | None = None
        self.model = None
        self.calibrator: IsotonicRegression | None = None
        self.selection: dict[str, float] = {}

    def fit(self, train: pd.DataFrame, val: pd.DataFrame, max_train: int = 250_000) -> "EvidenceModule":
        tr = train if len(train) <= max_train else train.sample(max_train, random_state=SEED).sort_index()
        Xtr, ytr = tr[self.columns].to_numpy(float), tr[self.label].to_numpy(bool)
        Xv, yv = val[self.columns].to_numpy(float), val[self.label].to_numpy(bool)
        best = None
        for name, mk in CANDIDATES.items():
            m = mk().fit(Xtr, ytr)
            ap = float(average_precision_score(yv, _raw(m, Xv)))
            self.selection[name] = ap
            if best is None or ap > best[0] + 1e-9:  # ties keep the earlier (simpler) candidate
                best = (ap, name, m)
        _, self.model_name, self.model = best
        raw_v = _raw(self.model, Xv)
        self.calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw_v, yv.astype(float))
        self._val_raw = raw_v
        return self

    def raw(self, df: pd.DataFrame) -> np.ndarray:
        return _raw(self.model, df[self.columns].to_numpy(float))

    def predict_proba_array(self, X: np.ndarray) -> np.ndarray:
        """Same as predict_proba for an already-built feature matrix (columns in `self.columns` order)."""
        return self.calibrator.predict(_raw(self.model, np.asarray(X, float)))

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Calibrated probability using the calibrator fitted on all of validation (use for test / live)."""
        return self.calibrator.predict(self.raw(df))

    def crossfit_val_proba(self, val: pd.DataFrame) -> np.ndarray:
        """Out-of-fold calibrated probabilities on validation (calibrator never sees the block it scores)."""
        raw = self.raw(val)
        y = val[self.label].to_numpy(float)
        blocks = time_blocks(val.ts)
        out = np.zeros(len(val))
        for b in range(N_BLOCKS):
            te, tr = blocks == b, blocks != b
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw[tr], y[tr])
            out[te] = iso.predict(raw[te])
        return out


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    ids = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = ids == b
        if m.any():
            rows.append({"bin": b, "mean_pred": float(p[m].mean()), "frac_pos": float(y[m].mean()), "n": int(m.sum())})
    return rows
