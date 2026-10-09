"""Virtual sensor node fleet: replays public data over the bus like an ESP32 would.

Assignment of real series to the 8 demo nodes (everything mixed here is `semi_synthetic`):
  pressure  : BattLeDIM pressure sensors, mean of every third sensor starting at (node index mod 3), metres.
              This matches how the training backgrounds were built (docs/scenarios.md).
  flow      : BattLeDIM has only 3 flow sensors, so node i uses flow sensor (i mod 3), m3/h.
  turbidity : USGS station (i mod 3), FNU, shifted in time by a node-specific offset.
  tds       : 0.64 x USGS specific conductance of the same station (uS/cm -> mg/L proxy).
Nodes that share a sensor group are decorrelated by circularly shifting their infrastructure series by
(i // 3) x 12 days. USGS 15-min values are forward-filled to the 5-min grid (at most 20 steps).
The USGS data are real but come from rivers in Virginia and are paired with simulated network data,
so the combined node series are semi-synthetic, not field data from one location.
"""
from __future__ import annotations

import argparse
import threading
import time

import numpy as np
import pandas as pd

from .. import config
from ..data.loaders import FFILL_LIMIT_5MIN, TDS_FACTOR, _battledim_two_years, usgs_5min
from ..data.raw_loaders import USGS_STATIONS
from ..ingest.bus import Bus

STEP_SECONDS = 300  # real-time spacing of BattLeDIM samples


def node_ids(n: int) -> list[str]:
    return [f"node-{i + 1}" for i in range(n)]


def build_node_frames(n_nodes: int = 8) -> dict[str, pd.DataFrame]:
    b = _battledim_two_years()
    idx = b["pressure"].index
    pcols, fcols = list(b["pressure"].columns), list(b["flow"].columns)
    usgs = {s: usgs_5min(s)[0].reindex(idx) for s in USGS_STATIONS}
    frames = {}
    for i, nid in enumerate(node_ids(n_nodes)):
        k = i % 3
        shift = (i // 3) * 12 * 288
        u = usgs[USGS_STATIONS[k]]
        q_shift = (i * 4000) % len(idx)
        df = pd.DataFrame({
            "ts": idx,
            "flow": np.roll(b["flow"][fcols[k]].to_numpy(), -shift),
            "pressure": np.roll(b["pressure"][pcols[k::3]].mean(axis=1).to_numpy(), -shift),
            "turbidity": np.roll(u["turbidity"].to_numpy(), -q_shift),
            "tds": np.roll(u["tds"].to_numpy(), -q_shift),
        })
        df["source"] = "semi_synthetic"
        frames[nid] = df
    return frames


def find_clean_start(frames: dict[str, pd.DataFrame], lookback: int = 400, horizon: int = 3000,
                     max_missing: float = 0.02, first: int = 1000) -> int:
    """First step >= max(lookback, first) where, for every node, at most `max_missing` of the quality values
    in [s - lookback, s + horizon) are missing (the early 2018 period has the fewest background leaks)."""
    n = min(len(f) for f in frames.values())
    miss = np.zeros(n)
    for f in frames.values():
        miss = np.maximum(miss, 0)  # keep shape
    cs = []
    for f in frames.values():
        bad = f[["flow", "pressure", "turbidity", "tds"]].isna().any(axis=1).to_numpy()[:n]
        cs.append(np.concatenate([[0], np.cumsum(bad)]))
    span = lookback + horizon
    for s in range(max(lookback, first), n - horizon):
        if all((c[s + horizon] - c[s - lookback]) / span <= max_missing for c in cs):
            return s
    raise RuntimeError("no clean stretch found")


def _clean(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


class NodeFleet:
    """Publishes one reading per node per step. Thread-safe controls for speed/pause."""

    def __init__(self, bus: Bus, frames: dict[str, pd.DataFrame], speed: float = 600.0,
                 start: int = 0, max_steps: int | None = None, modifier=None):
        self.bus, self.frames = bus, frames
        self.speed = float(speed)
        self.step = start
        self.max_steps = max_steps
        self.modifier = modifier  # callable(node_id, step, reading) -> reading
        self.paused = False
        self.published = 0
        self.last_ts: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self):
        n = min(len(f) for f in self.frames.values())
        end = n if self.max_steps is None else min(n, self.step + self.max_steps)
        while not self._stop.is_set() and self.step < end:
            if self.paused:
                time.sleep(0.05)
                continue
            t_step = time.time()
            for nid, f in self.frames.items():
                row = f.iloc[self.step]
                r = {"node_id": nid, "ts": row["ts"].isoformat(), "flow": _clean(row["flow"]),
                     "pressure": _clean(row["pressure"]), "turbidity": _clean(row["turbidity"]),
                     "tds": _clean(row["tds"])}
                if self.modifier:
                    r = self.modifier(nid, self.step, r)
                self.bus.publish(config.TOPIC_READINGS.format(node_id=nid), r)
                self.published += 1
                self.last_ts = r["ts"]
            self.step += 1
            if self.speed > 0:
                wait = STEP_SECONDS / self.speed - (time.time() - t_step)
                if wait > 0:
                    time.sleep(wait)

    def start(self):
        self._thread = threading.Thread(target=self._run, name="node-fleet", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    @property
    def done(self) -> bool:
        return self._thread is not None and not self._thread.is_alive()


def main():
    ap = argparse.ArgumentParser(description="Replay public data as virtual sensor nodes over MQTT.")
    ap.add_argument("--dataset", default="battledim+usgs")
    ap.add_argument("--nodes", type=int, default=8)
    ap.add_argument("--speed", type=float, default=600.0, help="replay speedup vs real time (0 = as fast as possible)")
    ap.add_argument("--steps", type=int, default=None)
    a = ap.parse_args()
    mode = config.resolve_mode()
    if mode != "docker":
        raise SystemExit("Standalone node needs MQTT (Docker). In fallback mode use scripts/run_demo.py, "
                         "which hosts the in-process bus, worker and nodes in one process.")
    from ..ingest.bus import make_bus

    frames = build_node_frames(a.nodes)
    bus = make_bus(mode)
    fleet = NodeFleet(bus, frames, a.speed, start=find_clean_start(frames), max_steps=a.steps)
    fleet.start()
    fleet.join()
    bus.close()


if __name__ == "__main__":
    main()
