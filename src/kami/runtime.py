"""Wires bus, store, ingest worker (and later the processor) into one object."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config
from .ingest.bus import Bus, make_bus
from .ingest.worker import IngestWorker
from .store import Store, make_store


@dataclass
class Stack:
    mode: str
    bus: Bus
    store: Store
    worker: IngestWorker
    extras: dict = field(default_factory=dict)

    @classmethod
    def create(cls, mode: str | None = None, store: Store | None = None, bus: Bus | None = None) -> "Stack":
        mode = mode or config.resolve_mode()
        bus = bus or make_bus(mode)
        store = store or make_store(mode)
        store.init()  # idempotent
        worker = IngestWorker(bus, store)
        worker.start()
        return cls(mode, bus, store, worker)

    def close(self):
        self.bus.close()
        self.store.close()
