"""Connects the alert lifecycle of the live processor to a notifier.

`on_event` is registered as a processor listener. It only applies the trigger rule and puts the message on a bounded
queue; a background thread does the sending, the retries and the state file. Nothing in here can raise into, or block,
the processing loop. Log lines carry fixed sentences, the HTTP status and the service's numeric error code only.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .base import Notifier, SendOutcome
from .message import format_message
from .rules import Decision, TriggerRule

log = logging.getLogger("kami.notify")
MAX_RETRIES = 2  # network errors and server errors
MAX_WAIT_S = 60.0  # longest single wait after a "too many requests" answer


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _line(out: SendOutcome) -> str:
    extra = [f"HTTP {out.http_status}"] if out.http_status else []
    if out.error_code is not None:
        extra.append(f"error_code {out.error_code}")
    return out.reason + (f" ({', '.join(extra)})" if extra else "")


class NotificationManager:
    def __init__(self, notifier: Notifier, rule: TriggerRule | None = None, node_names: dict | None = None, detail: str = "",
                 state_path: Path | None = None, backoff: tuple = (2.0, 6.0), hold_s: float = 600.0, queue_size: int = 200,
                 clock=time.time, sleep=None, start: bool = True):
        self.notifier, self.rule = notifier, rule or TriggerRule()
        self.node_names, self.detail, self.state_path = node_names or {}, detail, state_path
        self.backoff, self.hold_s, self.clock = backoff, hold_s, clock
        self.sent = self.suppressed = self.failed = 0
        self.suppressed_by: Counter = Counter()
        self.last_send_utc: str | None = None
        self.last_problem: str | None = None
        self.started_utc = _utc()
        self._hold_until = 0.0
        self._dirty = state_path is not None  # write the state file once at start
        self._q: queue.Queue = queue.Queue(maxsize=queue_size)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sleep = sleep or self._stop.wait
        self._thread = threading.Thread(target=self._run, name="kami-notify", daemon=True)
        if start:
            self._thread.start()

    # ----------------------------------------------------------- called from the processing loop
    def on_event(self, kind: str, data: dict) -> None:
        if kind != "alert":
            return
        try:
            now = self.clock()
            with self._lock:
                d = self.rule.evaluate(data, now)
                if d.send and now < self._hold_until:
                    d = Decision(False, "on_hold")
                if d.send:
                    alert = {**data, "ts": data.get("last_ts")}
                    text = format_message(alert, self.node_names.get(data["node_id"]))
                    try:
                        self._q.put_nowait((text, alert))
                    except queue.Full:
                        d = Decision(False, "queue_full")
                    else:
                        self.rule.commit(data, now)
                if d.suppressed:
                    self.suppressed += 1
                    self.suppressed_by[d.reason] += 1
                    self._dirty = True
            if d.suppressed:
                log.info("alert message held back (%s) for %s", d.reason, data.get("node_id"))
        except Exception as e:  # the processing loop must never see an error from here
            self._problem(f"notification error ({type(e).__name__})", count_failed=True)

    # ----------------------------------------------------------- background thread
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._q.get(timeout=0.2)
            except queue.Empty:
                job = None
            try:
                if job is not None:
                    self._deliver(*job)
                self._save()
            except Exception as e:  # keep the thread alive whatever a notifier does
                self._problem(f"notification worker error ({type(e).__name__})", count_failed=True)
            finally:
                if job is not None:
                    self._q.task_done()

    def _deliver(self, text: str, alert: dict) -> None:
        retries, waited, attempts = 0, False, 0
        while True:
            attempts += 1
            try:
                out = self.notifier.send(text, alert)
            except Exception as e:
                out = SendOutcome("failed", reason=f"notifier error ({type(e).__name__})")
            if out.kind == "retry" and retries < MAX_RETRIES and not self._stop.is_set():
                self._sleep(self.backoff[min(retries, len(self.backoff) - 1)])
                retries += 1
                continue
            if out.kind == "wait" and not waited and not self._stop.is_set():  # rate limited: wait once, then one more attempt
                waited = True
                self._sleep(min(max(out.retry_after or 1.0, 0.0), MAX_WAIT_S))
                continue
            break
        if out.kind in ("retry", "wait"):
            out = SendOutcome("failed", out.http_status, out.error_code, f"{out.reason}; gave up after {attempts} attempts")
        self._record(out)

    def _record(self, out: SendOutcome) -> None:
        with self._lock:
            self._dirty = True
            if out.kind == "sent":
                self.sent += 1
                self.last_send_utc = _utc()
                return
            self.failed += 1
            if out.pause:  # the next messages would fail the same way: do not keep asking the service
                self._hold_until = self.clock() + self.hold_s
        self._problem("Alert message not sent: " + _line(out))

    # ----------------------------------------------------------- helpers
    def _problem(self, line: str, count_failed: bool = False) -> None:
        with self._lock:
            self.last_problem = line
            self._dirty = True
            if count_failed:
                self.failed += 1
        log.warning(line)

    def _counts(self) -> dict:
        return {"mode": self.notifier.mode, "sent": self.sent, "suppressed": self.suppressed, "failed": self.failed,
                "suppressed_by": dict(self.suppressed_by), "last_send_utc": self.last_send_utc, "last_problem": self.last_problem}

    def _save(self) -> None:
        """Write the state file (counts and times only) when something changed. Runs in the background thread."""
        with self._lock:
            if not self._dirty or self.state_path is None:
                self._dirty = False
                return
            self._dirty = False
            state = {**self._counts(), "started_utc": self.started_utc, "updated_utc": _utc()}
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError:
            log.warning("could not write the notification state file")

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """True once the queue is empty and the state file is up to date (used by tests and the test-alert script)."""
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                idle = self._q.unfinished_tasks == 0 and not self._dirty
            if idle:
                return True
            time.sleep(0.02)
        return False

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        """For GET /notifications/status. No token, chat id or URL is stored in this object."""
        with self._lock:
            return {**self._counts(), "detail": self.detail, "queued": self._q.qsize(),
                    "messages_last_hour": self.rule.sent_last_hour(self.clock()),
                    "limits": {"min_priority": "High", "cooldown_seconds_per_node": self.rule.cooldown_s,
                               "max_per_hour": self.rule.hourly_cap}}
