"""Loaders for the raw public datasets (Step 0). Return tidy DataFrames."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw"
USGS_STATIONS = ["01654000", "01646305", "01654500"]


def _battledim_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", decimal=",")
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    return df.set_index("Timestamp")


def load_battledim(year: int) -> dict[str, pd.DataFrame]:
    """Returns {'pressure','flow','leak'} wide frames indexed by timestamp (5 min)."""
    d = RAW / "battledim"
    return {
        "pressure": _battledim_csv(d / f"{year}_SCADA_Pressures.csv"),
        "flow": _battledim_csv(d / f"{year}_SCADA_Flows.csv"),
        "leak": _battledim_csv(d / f"{year}_Leakages.csv"),
    }


def load_usgs(station: str) -> pd.DataFrame:
    """Returns ts (UTC-naive local EST), turbidity (FNU), conductance (uS/cm)."""
    path = RAW / "usgs" / f"iv_{station}.rdb"
    df = pd.read_csv(path, sep="\t", comment="#", dtype=str)
    df = df[df["datetime"].str.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", na=False)]
    cond = [c for c in df.columns if c.endswith("_00095")][0]
    turb = [c for c in df.columns if c.endswith("_63680")][0]
    out = pd.DataFrame({
        "ts": pd.to_datetime(df["datetime"], format="%Y-%m-%d %H:%M"),
        "turbidity": pd.to_numeric(df[turb], errors="coerce"),
        "conductance": pd.to_numeric(df[cond], errors="coerce"),
    })
    out["station"] = station
    return out
