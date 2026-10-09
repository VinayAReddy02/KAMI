"""Causal temporal-context features of one evidence stream p(t) in [0, 1] (per node, time ordered).

  suddenness     max over the last `window` steps of the (non-negative) rise p_u - p_{u-k}.
                 In [0, 1]: 1 means the evidence jumped from 0 to 1 within k steps.
  persist_steps  length of the current run of consecutive steps with p >= theta (0 if p < theta).
  persist_frac   share of the last `frac_window` steps with p >= theta.
  recurrence     number of separate episodes that started within the last `rec_window` steps. An episode
                 starts at a step with p >= theta after at least `gap` steps below theta.

Everything at step t uses steps <= t only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TemporalParams:
    theta: float = 0.5
    k: int = 3  # 15 min
    window: int = 24  # 2 h
    frac_window: int = 72  # 6 h
    gap: int = 24  # 2 h below theta ends an episode
    rec_window: int = 2016  # 7 days

    def as_dict(self):
        return asdict(self)


DEFAULT = TemporalParams()


def temporal_features(p, params: TemporalParams = DEFAULT, prefix: str = "") -> pd.DataFrame:
    p = pd.Series(np.asarray(p, float)).fillna(0.0)  # missing evidence counts as no evidence
    b = (p >= params.theta).to_numpy()
    n = len(p)
    rise = (p - p.shift(params.k)).clip(lower=0).fillna(0.0)
    suddenness = rise.rolling(params.window, min_periods=1).max()
    idx = np.arange(n)
    last_off = np.maximum.accumulate(np.where(~b, idx, -1))
    persist = np.where(b, idx - last_off, 0)
    frac = pd.Series(b.astype(float)).rolling(params.frac_window, min_periods=1).mean()
    prev_any = pd.Series(b.astype(float)).shift(1).rolling(params.gap, min_periods=1).max().fillna(0.0).to_numpy() > 0
    starts = (b & ~prev_any).astype(float)
    recurrence = pd.Series(starts).rolling(params.rec_window, min_periods=1).sum()
    return pd.DataFrame({
        f"{prefix}suddenness": suddenness.to_numpy(),
        f"{prefix}persist_steps": persist.astype(float),
        f"{prefix}persist_frac": frac.to_numpy(),
        f"{prefix}recurrence": recurrence.to_numpy(),
    })
