"""Streaming processor: readings in, node assessments (category, priority, confidence, explanation) out.

Per reading: update the node's signal buffer (forward-fill short gaps like the batch pipeline), compute the
causal features of the last step (`compute_last`, tested equal to the batch features), evidence
probabilities from the calibrated modules, causal temporal features of each evidence stream, then the
selected fusion design. Deployed models are the scenario-trained modules (data/processed/models).
"""
from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from typing import Callable

import joblib
import numpy as np
import pandas as pd

from ..data.loaders import FFILL_LIMIT_5MIN
from ..features.causal import DAY, compute_last
from ..features.temporal import DEFAULT, temporal_features
from ..models.fusion import CATS, PRIORITIES, assess

ROOT = Path(__file__).resolve().parents[3]
MODELS = ROOT / "data" / "processed" / "models"
SIGNALS = ("flow", "pressure", "turbidity", "tds")
BUF = 400  # >= 289 needed for the 24 h lag and the 288-step windows
P_HIST = DEFAULT.rec_window + DEFAULT.gap + 8
SERIES_KEEP = 600  # points kept per node for the charts
CALM_STEPS = 12  # an alert closes after 1 h of Normal


class _Node:
    def __init__(self):
        self.buf = {s: deque(maxlen=BUF) for s in SIGNALS}
        self.last_valid = {s: np.nan for s in SIGNALS}
        self.age = {s: 0 for s in SIGNALS}
        self.p = {"infra": deque(maxlen=P_HIST), "quality": deque(maxlen=P_HIST)}
        self.series: deque = deque(maxlen=SERIES_KEEP)
        self.latest: dict | None = None
        self.calm = 0
        self.open_alert: dict | None = None


