"""Bootstrap 95% confidence intervals (1000 resamples, fixed seed) for event-level metrics.

Events are resampled for recall and category accuracy, alert segments for precision (F1 combines the replicate's
recall and precision), and whole days for false alarms per day.
"""
from __future__ import annotations

import numpy as np

N_BOOT = 1000


def _ci(x) -> list[float]:
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))]


def bootstrap_any(details: dict, cat_ok: np.ndarray | None = None, n: int = N_BOOT, seed: int = 12345) -> dict:
    rng = np.random.default_rng(seed)
    det, seg_tp = details["detected"], details["seg_tp"]
    E, S = len(det), len(seg_tp)
    days = np.array(sorted(details["normal_rows_by_day"]), dtype="datetime64[D]")
    rows = np.array([details["normal_rows_by_day"][d] for d in days], float)
    fa_by_day = np.array([int(((details["seg_day"] == d) & ~seg_tp).sum()) for d in days], float)
    D = len(days)
    rec, prec, f1, fa, cat = [], [], [], [], []
    for _ in range(n):
        ie = rng.integers(0, E, E) if E else np.array([], int)
        is_ = rng.integers(0, S, S) if S else np.array([], int)
        id_ = rng.integers(0, D, D)
        r = det[ie].mean() if E else 0.0
        p = seg_tp[is_].mean() if S else 0.0
        rec.append(r)
        prec.append(p)
        f1.append(2 * p * r / (p + r) if p + r else 0.0)
        den = rows[id_].sum() / 288.0
        fa.append(fa_by_day[id_].sum() / den if den else 0.0)
        if cat_ok is not None and E:
            cat.append(cat_ok[ie].mean())
    out = {"recall": _ci(rec), "precision": _ci(prec), "f1": _ci(f1), "fa_per_day": _ci(fa)}
    if cat:
        out["category_accuracy"] = _ci(cat)
    return out
