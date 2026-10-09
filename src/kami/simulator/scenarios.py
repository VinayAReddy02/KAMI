"""Labelled scenario generator: injects events into real/simulated background series.

EVERYTHING produced here is `semi_synthetic`. The rules and their physical rationale are in
docs/scenarios.md. Amplitudes are expressed in units of each signal's day-to-day noise
(robust std of x_t - x_{t-24h}) measured on the TRAIN split of the background, so they do not
depend on validation or test data.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from ..data.splits import assign_split

EVENT_TYPES = ["infra_leak", "infra_burst", "quality_turbidity_surge", "quality_tds_shift", "combined"]
STEP_MIN = 5
H = 60 // STEP_MIN  # steps per hour
DAY = 24 * H
MARGIN = 2 * DAY  # no event within 2 days of a split edge
GAP = 12 * H  # min gap between events on one node
CONTEXT = 6 * H  # background must be valid this long before/after an event
SOURCE = "scenario_semi_synthetic"


def _robust_sigma(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def noise_scales(bg: pd.DataFrame, train_mask: np.ndarray) -> dict:
    """Day-to-day noise per signal from the train split of one node's background."""
    out = {}
    for s in ("flow", "pressure"):
        x = bg[s].to_numpy(float)
        d = x[DAY:] - x[:-DAY]
        m = train_mask[DAY:]
        out[s] = _robust_sigma(d[m]) / np.sqrt(2)
    return out


def _smooth_ramp(n: int, ramp: int) -> np.ndarray:
    g = np.ones(n)
    r = min(ramp, n)
    g[:r] = np.linspace(0, 1, r, endpoint=False)
    return g


def _infra_profile(kind: str, rng, dur: int) -> tuple[np.ndarray, dict]:
    rec = H  # 1 h linear recovery after the repair
    if kind == "infra_leak":
        ramp = int(rng.uniform(6, 36) * H)
        g = _smooth_ramp(dur, ramp)
    else:  # burst: ramp within 5-15 minutes
        ramp = int(rng.integers(1, 4))
        g = _smooth_ramp(dur, ramp)
    tail = np.linspace(1, 0, rec, endpoint=False)[1:]
    g = np.concatenate([g, tail])
    return g, {"ramp_steps": ramp}


def _turbidity_profile(rng) -> tuple[np.ndarray, dict]:
    rise = int(rng.uniform(15, 60) / STEP_MIN) or 1
    tau = rng.uniform(2, 8) * H
    n_decay = int(4 * tau)
    g = np.concatenate([np.linspace(0, 1, rise, endpoint=False), np.exp(-np.arange(n_decay) / tau)])
    return g, {"rise_steps": rise, "tau_steps": float(tau)}


def _tds_profile(rng, dur: int) -> tuple[np.ndarray, dict]:
    ramp = int(rng.uniform(0.5, 3) * H)
    g = _smooth_ramp(dur, ramp)
    g = np.concatenate([g, np.linspace(1, 0, H, endpoint=False)[1:]])
    return g, {"ramp_steps": ramp}


def _plan_event(kind: str, rng, scales: dict) -> dict:
    """Draw the parameters and per-step effect profiles of one event (before placement)."""
    p: dict = {"type": kind, "infra": None, "turb": None, "tds": None}
    if kind in ("infra_leak", "infra_burst", "combined"):
        ik = kind if kind != "combined" else str(rng.choice(["infra_leak", "infra_burst"]))
        dur = int((rng.uniform(2, 5) if ik == "infra_leak" else rng.uniform(0.5, 2)) * DAY)
        g, meta = _infra_profile(ik, rng, dur)
        lo, hi = (3, 8) if ik == "infra_leak" else (5, 12)
        p["infra"] = {"kind": ik, "g": g, "dp": float(rng.uniform(lo, hi) * scales["pressure"]),
                      "df": float(rng.uniform(lo, hi) * scales["flow"]), **meta}
    if kind in ("quality_turbidity_surge", "combined"):
        g, meta = _turbidity_profile(rng)
        p["turb"] = {"g": g, "delta": float(rng.uniform(1.0, 2.5)), **meta}
    if kind == "quality_tds_shift" or (kind == "combined" and rng.random() < 0.5):
        dur = int(rng.uniform(0.25, 2) * DAY)
        g, meta = _tds_profile(rng, dur)
        p["tds"] = {"g": g, "rel": float(rng.uniform(0.2, 0.6)), **meta}
    # offsets (steps) of each component relative to the event start
    p["offsets"] = {"infra": 0, "turb": 0, "tds": 0}
    if kind == "combined":
        base = int(rng.uniform(-1, 3) * H)  # quality onset relative to infra onset
        p["offsets"]["turb"] = base
        p["offsets"]["tds"] = base + int(rng.uniform(0, 2) * H)
        m = min(p["offsets"].values())
        p["offsets"] = {k: v - m for k, v in p["offsets"].items()}
    p["length"] = max((p[k]["g"].size + p["offsets"][k]) if p[k] else 0 for k in ("infra", "turb", "tds"))
    return p


