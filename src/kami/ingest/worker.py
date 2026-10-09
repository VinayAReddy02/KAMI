"""Ingest worker: subscribe to node readings, validate, write to storage, notify listeners."""
from __future__ import annotations

import logging
from typing import Callable

from .. import config
from ..store import Store, validate_reading
from .bus import Bus

log = logging.getLogger("kami.ingest")


class IngestWorker:
    def __init__(self, bus: Bus, store: Store):
        self.bus, self.store = bus, store
        self.accepted = 0
        self.rejected = 0
        self.listeners: list[Callable[[dict], None]] = []

    def start(self) -> None:
        self.bus.subscribe(config.TOPIC_READINGS_ALL, self._on_message)

    def _on_message(self, topic: str, payload: dict) -> None:
        try:
            r = validate_reading(payload)
        except ValueError as e:
            self.rejected += 1
            log.warning("rejected reading on %s: %s", topic, e)
            return
        self.store.write_reading(r)
        self.accepted += 1
        for fn in self.listeners:
            try:
                fn(r)
            except Exception:  # a listener must never break ingestion
                log.exception("listener failed")
