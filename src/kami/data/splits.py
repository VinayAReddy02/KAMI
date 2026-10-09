"""Chronological train/validation/test splits per dataset; no event crosses a boundary."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

FRACTIONS = (0.6, 0.2, 0.2)


def event_spans(df: pd.DataFrame) -> pd.DataFrame:
    """One row per event_id: node_id, start, end (from rows with a non-empty event_id)."""
    e = df[df.event_id != ""]
    g = e.groupby(["node_id", "event_id"]).ts.agg(["min", "max"]).reset_index()
    return g.rename(columns={"min": "start", "max": "end"})


def make_splits(df: pd.DataFrame, fractions=FRACTIONS, spans: pd.DataFrame | None = None) -> dict:
    """Boundaries as timestamps. A boundary is moved to the nearest instant not inside any event."""
    ts = df.ts.drop_duplicates().sort_values().reset_index(drop=True)
    spans = event_spans(df) if spans is None else spans
    bounds = []
    cum = 0.0
    for f in fractions[:-1]:
        cum += f
        b = ts.iloc[int(len(ts) * cum)]
        # move out of any event that contains b (to just after the latest overlapping end)
        for _ in range(100):
            hit = spans[(spans.start < b) & (spans.end >= b)]
            if hit.empty:
                break
            b = hit.end.max() + pd.Timedelta(minutes=5)
        bounds.append(b)
    return {"train_end": bounds[0], "val_end": bounds[1], "start": ts.iloc[0], "end": ts.iloc[-1]}


def assign_split(ts: pd.Series, sp: dict) -> pd.Series:
    out = pd.Series("test", index=ts.index)
    out[ts < sp["val_end"]] = "val"
    out[ts < sp["train_end"]] = "train"
    return out


def check_no_straddle(df: pd.DataFrame, sp: dict, spans: pd.DataFrame | None = None) -> bool:
    spans = event_spans(df) if spans is None else spans
    for b in (sp["train_end"], sp["val_end"]):
        if ((spans.start < b) & (spans.end >= b)).any():
            return False
    return True


def save_splits(sp: dict, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({k: str(v) for k, v in sp.items()}, indent=2), encoding="utf-8")


def load_splits(path: Path) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return {k: pd.Timestamp(v) for k, v in d.items()}
