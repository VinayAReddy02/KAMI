"""Guarded split access: the test split is only reachable through `final_evaluation`.

Every test access is recorded (counter + key hash of model id and dataset) in results/test_eval_log.json,
so Step 5 can show each design was evaluated on test exactly once.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LOG = ROOT / "results" / "test_eval_log.json"
_active = {"on": False}


class TestSplitLocked(PermissionError):
    __test__ = False


def _read_log(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


@contextlib.contextmanager
def final_evaluation(model_id: str, dataset: str, log_path: Path = LOG):
    """Open test access once for (model_id, dataset). A second call for the same pair raises."""
    key = hashlib.sha256(f"{model_id}|{dataset}".encode()).hexdigest()[:16]
    log = _read_log(log_path)
    if any(r["key"] == key for r in log):
        raise TestSplitLocked(f"test split already evaluated for {model_id} on {dataset}")
    log.append({"key": key, "model": model_id, "dataset": dataset, "count": len(log) + 1})
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    _active["on"] = True
    try:
        yield
    finally:
        _active["on"] = False


class SplitData:
    """Holds a frame with a `split` column; `.test()` only works inside `final_evaluation`."""

    def __init__(self, df: pd.DataFrame):
        self._df = df

    def train(self) -> pd.DataFrame:
        return self._df[self._df.split == "train"]

    def val(self) -> pd.DataFrame:
        return self._df[self._df.split == "val"]

    def test(self) -> pd.DataFrame:
        if not _active["on"]:
            raise TestSplitLocked("test split is only available inside final_evaluation()")
        return self._df[self._df.split == "test"]
