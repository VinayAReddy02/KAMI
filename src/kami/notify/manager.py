"""Connects the alert lifecycle of the live processor to a notifier.

`on_event` is registered as a processor listener. It only applies the trigger rule and puts the message on a bounded
queue; a background thread does the sending, the retries (at most two, with backoff) and one later status check.
Nothing in here can raise into, or block, the processing loop. Log lines carry fixed sentences, the HTTP status and
Twilio's numeric error code only.
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
from .twilio import BAD_CREDENTIALS, NOT_JOINED, WINDOW_CLOSED

log = logging.getLogger("kami.notify")
STATE_KEY = "messages_handed_to_twilio"


def load_used(state_path: Path, max_total: int) -> tuple[int, str | None]:
    """Lifetime budget already spent (0 if there is no state file). An unreadable file counts as a spent budget."""
    if not Path(state_path).is_file():
        return 0, None
    try:
        return max(int(json.loads(Path(state_path).read_text(encoding="utf-8"))[STATE_KEY]), 0), None
    except (OSError, ValueError, KeyError, TypeError):
        return max_total, "message budget file is unreadable: sending is stopped (see docs/notifications.md)"


def _line(out: SendOutcome) -> str:
    extra = [f"HTTP {out.http_status}"] if out.http_status else []
    if out.error_code is not None and out.error_code >= 0:
        extra.append(f"Twilio error {out.error_code}")
    return out.reason + (f" ({', '.join(extra)})" if extra else "")


class NotificationManager:
    def __init__(self, notifier: Notifier, rule: TriggerRule | None = None, node_names: dict | None = None, detail: str = "",
                 state_path: Path | None = None, max_retries: int = 2, backoff: tuple = (2.0, 6.0), check_delay: float | None = 20.0,
                 hold_s: float = 600.0, queue_size: int = 200, clock=time.time, start: bool = True):
        self.notifier, self.rule = notifier, rule or TriggerRule()
        self.node_names, self.detail, self.state_path = node_names or {}, detail, state_path
        self.max_retries, self.backoff, self.check_delay, self.hold_s, self.clock = min(int(max_retries), 2), backoff, check_delay, hold_s, clock
        self.sent = self.suppressed = self.failed = 0
        self.suppressed_by: Counter = Counter()
        self.last_send_utc: str | None = None
        self.last_problem: str | None = None
        self._hold_until = 0.0
        self._checks: list[tuple[float, str]] = []
        self._q: queue.Queue = queue.Queue(maxsize=queue_size)
        self._lock = threading.Lock()
        self._stop = threading.Event()
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
                        self._save()
                if d.suppressed:
                    self.suppressed += 1
                    self.suppressed_by[d.reason] += 1
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
                self._run_checks()
            except Exception as e:  # keep the thread alive whatever a notifier does
                self._problem(f"notification worker error ({type(e).__name__})", count_failed=True)
            finally:
                if job is not None:
                    self._q.task_done()

    def _deliver(self, text: str, alert: dict) -> None:
        out = SendOutcome("failed", reason="not attempted")
        for attempt in range(self.max_retries + 1):
            if attempt:  # a retry is a new request: it spends budget too
                with self._lock:
                    if self.rule.budget_remaining <= 0:
                        out = SendOutcome("suppressed", reason="message budget reached during a retry")
                        break
                    self.rule.used_total += 1
                    self._save()
                self._stop.wait(self.backoff[min(attempt - 1, len(self.backoff) - 1)])
            try:
                out = self.notifier.send(text, alert)
            except Exception as e:
                out = SendOutcome("failed", reason=f"notifier error ({type(e).__name__})")
            if out.kind != "retry":
                break
        if out.kind == "retry":
            out = SendOutcome("failed", out.http_status, out.error_code, f"{out.reason}; gave up after {self.max_retries + 1} attempts")
        self._record(out)

    def _record(self, out: SendOutcome, revised: bool = False) -> None:
        with self._lock:
            if revised:
                self.sent -= 1
            if out.kind == "sent":
                self.sent += 1
                self.last_send_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if out.sid and self.check_delay is not None:
                    self._checks.append((self.clock() + self.check_delay, out.sid))
                return
            if out.kind == "suppressed":
                self.suppressed += 1
                self.suppressed_by["window_closed" if out.error_code == WINDOW_CLOSED else "budget"] += 1
            else:
                self.failed += 1
            if out.error_code in (WINDOW_CLOSED, NOT_JOINED, BAD_CREDENTIALS) or out.http_status in (401, 403):
                self._hold_until = self.clock() + self.hold_s  # the next messages would fail the same way: do not spend on them
        self._problem("WhatsApp alert not sent: " + _line(out))

    def _run_checks(self) -> None:
        with self._lock:
            now = self.clock()
            due = [c for c in self._checks if c[0] <= now]
            self._checks = [c for c in self._checks if c[0] > now]
        for _, sid in due:
            try:
                out = self.notifier.check(sid)
            except Exception:
                out = None
            if out is not None and out.kind != "sent":
                self._record(out, revised=True)

    # ----------------------------------------------------------- helpers
    def _problem(self, line: str, count_failed: bool = False) -> None:
        with self._lock:
            self.last_problem = line
            if count_failed:
                self.failed += 1
        log.warning(line)

    def _save(self) -> None:
        """Persist the lifetime budget (Twilio mode only). Called with the lock held."""
        if self.state_path is None:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({STATE_KEY: self.rule.used_total,
                                       "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError:
            self.rule.used_total = self.rule.max_total  # the budget cannot be kept across runs: stop sending
            self.last_problem = "could not save the message budget: sending is stopped"
            log.warning(self.last_problem)

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """True once the queue is empty and no status check is pending (used by tests and the test-alert script)."""
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                idle = self._q.unfinished_tasks == 0 and not self._checks
            if idle:
                return True
            time.sleep(0.02)
        return False

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        """For GET /notifications/status. No credential, number or URL is stored in this object."""
        with self._lock:
            return {"mode": self.notifier.mode, "detail": self.detail, "sent": self.sent, "suppressed": self.suppressed,
                    "failed": self.failed, "suppressed_by": dict(self.suppressed_by), "last_send_utc": self.last_send_utc,
                    "last_problem": self.last_problem, "queued": self._q.qsize(),
                    "messages_last_hour": self.rule.sent_last_hour(self.clock()),
                    "limits": {"min_priority": "High", "cooldown_seconds_per_node": self.rule.cooldown_s,
                               "max_per_hour": self.rule.hourly_cap, "max_total": self.rule.max_total},
                    "budget_used": self.rule.used_total, "budget_remaining": self.rule.budget_remaining,
                    "budget_scope": "lifetime, kept in results/notifications/state.json" if self.state_path else "this run only (dry run)"}
