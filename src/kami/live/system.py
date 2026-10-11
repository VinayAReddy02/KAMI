"""Assembles the live system: virtual nodes -> bus -> ingest worker -> streaming processor -> API."""
from __future__ import annotations

import json
from dataclasses import dataclass

from .. import config
from ..runtime import Stack
from ..simulator.inject import Injector
from ..simulator.node import NodeFleet, build_node_frames, find_clean_start
from .processor import BUF, LiveProcessor

NODES_CONFIG = config.ROOT / "config" / "nodes.json"


def load_nodes_config() -> dict:
    return json.loads(NODES_CONFIG.read_text(encoding="utf-8"))


@dataclass
class LiveSystem:
    processor: LiveProcessor
    injector: Injector
    fleet: NodeFleet
    frames: dict
    start: int


def build_live(stack: Stack, speed: float = 600.0, n_nodes: int = 8, start: int | None = None,
               max_steps: int | None = None, notifications: str = "dry_run") -> LiveSystem:
    """`notifications`: "dry_run" (default: alert messages only go to the dry-run log, whatever .env says) or "auto"
    (the Telegram bot is used if it is enabled and configured in .env, see docs/notifications.md)."""
    frames = build_node_frames(n_nodes)
    start = find_clean_start(frames) if start is None else start
    proc = LiveProcessor(stack.store)
    for nid, f in frames.items():
        proc.prime(nid, f.iloc[start - BUF:start])
    inj = Injector(frames)
    fleet = NodeFleet(stack.bus, frames, speed, start=start, max_steps=max_steps, modifier=inj.modifier)
    stack.worker.listeners.append(proc.on_reading)

    def push(kind: str, data: dict) -> None:
        hub = stack.extras.get("hub")
        if hub is not None:
            hub.push({"type": kind, "data": data})

    proc.listeners.append(push)
    from ..notify import build_manager  # outbound alert push; listens to alert events, never blocks the processor

    names = {n["id"]: n["name"] for n in load_nodes_config()["nodes"]}
    stack.extras["notifications"] = build_manager(names, allow_real_sending=notifications == "auto")
    proc.listeners.append(stack.extras["notifications"].on_event)
    live = LiveSystem(proc, inj, fleet, frames, start)
    stack.extras["live"] = live
    return live
