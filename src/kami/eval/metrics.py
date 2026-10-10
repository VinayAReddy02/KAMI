"""Point-level and event-level metrics for anomaly detectors on time-ordered node series.

Definitions (all on *scored* rows: valid, not ambiguous, features available):
  point P/R/F1   : row-wise prediction vs the domain flag.
  alert segment  : run of predicted rows; runs separated by <= GAP_STEPS rows are merged.
  event detected : any predicted row inside the event window [start, end].
  true alert     : segment overlapping an event window extended by GRACE_STEPS after its end.
  false alert    : any other segment.   False alarms per day = false alerts / days of scored normal rows.
  event P        : true alerts / alerts;  event R : detected events / events;  event F1 from these.
  latency        : hours from event start to the first predicted row in the event (detected events only).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STEP_MIN = 5
GAP_STEPS = 12
GRACE_STEPS = 12


def runs(b: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive (start, end) index pairs of True runs."""
    if not b.any():
        return []
    d = np.diff(np.concatenate([[0], b.astype(np.int8), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1))


def merge_runs(rs: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for a, b in rs:
        if out and a - out[-1][1] <= gap + 1:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def domain_events(df: pd.DataFrame, domain: str, override: pd.DataFrame | None = None) -> pd.DataFrame:
    """Events of a domain ('infra' or 'quality'): node_id, event_id, type, start, end."""
    if override is not None:
        return override
    flag = f"{domain}_flag"
    e = df[df[flag] & (df.event_id != "")]
    g = e.groupby(["node_id", "event_id"]).agg(type=("event_type", "first"), start=("ts", "min"), end=("ts", "max"))
    return g.reset_index()


def _prf(tp: float, fp: float, fn: float) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def evaluate(df: pd.DataFrame, pred: np.ndarray, domain: str, events: pd.DataFrame | None = None,
             scored: np.ndarray | None = None) -> dict:
    """df: one split (any nodes). pred: bool per row of df. scored: bool per row (default all).

    `events` (node_id, event_id, type, start, end) overrides the events derived from the flags.
    """
    flag_col = f"{domain}_flag"
    d = df.assign(_pred=np.asarray(pred, bool), _scored=True if scored is None else np.asarray(scored, bool))
    ev_all = domain_events(df, domain, events)
    tp_p = fp_p = fn_p = 0
    n_det = n_events = tp_seg = fp_seg = normal_rows = 0
    latencies: list[float] = []
    by_type: dict[str, list[int]] = {}
    for node, g in d.sort_values(["node_id", "ts"]).groupby("node_id", sort=False):
        ts = g.ts.to_numpy()
        sc = g._scored.to_numpy()
        pr = g._pred.to_numpy() & sc
        raw_fl = g[flag_col].to_numpy()
        fl = raw_fl & sc
        tp_p += int((pr & fl).sum())
        fp_p += int((pr & ~fl).sum())
        fn_p += int((~pr & fl).sum())
        normal_rows += int((sc & ~raw_fl).sum())
        segs = merge_runs(runs(pr), GAP_STEPS)
        ev = ev_all[ev_all.node_id == node] if "node_id" in ev_all else ev_all
        spans = []
        for _, e in ev.iterrows():
            a = int(np.searchsorted(ts, np.datetime64(e.start), "left"))
            b = int(np.searchsorted(ts, np.datetime64(e.end), "right")) - 1
            if b >= a:
                spans.append((a, b, e.type))
        for a, b, typ in spans:
            n_events += 1
            by_type.setdefault(typ, [0, 0])[1] += 1
            hit = np.where(pr[a:b + 1])[0]
            if hit.size:
                n_det += 1
                by_type[typ][0] += 1
                latencies.append(float(hit[0]) * STEP_MIN / 60.0)
        for sa, sb in segs:
            if any(sa <= b + GRACE_STEPS and sb >= a for a, b, _ in spans):
                tp_seg += 1
            else:
                fp_seg += 1
    pp, pr_, pf = _prf(tp_p, fp_p, fn_p)
    ep = tp_seg / (tp_seg + fp_seg) if tp_seg + fp_seg else 0.0
    er = n_det / n_events if n_events else 0.0
    ef = 2 * ep * er / (ep + er) if ep + er else 0.0
    ep_ev = n_det / (n_det + fp_seg) if n_det + fp_seg else 0.0
    days = normal_rows * STEP_MIN / 1440.0
    return {
        "point": {"precision": pp, "recall": pr_, "f1": pf},
        "event": {"precision": ep, "recall": er, "f1": ef, "events": n_events, "detected": n_det,
                  "alert_segments": tp_seg + fp_seg, "false_alert_segments": fp_seg,
                  # each detected event counted once (Round 2): detected events / (detected events + false alerts)
                  "precision_event_counted": ep_ev, "f1_event_counted": 2 * ep_ev * er / (ep_ev + er) if ep_ev + er else 0.0},
        "false_alarms_per_day": fp_seg / days if days else 0.0,
        "latency_h": {"median": float(np.median(latencies)) if latencies else None,
                      "p90": float(np.percentile(latencies, 90)) if latencies else None, "n": len(latencies)},
        "per_type_recall": {k: {"recall": v[0] / v[1], "events": v[1]} for k, v in sorted(by_type.items())},
        "scored_normal_days": days,
    }