class LiveProcessor:
    def __init__(self, store=None, models_dir: Path = MODELS):
        self.store = store
        ev = {d: joblib.load(models_dir / f"evidence_scenarios_{d}.joblib") for d in ("infra", "quality")}
        self.modules = {d: ev[d]["module"] for d in ev}
        self.columns = {d: ev[d]["columns"] for d in ev}
        fz = joblib.load(models_dir / "fusion_selected.joblib")
        self.design, self.fusion = fz["design"], fz["model"]
        self.nodes: dict[str, _Node] = {}
        self.alerts: list[dict] = []
        self.listeners: list[Callable[[str, dict], None]] = []
        self.lock = threading.RLock()
        self._alert_seq = 0
        self.processed = 0

    # ----------------------------------------------------------- setup
    def prime(self, node_id: str, history: pd.DataFrame) -> None:
        """Fill a node's signal buffers from earlier rows (no outputs, evidence history stays empty)."""
        with self.lock:
            n = self.nodes.setdefault(node_id, _Node())
            for _, row in history.iterrows():
                self._push(n, {s: row[s] for s in SIGNALS})

    def _push(self, n: _Node, vals: dict) -> None:
        for s in SIGNALS:
            v = vals.get(s)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                n.age[s] += 1
                v = n.last_valid[s] if n.age[s] <= FFILL_LIMIT_5MIN else np.nan
            else:
                n.last_valid[s], n.age[s] = float(v), 0
            n.buf[s].append(np.nan if v is None else float(v))

    # ----------------------------------------------------------- main entry
    def on_reading(self, r: dict) -> dict | None:
        with self.lock:
            n = self.nodes.setdefault(r["node_id"], _Node())
            self._push(n, r)
            self.processed += 1
            ready = len(n.buf["flow"]) > DAY
            vals = {s: n.buf[s][-1] for s in SIGNALS}
            ev_ok = {"infra": False, "quality": False}
            p = {"infra": 0.0, "quality": 0.0}
            if ready:
                feats = compute_last({s: np.fromiter(n.buf[s], float) for s in SIGNALS})
                feats.update(vals)  # raw signal values are model inputs too
                for d in ("infra", "quality"):
                    x = np.array([[feats.get(c, np.nan) for c in self.columns[d]]])
                    if np.isfinite(x).all():
                        p[d] = float(self.modules[d].predict_proba_array(x)[0])
                        ev_ok[d] = True
            for d in ("infra", "quality"):
                n.p[d].append(p[d])
            row = {"p_infra": p["infra"], "p_quality": p["quality"]}
            for d in ("infra", "quality"):
                t = temporal_features(np.fromiter(n.p[d], float), DEFAULT).iloc[-1]
                for k in ("suddenness", "persist_steps", "persist_frac", "recurrence"):
                    row[f"{d}_{k}"] = float(t[k])
            if ready:
                df = pd.DataFrame([row])
                k = int(self.fusion.predict(df)[0])
                proba = self.fusion.predict_proba(df)[0]
                a = assess(row, proba, k)
            else:
                a = {"category": "Normal", "priority": "Low", "confidence": None,
                     "explanation": "Warming up: collecting 24 h of history before assessing."}
            a.update({"node_id": r["node_id"], "ts": r["ts"], "status": "ok" if ready else "warming_up",
                      "p_infra": row["p_infra"], "p_quality": row["p_quality"],
                      "evidence_available": ev_ok,
                      "temporal": {k: row[k] for k in row if k not in ("p_infra", "p_quality")}})
            n.latest = a
            n.series.append({"ts": r["ts"], **{s: (None if np.isnan(vals[s]) else vals[s]) for s in SIGNALS},
                             "p_infra": a["p_infra"], "p_quality": a["p_quality"], "category": a["category"],
                             "priority": a["priority"]})
            alert_event = self._update_alert(n, a)
        if self.store is not None:
            self.store.write_assessment(a)
        for fn in self.listeners:
            fn("assessment", a)
            if alert_event:
                fn("alert", alert_event)
        return a

    # ----------------------------------------------------------- alerts
    def _update_alert(self, n: _Node, a: dict) -> dict | None:
        if a["category"] == "Normal":
            n.calm += 1
            if n.open_alert is not None and n.calm >= CALM_STEPS:
                n.open_alert.update(status="closed", end_ts=a["ts"])
                ev, n.open_alert = n.open_alert, None
                return dict(ev)
            return None
        n.calm = 0
        if n.open_alert is None:
            self._alert_seq += 1
            n.open_alert = {"id": self._alert_seq, "node_id": a["node_id"], "category": a["category"],
                            "priority": a["priority"], "max_priority": a["priority"], "start_ts": a["ts"],
                            "last_ts": a["ts"], "end_ts": None, "status": "active", "confidence": a["confidence"],
                            "explanation": a["explanation"]}
            self.alerts.append(n.open_alert)
            return dict(n.open_alert)
        al = n.open_alert
        changed = al["category"] != a["category"] or al["priority"] != a["priority"]
        al.update(category=a["category"], priority=a["priority"], last_ts=a["ts"], confidence=a["confidence"],
                  explanation=a["explanation"])
        if PRIORITIES.index(a["priority"]) > PRIORITIES.index(al["max_priority"]):
            al["max_priority"] = a["priority"]
        return dict(al) if changed else None

    # ----------------------------------------------------------- queries
    def latest(self, node_id: str) -> dict | None:
        with self.lock:
            n = self.nodes.get(node_id)
            return dict(n.latest) if n and n.latest else None

    def series(self, node_id: str, limit: int = SERIES_KEEP) -> list[dict]:
        with self.lock:
            n = self.nodes.get(node_id)
            return list(n.series)[-limit:] if n else []

    def list_alerts(self, category=None, priority=None, node=None, status=None, limit=200) -> list[dict]:
        with self.lock:
            out = [dict(a) for a in reversed(self.alerts)]
        for key, val in (("category", category), ("priority", priority), ("node_id", node), ("status", status)):
            if val:
                out = [a for a in out if a[key] == val]
        return out[:limit]

    def counts(self) -> dict:
        with self.lock:
            c = {k: 0 for k in CATS}
            for n in self.nodes.values():
                if n.latest:
                    c[n.latest["category"]] += 1
            return c
