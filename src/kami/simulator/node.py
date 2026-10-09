"""Virtual sensor node fleet: replays public data over the bus like an ESP32 would.

Assignment of real series to the 8 demo nodes (everything mixed here is `semi_synthetic`):
  pressure  : BattLeDIM 2018 pressure sensors, 8 evenly spaced columns (metres), one per node.
  flow      : BattLeDIM 2018 has only 3 flow sensors, so node i reuses flow sensor (i mod 3) (m3/h).
  turbidity : USGS station (i mod 3), FNU, shifted in time by a node-specific offset.
  tds       : 0.64 x USGS specific conductance of the same station (uS/cm -> mg/L proxy).
USGS 15-min values are forward-filled to the 5-min BattLeDIM grid (at most 3 steps).
The USGS data are real but come from rivers in Virginia and are paired with simulated network
data, so the combined node series are semi-synthetic, not field data from one location.
"""
from __future__ import annotations

import argparse
import threading
import time

import numpy as np
import pandas as pd

from .. import config
from ..data.raw_loaders import USGS_STATIONS, load_battledim, load_usgs
from ..ingest.bus import Bus

TDS_FACTOR = 0.64
STEP_SECONDS = 300  # real-time spacing of BattLeDIM samples


def node_ids(n: int) -> list[str]:
    return [f"node-{i + 1}" for i in range(n)]


def build_node_frames(n_nodes: int = 8, year: int = 2018) -> dict[str, pd.DataFrame]:
    b = load_battledim(year)
    idx = b["pressure"].index
    pcols = list(b["pressure"].columns)
    pick = np.linspace(0, len(pcols) - 1, n_nodes).round().astype(int)
    fcols = list(b["flow"].columns)
    usgs = {}
    for s in USGS_STATIONS:
        u = load_usgs(s).drop_duplicates("ts").set_index("ts").sort_index()
        u = u.reindex(pd.date_range(u.index.min(), u.index.max(), freq="5min")).ffill(limit=3)
        usgs[s] = u
    frames = {}
    for i, nid in enumerate(node_ids(n_nodes)):
        u = usgs[USGS_STATIONS[i % len(USGS_STATIONS)]]
        off = (i * 4000) % max(1, len(u) - len(idx))
        uu = u.iloc[off : off + len(idx)]
        if len(uu) < len(idx):
            uu = uu.reindex(range(len(idx)))
        df = pd.DataFrame({
            "ts": idx,
            "flow": b["flow"][fcols[i % len(fcols)]].to_numpy(),
            "pressure": b["pressure"][pcols[pick[i]]].to_numpy(),
            "turbidity": uu["turbidity"].to_numpy(),
            "tds": uu["conductance"].to_numpy() * TDS_FACTOR,
        })
        df["source"] = "semi_synthetic"
        frames[nid] = df
    return frames


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
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self):
        n = min(len(f) for f in self.frames.values())
        end = n if self.max_steps is None else min(n, self.step + self.max_steps)
        while not self._stop.is_set() and self.step < end:
            if self.paused:
                time.sleep(0.05)
                continue
            for nid, f in self.frames.items():
                row = f.iloc[self.step]
                r = {"node_id": nid, "ts": row["ts"].isoformat(), "flow": _clean(row["flow"]),
                     "pressure": _clean(row["pressure"]), "turbidity": _clean(row["turbidity"]),
                     "tds": _clean(row["tds"])}
                if self.modifier:
                    r = self.modifier(nid, self.step, r)
                self.bus.publish(config.TOPIC_READINGS.format(node_id=nid), r)
                self.published += 1
            self.step += 1
            if self.speed > 0:
                time.sleep(STEP_SECONDS / self.speed)

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

    bus = make_bus(mode)
    fleet = NodeFleet(bus, build_node_frames(a.nodes), a.speed, max_steps=a.steps)
    fleet.start()
    fleet.join()
    bus.close()


if __name__ == "__main__":
    main()
