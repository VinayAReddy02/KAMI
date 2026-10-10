"""Fast repeated evaluation of "any alert vs any event" for threshold tuning, plus the pieces the bootstrap needs.

Same definitions as `metrics.evaluate` (domain "any"): alert segments merged across <= GAP_STEPS rows, an alert is
true if it overlaps an event window extended by GRACE_STEPS, false alarms per day over scored normal days.
Precomputes per-node arrays once so that many predictions can be scored quickly. Equality with
`metrics.evaluate` is unit-tested.

Two known properties of these segment-based metrics (both reported next to them, see run_final / SUMMARY):
  * duration is not penalised: a rule that alerts almost all the time has few, long segments;
  * fragments are counted: an event whose alert drops out for more than GAP_STEPS contributes several true segments,
    which raises precision. `precision_event_counted` / `f1_event_counted` count every detected event once instead
    (detected events / (detected events + false segments)).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .metrics import GAP_STEPS, GRACE_STEPS, STEP_MIN, merge_runs, runs

ROWS_PER_DAY = 1440 // STEP_MIN
# streams an event type contains: (infrastructure, quality)
TYPE_STREAMS = {"infra_leak": (True, False), "infra_burst": (True, False), "quality_turbidity_surge": (False, True),
                "quality_tds_shift": (False, True), "combined": (True, True)}
TYPE_CAT = {"infra_leak": 1, "infra_burst": 1, "quality_turbidity_surge": 2, "quality_tds_shift": 2, "combined": 3}


def _f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if p + r else 0.0


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
        self.scored_rows = sum(int(n["sc"].sum()) for n in self.nodes)

    def __call__(self, pred: np.ndarray, details: bool = False) -> dict:
        pred = np.asarray(pred, bool)
        det, latency, ev_types, ev_day, true_segs = [], [], [], [], []
        seg_tp, seg_day = [], []
        alert_rows = normal_alert_rows = 0
        for n in self.nodes:
            pr = pred[n["pos"]] & n["sc"]
            alert_rows += int(pr.sum())
            normal_alert_rows += int((pr & ~n["fl"]).sum())
            segs = merge_runs(runs(pr), GAP_STEPS)
            base = len(det)
            for a, b, typ in n["spans"]:
                hit = np.where(pr[a:b + 1])[0]
                det.append(bool(hit.size))
                latency.append(hit[0] * STEP_MIN / 60.0 if hit.size else np.nan)
                ev_types.append(typ)
                ev_day.append(n["day"][a])
                true_segs.append(0)
            for sa, sb in segs:
                owner = next((i for i, (a, b, _) in enumerate(n["spans"]) if sa <= b + GRACE_STEPS and sb >= a), None)
                seg_tp.append(owner is not None)
                seg_day.append(n["day"][sa])
                if owner is not None:
                    true_segs[base + owner] += 1  # a true segment belongs to the first event it overlaps
        n_seg, tp = len(seg_tp), int(sum(seg_tp))
        fp = n_seg - tp
        n_det = int(sum(det))
        p = tp / n_seg if n_seg else 0.0
        r = n_det / len(det) if det else 0.0
        p_ev = n_det / (n_det + fp) if n_det + fp else 0.0
        days = self.normal_rows / ROWS_PER_DAY
        lat = [x for x in latency if not np.isnan(x)]
        out = {"f1": _f1(p, r), "precision": p, "recall": r, "fa_per_day": fp / days if days else 0.0,
               "segments": n_seg, "true_segments": tp, "false_segments": fp, "events": len(det), "detected": n_det,
               "precision_event_counted": p_ev, "f1_event_counted": _f1(p_ev, r),
               "latency_median_h": float(np.median(lat)) if lat else None,
               "latency_p90_h": float(np.percentile(lat, 90)) if lat else None,
               "alert_fraction": alert_rows / self.scored_rows if self.scored_rows else 0.0,
               "normal_alert_fraction": normal_alert_rows / self.normal_rows if self.normal_rows else 0.0}
        if details:
            rows_by_day = self.normal_rows_by_day()
            days_sorted = sorted(set(rows_by_day) | set(seg_day))
            seg_tp_a, seg_day_a = np.array(seg_tp, bool), np.array(seg_day, dtype="datetime64[D]")
            out["detail"] = {
                "event_detected": np.array(det, bool), "event_type": np.array(ev_types), "event_latency_h": np.array(latency, float),
                "event_true_segments": np.array(true_segs, int), "event_start_day": np.array(ev_day, dtype="datetime64[D]"),
                "day": np.array(days_sorted, dtype="datetime64[D]"),
                "day_normal_rows": np.array([rows_by_day.get(d, 0) for d in days_sorted], float),
                "day_false_segments": np.array([int(((seg_day_a == d) & ~seg_tp_a).sum()) for d in days_sorted], float),
            }
        return out

    def normal_rows_by_day(self) -> dict:
        acc: dict = {}
        for n in self.nodes:
            m = n["sc"] & ~n["fl"]
            days, cnt = np.unique(n["day"][m], return_counts=True)
            for d, c in zip(days, cnt):
                acc[d] = acc.get(d, 0) + int(c)
        return acc

    def category_correct(self, pred_cat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Per event (same order as detail['event_detected']): does the set of streams the model reports during the event
        equal the streams the event contains? Infrastructure counts as reported if any scored row inside the event window is
        predicted Infrastructure or Combined; Quality if any row is predicted Quality or Combined. An undetected event is
        wrong. A prediction that equals the row labels on every row scores 1.0 (unit-tested).

        (Round 1 used "the most frequent non-Normal category inside the window". That rule is wrong for Combined events,
        whose quality part is much shorter than the infrastructure part: most rows are truly Infrastructure-only, so a
        perfect row-level prediction was marked wrong.)"""
        pred_cat = np.asarray(pred_cat, int)
        ok, types = [], []
        for n in self.nodes:
            pc = np.where(n["sc"], pred_cat[n["pos"]], 0)
            for a, b, typ in n["spans"]:
                w = pc[a:b + 1]
                reported = (bool(np.isin(w, (1, 3)).any()), bool(np.isin(w, (2, 3)).any()))
                ok.append(reported == TYPE_STREAMS[typ])
                types.append(typ)
        return np.array(ok, bool), np.array(types)
