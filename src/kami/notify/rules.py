"""When an alert event becomes a message (docs/notifications.md). Pure logic: the caller passes the time.

Trigger   an alert episode OPENS with priority High or Critical, or an open episode ESCALATES to High or Critical
          (to a higher priority than the one already notified for that episode).
Limits    at most one message per node per `cooldown_s` (10 minutes of wall-clock time), at most `hourly_cap`
          messages in any 60 minutes overall, at most `max_total` messages in total (lifetime budget).
No repeat an episode is never notified twice at the same priority; a change of category alone, a de-escalation and the
          closing of an episode send nothing.
A trigger that a limit holds back is counted as suppressed and is not marked as notified, so a later change of the same
episode can still be sent once the limit allows it.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

PRIORITIES = ("Low", "Medium", "High", "Critical")
MIN_RANK = PRIORITIES.index("High")
COOLDOWN_S = 600.0
HOURLY_CAP = 30
HOUR_S = 3600.0


@dataclass(frozen=True)
class Decision:
    send: bool
    reason: str  # send: 'opened' | 'escalated'; no send: 'not_triggered' | 'cooldown' | 'hourly_cap' | 'budget'

    @property
    def suppressed(self) -> bool:
        return not self.send and self.reason != "not_triggered"


class TriggerRule:
    def __init__(self, cooldown_s: float = COOLDOWN_S, hourly_cap: int = HOURLY_CAP, max_total: int = 80, used_total: int = 0):
        self.cooldown_s, self.hourly_cap, self.max_total = float(cooldown_s), int(hourly_cap), int(max_total)
        self.used_total = int(used_total)  # messages already spent from the lifetime budget
        self._notified: dict[tuple, int] = {}  # episode -> highest priority rank already notified
        self._seen: set[tuple] = set()  # episodes for which an earlier event was seen
        self._last_node: dict[str, float] = {}
        self._recent: deque[float] = deque()

    @staticmethod
    def _key(event: dict) -> tuple:
        return (event["node_id"], event["id"])

    def sent_last_hour(self, now: float) -> int:
        while self._recent and now - self._recent[0] >= HOUR_S:
            self._recent.popleft()
        return len(self._recent)

    @property
    def budget_remaining(self) -> int:
        return max(self.max_total - self.used_total, 0)

    def evaluate(self, event: dict, now: float) -> Decision:
        """Decide for one alert event of the live processor. Changes nothing except forgetting closed episodes."""
        key = self._key(event)
        if event.get("status") == "closed":
            self._notified.pop(key, None)
            self._seen.discard(key)
            return Decision(False, "not_triggered")
        first = key not in self._seen
        self._seen.add(key)
        rank = PRIORITIES.index(event["priority"])
        if rank < MIN_RANK or rank <= self._notified.get(key, -1):
            return Decision(False, "not_triggered")
        if self.budget_remaining <= 0:
            return Decision(False, "budget")
        last = self._last_node.get(event["node_id"])
        if last is not None and now - last < self.cooldown_s:
            return Decision(False, "cooldown")
        if self.sent_last_hour(now) >= self.hourly_cap:
            return Decision(False, "hourly_cap")
        return Decision(True, "opened" if first else "escalated")

    def commit(self, event: dict, now: float) -> None:
        """Record that a message for this event was handed over for sending."""
        self._notified[self._key(event)] = PRIORITIES.index(event["priority"])
        self._last_node[event["node_id"]] = now
        self._recent.append(now)
        self.used_total += 1
