"""Loaders to the common schema (Step 2).

Common columns: ts, node_id, flow, pressure, turbidity, tds, plus labels
event_id, event_type, infra_flag, quality_flag, source, semi_synthetic, valid, ambiguous.

Datasets built here
-------------------
battledim_network : ONE network-level series from BattLeDIM 2018+2019 (simulated hydraulics, real labels).
    flow = PUMP_1 (m3/h), pressure = mean of the 33 pressure sensors (m). turbidity/tds are NaN.
    Event windows come from the leak schedule (see `leak_events`).
scenario_background : three nodes (one per USGS station) with *unlabelled* background only:
    pressure = mean of every third pressure sensor group, flow = one BattLeDIM flow sensor,
    turbidity/tds = real USGS series shifted by 3 years so 2021-2022 lines up with 2018-2019.
    The scenario generator adds labelled events on top (`kami.simulator.scenarios`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .raw_loaders import USGS_STATIONS, load_battledim, load_usgs

SIGNALS = ["flow", "pressure", "turbidity", "tds"]
LABEL_COLS = ["event_id", "event_type", "infra_flag", "quality_flag", "source", "semi_synthetic", "valid", "ambiguous"]
COLUMNS = ["ts", "node_id", *SIGNALS, *LABEL_COLS]
TDS_FACTOR = 0.64
STEP = pd.Timedelta(minutes=5)
FFILL_LIMIT_5MIN = 20  # 15-min USGS values held for at most ~90 min (6 samples) -> 20 five-minute steps
EVENT_CAP = pd.Timedelta(days=7)
MIN_EVENT = pd.Timedelta(days=1)
GUARD = pd.Timedelta(days=1)


def _battledim_two_years() -> dict[str, pd.DataFrame]:
    parts = [load_battledim(y) for y in (2018, 2019)]
    return {k: pd.concat([p[k] for p in parts]) for k in ("pressure", "flow", "leak")}


def leak_events(leak: pd.DataFrame, config_types: dict[str, str]) -> tuple[pd.DataFrame, pd.Series]:
    """Event table and per-row `ambiguous` mask from the leak flow matrix.

    Rule: a leak's labelled window starts when its leak flow first reaches 50% of its own peak (t50)
    and lasts until the leak is fixed or 7 days, whichever is earlier. Leaks shorter than 1 day
    inside the data are dropped. BattLeDIM always has concurrent leaks (in 2019 every row), so the label means
    *onset of a new leak*; older leaks are background. The 24 h after a window ends is `ambiguous` (the leak
    is still acting but no longer labelled) and is excluded from scoring.
    """
    rows = []
    idx = leak.index
    for pipe in leak.columns:
        s = leak[pipe]
        peak = s.max()
        if peak <= 0:
            continue
        t50 = s.index[np.argmax(s.to_numpy() >= 0.5 * peak)]
        active_end = s[s > 0.01 * peak].index.max()
        end = min(active_end, t50 + EVENT_CAP, idx[-1])
        if end - t50 < MIN_EVENT:
            continue
        rows.append({"event_id": f"leak-{pipe}", "pipe": pipe, "start": t50, "end": end, "peak_flow": float(peak),
                     "leak_type": config_types.get(pipe, "unknown"),
                     "event_type": "infra_burst" if config_types.get(pipe) == "abrupt" else "infra_leak"})
    ev = pd.DataFrame(rows).sort_values("start").reset_index(drop=True)
    guard = pd.Series(False, index=idx)
    for _, e in ev.iterrows():
        guard.loc[e.end + STEP : e.end + GUARD] = True
    return ev, guard


def _leak_types() -> dict[str, str]:
    import re

    from .raw_loaders import RAW

    txt = (RAW / "battledim" / "dataset_configuration.yaml").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^- (p\d+),\s*[\d\- :]+,\s*[\d\- :]+,\s*[\d.]+,\s*(abrupt|incipient)", txt, re.M):
        out[m.group(1)] = m.group(2)
    return out


def build_battledim_network() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    b = _battledim_two_years()
    log = {"rows_in": len(b["pressure"]), "duplicate_ts": int(b["pressure"].index.duplicated().sum()),
           "nan_pressure": int(b["pressure"].isna().sum().sum()), "nan_flow": int(b["flow"].isna().sum().sum())}
    ev, ambiguous = leak_events(b["leak"], _leak_types())
    idx = b["pressure"].index
    df = pd.DataFrame({
        "ts": idx, "node_id": "battledim-network",
        "flow": b["flow"]["PUMP_1"].to_numpy(),
        "pressure": b["pressure"].mean(axis=1).to_numpy(),
        "turbidity": np.nan, "tds": np.nan,
    })
    df["event_id"] = ""
    df["event_type"] = "normal"
    df["infra_flag"] = False
    df["quality_flag"] = False
    for _, e in ev.iterrows():
        m = (df.ts >= e.start) & (df.ts <= e.end)
        df.loc[m & ~df.infra_flag, ["event_id", "event_type"]] = [e.event_id, e.event_type]
        df.loc[m, "infra_flag"] = True
    df["source"] = "battledim_simulated"
    df["semi_synthetic"] = True
    df["valid"] = df[["flow", "pressure"]].notna().all(axis=1)
    df["ambiguous"] = ambiguous.to_numpy()
    log["events"] = len(ev)
    log["ambiguous_rows"] = int(df.ambiguous.sum())
    return df[COLUMNS], ev, log


def usgs_5min(station: str) -> tuple[pd.DataFrame, dict]:
    u = load_usgs(station)
    n_in = len(u)
    dup = int(u.ts.duplicated().sum())
    u = u.drop_duplicates("ts", keep="last").set_index("ts").sort_index()
    bad_turb = int((u.turbidity <= 0).sum())
    u.loc[u.turbidity <= 0, "turbidity"] = np.nan  # invalid (sensor fouling / negative baseline offset)
    u["tds"] = u.conductance * TDS_FACTOR
    grid = pd.date_range("2021-01-01 00:00", "2022-12-31 23:55", freq="5min")
    u = u[["turbidity", "tds"]].reindex(grid).ffill(limit=FFILL_LIMIT_5MIN)
    u.index = u.index - pd.DateOffset(years=3)
    return u, {"rows_in": n_in, "duplicate_ts": dup, "invalid_turbidity_le0": bad_turb,
               "nan_turbidity_after_fill": int(u.turbidity.isna().sum()), "nan_tds_after_fill": int(u.tds.isna().sum())}


def build_scenario_background() -> tuple[pd.DataFrame, dict]:
    b = _battledim_two_years()
    idx = b["pressure"].index
    pcols = list(b["pressure"].columns)
    fcols = list(b["flow"].columns)
    frames, log = [], {}
    for k, st in enumerate(USGS_STATIONS):
        u, ulog = usgs_5min(st)
        log[st] = ulog
        u = u.reindex(idx)
        f = pd.DataFrame({
            "ts": idx, "node_id": f"scn-node-{k + 1}",
            "flow": b["flow"][fcols[k]].to_numpy(),
            "pressure": b["pressure"][pcols[k::3]].mean(axis=1).to_numpy(),
            "turbidity": u.turbidity.to_numpy(), "tds": u.tds.to_numpy(),
        })
        f["event_id"] = ""
        f["event_type"] = "normal"
        f["infra_flag"] = False
        f["quality_flag"] = False
        f["source"] = f"scenario_background(usgs {st}, battledim)"
        f["semi_synthetic"] = True
        f["valid"] = f[SIGNALS].notna().all(axis=1)
        f["ambiguous"] = False
        frames.append(f)
    return pd.concat(frames, ignore_index=True)[COLUMNS], log
