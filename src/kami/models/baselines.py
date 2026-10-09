"""Baseline detectors (comparison only, not the contribution): fixed thresholds and Isolation Forest."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

SEED = 0


class FixedThreshold:
    """Independent per-sensor limits mean +/- k*std from training statistics; any sensor out of range alerts."""

    name = "fixed_threshold"

    def __init__(self, signals: list[str], k: float = 3.0):
        self.signals, self.k = signals, k
        self.mu: dict[str, float] = {}
        self.sd: dict[str, float] = {}

    def fit(self, train: pd.DataFrame) -> "FixedThreshold":
        for s in self.signals:
            x = train[s].dropna()
            self.mu[s], self.sd[s] = float(x.mean()), float(x.std()) + 1e-12
        return self

    def score(self, df: pd.DataFrame) -> np.ndarray:
        z = np.column_stack([np.abs(df[s].to_numpy(float) - self.mu[s]) / self.sd[s] for s in self.signals])
        return np.nanmax(np.where(np.isnan(z), -np.inf, z), axis=1)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.score(df) > self.k


class IsoForest:
    """Isolation Forest on raw signals plus the causal features of a domain; alert above a score quantile."""

    name = "isolation_forest"

    def __init__(self, columns: list[str], n_estimators: int = 100, max_samples: int = 256, quantile: float = 0.99):
        self.columns, self.n_estimators, self.max_samples, self.quantile = columns, n_estimators, max_samples, quantile
        self.model: IsolationForest | None = None
        self.threshold = np.inf
        self._train_scores: np.ndarray | None = None

    def fit(self, train: pd.DataFrame) -> "IsoForest":
        X = train[self.columns].to_numpy(float)
        self.model = IsolationForest(n_estimators=self.n_estimators, max_samples=min(self.max_samples, len(X)),
                                     random_state=SEED, n_jobs=-1).fit(X)
        self._train_scores = -self.model.score_samples(X)
        self.set_quantile(self.quantile)
        return self

    def set_quantile(self, q: float) -> None:
        self.quantile = q
        self.threshold = float(np.quantile(self._train_scores, q))

    def score(self, df: pd.DataFrame) -> np.ndarray:
        s = np.full(len(df), -np.inf)
        X = df[self.columns].to_numpy(float)
        ok = np.isfinite(X).all(axis=1)
        if ok.any():
            s[ok] = -self.model.score_samples(X[ok])
        return s

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.score(df) > self.threshold
