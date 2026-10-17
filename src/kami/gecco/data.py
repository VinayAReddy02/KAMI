"""GECCO Industrial Challenge 2019 drinking-water data (real, labelled) as a KAMI quality-stream frame (Round 7, Part G).

Protocol: docs/gecco_protocol.md (committed before any test label was read). In short:
  train = file 7 (Jul to Sep 2017), validation = file 8 (Oct 1 to Nov 8), test = file 6 (Nov 8 to 29), by time.
  turbidity [FNU] <- Turb [FNU];  tds [mg/L] <- Cond [S/m] x 10 000 (-> uS/cm) x 0.64.  pH, SAC, Tp, PFM are not used.
  Rows with Tp, pH, Cond, Turb and SAC all exactly 0 are sensor dropouts (set to missing).
  5-minute clock-aligned steps (time stamp = step start): median of the minutes; event step if any minute is an event.
The test file's `Event` column is never read by `build_frame`; `attach_test_labels` reads it, and only while
`kami.eval.access.final_evaluation(..., "gecco_test", ...)` is open.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .. import config
from ..features.causal import compute_features

RAW = config.ROOT / "data" / "raw" / "gecco"
FILES = {"train": "7_gecco2019_train_water_quality.csv", "val": "8_gecco2019_valid_water_qulity.csv",
         "test": "6_gecco2019_test_water_quality.csv"}
DATASET = "gecco_test"  # the name the guarded test access is logged under
NODE = "gecco"
DATA_KIND = "real"
EVENT_TYPE = "real_quality_event"
SIGNALS = ["turbidity", "tds"]
US_CM_PER_S_M = 10_000.0
TDS_PER_US_CM = 0.64  # the same conversion as for the USGS data (docs/datasets.md)
DROPOUT_COLS = ["Tp", "pH", "Cond", "Turb", "SAC"]
STEP = "5min"


def read_minutes(split: str, root: Path = RAW, labels: bool = True) -> pd.DataFrame:
    """One file as 1-minute rows: ts, turbidity, tds (and `event` if labels=True). The test file is read without labels
    unless `attach_test_labels` asks for them."""
    if split == "test" and labels:
        _require_test_access()
    cols = ["Time", *DROPOUT_COLS] + (["Event"] if labels else [])
    raw = pd.read_csv(Path(root) / FILES[split], usecols=cols, encoding="utf-8")
    return map_signals(raw)


def map_signals(raw: pd.DataFrame) -> pd.DataFrame:
    """GECCO columns -> KAMI quality inputs (one row per minute)."""
    dropout = (raw[DROPOUT_COLS] == 0).all(axis=1)
    out = pd.DataFrame({"ts": pd.to_datetime(raw["Time"])})
    out["turbidity"] = raw["Turb"].astype(float).where(~dropout)
    out["tds"] = (raw["Cond"].astype(float) * US_CM_PER_S_M * TDS_PER_US_CM).where(~dropout)
    if "Event" in raw:
        out["event"] = raw["Event"].astype(bool)
    return out


def resample(minutes: pd.DataFrame) -> pd.DataFrame:
    """1-minute rows -> 5-minute steps (clock aligned, labelled by their start). Median of the available minutes; an
    event step if any minute is an event. Steps without any minute row are dropped."""
    g = minutes.set_index("ts").resample(STEP, label="left", closed="left")
    out = g[SIGNALS].median()
    n = g["turbidity"].size()
    if "event" in minutes:
        out["quality_flag"] = g["event"].max().fillna(False).astype(bool)
    out = out[n > 0].reset_index()
    return out


def runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """(first, last) index of every run of True."""
    f = np.asarray(flags, bool)
    d = np.diff(np.r_[0, f.astype(int), 0])
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0] - 1))


def label_events(steps: pd.DataFrame, split: str) -> pd.DataFrame:
    """event_id and event_type per step from runs of quality_flag (one event = one run of event steps)."""
    ids = np.full(len(steps), "", dtype=object)
    for i, (a, b) in enumerate(runs(steps["quality_flag"].to_numpy()), start=1):
        ids[a:b + 1] = f"{NODE}-{split}-{i:03d}"
    steps = steps.copy()
    steps["event_id"] = ids
    steps["event_type"] = np.where(ids != "", EVENT_TYPE, "")
    return steps


def build_frame(root: Path = RAW) -> pd.DataFrame:
    """The whole chronological series train -> validation -> test as one KAMI frame with causal features. Labels of
    train and validation are attached; the test rows have quality_flag = NaN and no event ids until
    `attach_test_labels` is called inside the guarded test access."""
    parts = []
    for split in ("train", "val", "test"):
        steps = resample(read_minutes(split, root, labels=(split != "test")))
        if split == "test":
            steps["quality_flag"] = np.nan
            steps["event_id"], steps["event_type"] = "", ""
        else:
            steps = label_events(steps, split)
        steps["split"] = split
        parts.append(steps)
    df = pd.concat(parts, ignore_index=True)
    assert df.ts.is_monotonic_increasing and not df.ts.duplicated().any(), "the three files must follow each other in time"
    df = pd.concat([df, compute_features(df[SIGNALS], signals=SIGNALS)], axis=1)
    df["node_id"] = NODE
    df["infra_flag"] = False
    df["ambiguous"] = False
    df["data_kind"] = DATA_KIND
    df.attrs["kami_dataset"] = DATASET
    return df


def _require_test_access() -> None:
    from ..eval import access

    if not (access._active["on"] and access._active["dataset"] == DATASET):
        raise access.TestSplitLocked("the GECCO test labels are only readable inside final_evaluation(..., 'gecco_test', ...)")


def attach_test_labels(df: pd.DataFrame, root: Path = RAW) -> pd.DataFrame:
    """A copy of `df` with the test rows' labels and event ids. Only inside the guarded test access."""
    _require_test_access()
    steps = label_events(resample(read_minutes("test", root, labels=True)), "test")
    out = df.copy()
    test = (out.split == "test").to_numpy()
    lab = steps.set_index("ts").reindex(out.loc[test, "ts"])
    assert lab["quality_flag"].notna().all(), "every test step must have a label"
    out.loc[test, "quality_flag"] = lab["quality_flag"].to_numpy()
    out.loc[test, "event_id"] = lab["event_id"].to_numpy()
    out.loc[test, "event_type"] = lab["event_type"].to_numpy()
    return out


def event_counts(split: str, root: Path = RAW) -> dict:
    """Events counted at 1 minute and at 5 minutes (merging can join runs less than 5 minutes apart)."""
    m = read_minutes(split, root, labels=True)
    s = resample(m)
    return {"events_1min": len(runs(m["event"].to_numpy())), "events_5min": len(runs(s["quality_flag"].to_numpy())),
            "event_minutes": int(m["event"].sum()), "event_steps": int(s["quality_flag"].sum()), "steps": len(s)}