def _place(rng, n_events_len: list[int], lo: int, hi: int, ok_cum: np.ndarray, taken: list[tuple[int, int]]):
    """Return start indices for events of the given lengths inside [lo, hi), or raise."""
    starts = []
    for L in n_events_len:
        for _ in range(4000):
            s = int(rng.integers(lo, hi - L))
            a, b = s - CONTEXT, s + L + CONTEXT
            if a < 0 or b > len(ok_cum) - 1:
                continue
            if ok_cum[b] - ok_cum[a] != (b - a):
                continue
            if any(not (b + GAP <= t0 or a - GAP >= t1) for t0, t1 in taken):
                continue
            taken.append((s, s + L))
            starts.append(s)
            break
        else:
            raise RuntimeError("could not place event; reduce events per type")
    return starts


def generate_scenarios(background: pd.DataFrame, splits: dict, seed: int = 0, per_type: int = 4):
    """background: output of build_scenario_background (3 nodes). Returns (frame, events table).

    `per_type` events of every type are placed per node per split.
    """
    rng_master = np.random.SeedSequence(seed)
    nodes = list(background.node_id.drop_duplicates())
    child = rng_master.spawn(len(nodes))
    frames, events = [], []
    for node, seq in zip(nodes, child):
        rng = np.random.default_rng(seq)
        bg = background[background.node_id == node].sort_values("ts").reset_index(drop=True)
        split = assign_split(bg.ts, splits).to_numpy()
        scales = noise_scales(bg, split == "train")
        ok = (bg.valid.to_numpy()).astype(np.int64)
        ok_cum = np.concatenate([[0], np.cumsum(ok)])
        ts = bg.ts.to_numpy()
        flow, pres = bg.flow.to_numpy(float).copy(), bg.pressure.to_numpy(float).copy()
        turb, tds = bg.turbidity.to_numpy(float).copy(), bg.tds.to_numpy(float).copy()
        infra_flag = np.zeros(len(bg), bool)
        qual_flag = np.zeros(len(bg), bool)
        eid = np.full(len(bg), "", dtype=object)
        etype = np.full(len(bg), "normal", dtype=object)
        n_ev = 0
        for sp in ("train", "val", "test"):
            idx = np.where(split == sp)[0]
            lo, hi = idx[0] + MARGIN, idx[-1] + 1 - MARGIN
            kinds = [k for k in EVENT_TYPES for _ in range(per_type)]
            rng.shuffle(kinds)
            plans = [_plan_event(k, rng, scales) for k in kinds]
            taken: list[tuple[int, int]] = []
            starts = _place(rng, [p["length"] for p in plans], lo, hi, ok_cum, taken)
            for p, s0 in sorted(zip(plans, starts), key=lambda t: t[1]):
                n_ev += 1
                ev_id = f"{node}-{sp}-{n_ev:03d}"
                s_end = s0
                rec = {"event_id": ev_id, "node_id": node, "split": sp, "type": p["type"], "params": {}}
                if p["infra"]:
                    g = p["infra"]["g"]
                    a = s0 + p["offsets"]["infra"]
                    pres[a:a + g.size] -= p["infra"]["dp"] * g
                    flow[a:a + g.size] += p["infra"]["df"] * g
                    infra_flag[a:a + g.size] |= g > 0
                    s_end = max(s_end, a + g.size)
                    rec["params"]["infra"] = {k: v for k, v in p["infra"].items() if k != "g"} | {"start": str(ts[a])}
                if p["turb"]:
                    g = p["turb"]["g"]
                    a = s0 + p["offsets"]["turb"]
                    turb[a:a + g.size] *= np.exp(p["turb"]["delta"] * g)
                    qual_flag[a:a + g.size] |= g >= 0.05
                    s_end = max(s_end, a + g.size)
                    rec["params"]["turbidity"] = {k: v for k, v in p["turb"].items() if k != "g"} | {"start": str(ts[a])}
                if p["tds"]:
                    g = p["tds"]["g"]
                    a = s0 + p["offsets"]["tds"]
                    tds[a:a + g.size] *= 1 + p["tds"]["rel"] * g
                    qual_flag[a:a + g.size] |= g > 0
                    s_end = max(s_end, a + g.size)
                    rec["params"]["tds"] = {k: v for k, v in p["tds"].items() if k != "g"} | {"start": str(ts[a])}
                eid[s0:s_end] = ev_id
                etype[s0:s_end] = p["type"]
                rec["start"], rec["end"] = ts[s0], ts[min(s_end, len(ts)) - 1]
                rec["params"] = json.dumps(rec["params"], sort_keys=True)
                events.append(rec)
        out = bg.copy()
        out["flow"], out["pressure"], out["turbidity"], out["tds"] = flow, pres, turb, tds
        out["event_id"], out["event_type"] = eid, etype
        out["infra_flag"], out["quality_flag"] = infra_flag, qual_flag
        out["source"] = SOURCE
        out["semi_synthetic"] = True
        frames.append(out)
    return pd.concat(frames, ignore_index=True), pd.DataFrame(events)


def frame_hash(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=False).to_numpy().tobytes()).hexdigest()
