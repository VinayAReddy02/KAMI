"""Fast repeated evaluation of "any alert vs any event" for threshold tuning, plus the pieces bootstrap needs.

Same definitions as `metrics.evaluate` (domain "any"): alert segments merged across <= GAP_STEPS rows, an alert is
true if it overlaps an event window extended by GRACE_STEPS, false alarms per day over scored normal days.
Precomputes per-node arrays once so that many predictions can be scored quickly. Equality with
`metrics.evaluate` is unit-tested.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import GAP_STEPS, GRACE_STEPS, STEP_MIN, merge_runs, runs

ROWS_PER_DAY = 1440 // STEP_MIN


class AnyEvaluator:
    def __init__(self, df: pd.DataFrame, events: pd.DataFrame, scored: np.ndarray, flag_col: str = "any_flag"):
        self.n = len(df)
        self.nodes = []
        d = df.reset_index(drop=True).assign(_sc=np.asarray(scored, bool), _pos=np.arange(len(df)))
        for node, g in d.sort_values(["node_id", "ts"]).groupby("node_id", sort=False):
            ts = g.ts.to_numpy()
            ev = events[events.node_id == node]
            spans = []
            for _, e in ev.iterrows():
                a = int(np.searchsorted(ts, np.datetime64(e.start), "left"))
                b = int(np.searchsorted(ts, np.datetime64(e.end), "right")) - 1
                if b >= a:
                    spans.append((a, b, e.type))
            self.nodes.append({"pos": g._pos.to_numpy(), "sc": g._sc.to_numpy(), "fl": g[flag_col].to_numpy(bool),
                               "spans": spans, "day": ts.astype("datetime64[D]")})
        self.n_events = sum(len(n["spans"]) for n in self.nodes)
        self.normal_rows = sum(int((n["sc"] & ~n["fl"]).sum()) for n in self.nodes)

    def __call__(self, pred: np.ndarray, details: bool = False) -> dict:
        pred = np.asarray(pred, bool)
        det, seg_tp, seg_day, latencies, ev_types = [], [], [], [], []
        for n in self.nodes:
            pr = pred[n["pos"]] & n["sc"]
            segs = merge_runs(runs(pr), GAP_STEPS)
            for a, b, typ in n["spans"]:
                hit = np.where(pr[a:b + 1])[0]
                det.append(bool(hit.size))
                ev_types.append(typ)
                if hit.size:
                    latencies.append(hit[0] * STEP_MIN / 60.0)
            for sa, sb in segs:
                seg_tp.append(any(sa <= b + GRACE_STEPS and sb >= a for a, b, _ in n["spans"]))
                seg_day.append(n["day"][sa])
        n_seg = len(seg_tp)
        tp = sum(seg_tp)
        p = tp / n_seg if n_seg else 0.0
        r = sum(det) / len(det) if det else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        days = self.normal_rows / ROWS_PER_DAY
        fa = (n_seg - tp) / days if days else 0.0
        out = {"f1": f1, "precision": p, "recall": r, "fa_per_day": fa, "segments": n_seg, "events": len(det),
               "latency_median_h": float(np.median(latencies)) if latencies else None}
        if details:
            out["detected"] = np.array(det, bool)
            out["event_types"] = np.array(ev_types)
            out["seg_tp"] = np.array(seg_tp, bool)
            out["seg_day"] = np.array(seg_day, dtype="datetime64[D]")
            out["normal_rows_by_day"] = self.normal_rows_by_day()
        return out

    def normal_rows_by_day(self) -> dict:
        acc: dict = {}
        for n in self.nodes:
            m = n["sc"] & ~n["fl"]
            days, cnt = np.unique(n["day"][m], return_counts=True)
            for d, c in zip(days, cnt):
                acc[d] = acc.get(d, 0) + int(c)
        return acc


TYPE_CAT = {"infra_leak": 1, "infra_burst": 1, "quality_turbidity_surge": 2, "quality_tds_shift": 2, "combined": 3}


def category_correct(self: AnyEvaluator, pred_cat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per event (same order as `__call__(details=True)['detected']`): is the modal non-Normal predicted category inside
    the event window equal to the true category? Also returns the event types."""
    pred_cat = np.asarray(pred_cat, int)
    ok, types = [], []
    for n in self.nodes:
        pc = np.where(n["sc"], pred_cat[n["pos"]], 0)
        for a, b, typ in n["spans"]:
            w = pc[a:b + 1]
            w = w[w > 0]
            ok.append(bool(w.size and np.bincount(w).argmax() == TYPE_CAT[typ]))
            types.append(typ)
    return np.array(ok, bool), np.array(types)


AnyEvaluator.category_correct = category_correct
