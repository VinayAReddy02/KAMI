from __future__ import annotations

from .base import SIGNALS, Store, validate_reading
from .sqlite_store import SqliteStore


def make_store(mode: str) -> Store:
    from .. import config

    if mode == "docker":
        from .timescale_store import TimescaleStore

        s = TimescaleStore(config.PG_DSN)
    else:
        s = SqliteStore(config.SQLITE_PATH)
    s.init()
    return s


__all__ = ["SIGNALS", "Store", "SqliteStore", "make_store", "validate_reading"]
