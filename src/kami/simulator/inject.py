"""Live event injection for the demo: applies scenario-generator effect profiles to readings in flight.

Uses the same event plans and physics as `scenarios.generate_scenarios` (docs/scenarios.md), so injected
events are `semi_synthetic` and look like the events the models were trained on.
"""
from __future__ import annotations

import threading

import numpy as np

from .scenarios import EVENT_TYPES, _plan_event, noise_scales

STEP_MIN = 5


class Injector:
    def __init__(self, frames: dict, seed: int = 123):
        self.seed = seed
        self.lock = threading.Lock()
        self.active: list[dict] = []
        self.history: list[dict] = []
        self.scales = {}
        for nid, f in frames.items():
            n_train = int(len(f) * 0.6)
            mask = np.zeros(len(f), bool)
            mask[:n_train] = True
            self.scales[nid] = noise_scales(f, mask)
        self._count = 0

    def inject(self, kind: str, node: str, step: int, ts: str | None = None) -> dict:
        if kind not in EVENT_TYPES:
            raise ValueError(f"unknown event type {kind}")
        if node not in self.scales:
            raise KeyError(node)
        with self.lock:
            self._count += 1
            rng = np.random.default_rng(self.seed + self._count)
            plan = _plan_event(kind, rng, self.scales[node])
            rec = {"id": f"inject-{self._count:03d}", "node_id": node, "type": kind, "start_step": step,
                   "start_ts": ts, "length_steps": int(plan["length"]), "plan": plan}
            self.active.append(rec)
            self.history.append({k: v for k, v in rec.items() if k != "plan"})
            return {k: v for k, v in rec.items() if k != "plan"}

    def modifier(self, nid: str, step: int, r: dict) -> dict:
        with self.lock:
            live = [e for e in self.active if e["node_id"] == nid]
            self.active = [e for e in self.active if step - e["start_step"] < e["length_steps"]]
        if not live:
            return r
        r = dict(r)
        for e in live:
            p, t = e["plan"], step - e["start_step"]
            for comp in ("infra", "turb", "tds"):
                c = p[comp]
                if not c:
                    continue
                i = t - p["offsets"][comp]
                if not 0 <= i < c["g"].size:
                    continue
                g = float(c["g"][i])
                if comp == "infra":
                    if r.get("pressure") is not None:
                        r["pressure"] -= c["dp"] * g
                    if r.get("flow") is not None:
                        r["flow"] += c["df"] * g
                elif comp == "turb" and r.get("turbidity") is not None:
                    r["turbidity"] *= float(np.exp(c["delta"] * g))
                elif comp == "tds" and r.get("tds") is not None:
                    r["tds"] *= 1 + c["rel"] * g
        return r

    def status(self) -> list[dict]:
        with self.lock:
            return list(self.history[-20:])
