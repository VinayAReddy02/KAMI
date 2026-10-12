"""Default notifier: nothing leaves the machine. Each message is appended to `<notify dir>/dryrun_log.jsonl`."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .base import Notifier, SendOutcome
from .settings import notify_dir

ALERT_KEYS = ("id", "node_id", "category", "priority", "max_priority", "confidence", "explanation", "start_ts", "ts", "status",
              "p_infra", "p_quality", "temporal")


class DryRunNotifier(Notifier):
    mode = "dry_run"

    def __init__(self, directory: Path | None = None):
        self.path = Path(directory or notify_dir()) / "dryrun_log.jsonl"
        self._lock = threading.Lock()

    def send(self, text: str, alert: dict) -> SendOutcome:
        entry = {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "mode": self.mode, "text": text,
                 "alert": {k: alert.get(k) for k in ALERT_KEYS}}
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
        except OSError:
            return SendOutcome("failed", reason="could not write the dry-run log file")
        return SendOutcome("sent")
