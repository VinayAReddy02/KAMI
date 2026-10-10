"""Guarded split access: the test split is only reachable through `final_evaluation`.

Every test access is recorded (counter + key hash of model id and dataset) in results/test_eval_log.json,
so Step 5 can show each design was evaluated on test exactly once.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LOG = ROOT / "results" / "test_eval_log.json"
_active = {"on": False, "dataset": None}


class TestSplitLocked(PermissionError):
    __test__ = False


def _read_log(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


@contextlib.contextmanager
def final_evaluation(model_id: str, dataset: str, log_path: Path = LOG):
    """Open test access once for (model_id, dataset). A second call for the same pair raises."""
    from .data import LOCKED_LOGS  # lazy: avoids an import cycle

    if dataset in LOCKED_LOGS:
        # Held-out Round-2 sets: only through the designated log, and only once the frozen configuration exists
        # and still matches the files on disk.
        if Path(log_path).resolve() != LOCKED_LOGS[dataset].resolve():
            raise TestSplitLocked(f"{dataset} may only be opened with its designated log {LOCKED_LOGS[dataset].name}")
        from .freeze import verify

        try:
            verify()
        except (SystemExit, FileNotFoundError) as e:
            raise TestSplitLocked(f"{dataset} is locked until the frozen configuration verifies: {e}") from None
    key = hashlib.sha256(f"{model_id}|{dataset}".encode()).hexdigest()[:16]
    log = _read_log(log_path)
    if any(r["key"] == key for r in log):
        raise TestSplitLocked(f"test split already evaluated for {model_id} on {dataset}")
    log.append({"key": key, "model": model_id, "dataset": dataset, "count": len(log) + 1,
                "utc": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    _active["on"], _active["dataset"] = True, dataset
    try:
        yield
    finally:
        _active["on"], _active["dataset"] = False, None


def mark_completed(model_id: str, dataset: str, log_path: Path, **extra) -> None:
    """Record in the access log that the evaluation opened for (model_id, dataset) produced a saved result."""
    key = hashlib.sha256(f"{model_id}|{dataset}".encode()).hexdigest()[:16]
    log = _read_log(log_path)
    for r in log:
        if r["key"] == key:
            r["completed_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            r.update(extra)
    tmp = Path(str(log_path) + ".tmp")
    tmp.write_text(json.dumps(log, indent=2), encoding="utf-8")
    tmp.replace(log_path)


def is_logged(model_id: str, dataset: str, log_path: Path) -> bool:
    key = hashlib.sha256(f"{model_id}|{dataset}".encode()).hexdigest()[:16]
    return any(r["key"] == key for r in _read_log(log_path))


class SplitData:
    """Holds a frame with a `split` column; `.test()` only works inside `final_evaluation`."""

    def __init__(self, df: pd.DataFrame, dataset: str | None = None):
        self._df = df
        self.dataset = dataset or df.attrs.get("kami_dataset")

    def train(self) -> pd.DataFrame:
        return self._df[self._df.split == "train"]

    def val(self) -> pd.DataFrame:
        return self._df[self._df.split == "val"]

    def test(self) -> pd.DataFrame:
        if not _active["on"]:
            raise TestSplitLocked("test split is only available inside final_evaluation()")
        from .data import LOCKED_LOGS

        if self.dataset in LOCKED_LOGS and _active["dataset"] != self.dataset:
            raise TestSplitLocked(f"{self.dataset} test split can only be opened by final_evaluation for {self.dataset}")
        return self._df[self._df.split == "test"]
