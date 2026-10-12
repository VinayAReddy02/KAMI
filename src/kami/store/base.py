"""Storage interface. Two backends: SQLite (fallback) and TimescaleDB."""
from __future__ import annotations

from abc import ABC, abstractmethod

SIGNALS = ("flow", "pressure", "turbidity", "tds")


class Store(ABC):
    @abstractmethod
    def init(self) -> None: ...

    @abstractmethod
    def write_reading(self, r: dict) -> None: ...

    @abstractmethod
    def read_readings(self, node: str | None = None, since: str | None = None, limit: int = 1000) -> list[dict]: ...

    @abstractmethod
    def nodes(self) -> list[dict]: ...

    @abstractmethod
    def count(self, node: str | None = None) -> int: ...

    @abstractmethod
    def write_assessment(self, a: dict) -> None: ...

    @abstractmethod
    def read_assessments(self, node: str | None = None, limit: int = 500) -> list[dict]: ...

    @abstractmethod
    def write_complaint(self, c: dict) -> int:
        """Store one citizen complaint ticket (Round 6) and return its id."""

    @abstractmethod
    def read_complaints(self, limit: int = 200) -> list[dict]:
        """Complaint tickets, newest first, each with its id."""

    @abstractmethod
    def clear(self) -> None:
        """Remove all readings, assessments and complaints (a demo run starts from an empty database)."""

    @abstractmethod
    def close(self) -> None: ...


def validate_reading(r: dict) -> dict:
    """Return a cleaned reading or raise ValueError."""
    if not isinstance(r, dict):
        raise ValueError("reading must be an object")
    node = r.get("node_id")
    ts = r.get("ts")
    if not isinstance(node, str) or not node:
        raise ValueError("node_id missing")
    if not isinstance(ts, str) or not ts:
        raise ValueError("ts missing")
    out = {"node_id": node, "ts": ts}
    for s in SIGNALS:
        v = r.get(s)
        if v is None:
            out[s] = None
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
            raise ValueError(f"{s} not numeric")
        out[s] = float(v)
    return out
