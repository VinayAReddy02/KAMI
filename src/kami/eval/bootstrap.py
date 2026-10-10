"""Bootstrap 95% confidence intervals (1000 resamples, fixed seed) for the event-level metrics, and paired differences.

Units (PLAN_ROUND2 R6): EVENTS are resampled for recall, precision, F1 and category accuracy; whole DAYS are resampled
for false alarms. Concretely, one replicate draws events with replacement (each event carries whether it was detected,
how many true alert segments belong to it and whether its category was right) and, independently, calendar days with
replacement (each day carries its false alert segments and its scored normal rows). From the same replicate:

    recall                 = detected events / events
    precision              = true segments / (true segments + false segments)        (segment-based, as tuned)
    precision_event_counted = detected events / (detected events + false segments)   (each event counted once)
    f1, f1_event_counted   = harmonic means with recall
    fa_per_day             = false segments / (normal rows / 288)
    category_accuracy      = events with the right category / events

True segments are therefore kept together with their event (fragments of one alert are not treated as independent) and
false alarms of one day stay together. The draws depend only on the number of events and days, so two models scored
on the same frame get the SAME resampled events and days: `paired_diff` gives intervals for their difference.
Events and days are resampled independently of each other and serial dependence between neighbouring days is ignored,
so the intervals are approximate. Percentile intervals; when every unit agrees the interval has zero width, which
means "no variation among the resampled units", not certainty.
"""
from __future__ import annotations

import numpy as np

N_BOOT = 1000
SEED = 12345
METRICS = ("recall", "precision", "f1", "precision_event_counted", "f1_event_counted", "fa_per_day", "category_accuracy")


def _f1(p, r):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(p + r > 0, 2 * p * r / (p + r), 0.0)


def _ratio(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, a / b, 0.0)


def replicates(detail: dict, cat_ok: np.ndarray, n: int = N_BOOT, seed: int = SEED) -> dict:
    """Per-replicate values of every metric for one model (arrays of length n)."""
    det = np.asarray(detail["event_detected"], float)
    tseg = np.asarray(detail["event_true_segments"], float)
    cat = np.asarray(cat_ok, float)
    fp = np.asarray(detail["day_false_segments"], float)
    rows = np.asarray(detail["day_normal_rows"], float)
    E, D = len(det), len(fp)
    rng = np.random.default_rng(seed)
    ie = rng.integers(0, E, (n, E)) if E else np.zeros((n, 0), int)
    idd = rng.integers(0, D, (n, D)) if D else np.zeros((n, 0), int)
    n_det, n_true, n_cat = det[ie].sum(1), tseg[ie].sum(1), cat[ie].sum(1)
    n_fp, n_rows = fp[idd].sum(1), rows[idd].sum(1)
    recall = n_det / E if E else np.zeros(n)
    precision = _ratio(n_true, n_true + n_fp)
    precision_ev = _ratio(n_det, n_det + n_fp)
    return {"recall": recall, "precision": precision, "f1": _f1(precision, recall),
            "precision_event_counted": precision_ev, "f1_event_counted": _f1(precision_ev, recall),
            "fa_per_day": _ratio(n_fp, n_rows / 288.0),
            "category_accuracy": n_cat / E if E else np.zeros(n)}


def ci(x) -> list[float]:
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))]


def intervals(reps: dict) -> dict:
    return {k: ci(v) for k, v in reps.items()}


def paired_diff(reps_a: dict, reps_b: dict) -> dict:
    """95% interval of (a - b) per metric, using the same resampled events and days for both models."""
    out = {}
    for k in METRICS:
        d = np.asarray(reps_a[k]) - np.asarray(reps_b[k])
        lo, hi = ci(d)
        out[k] = {"ci95": [lo, hi], "excludes_zero": bool(lo > 0 or hi < 0)}
    return out
