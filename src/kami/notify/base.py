"""Notifier interface: one outbound alert message at a time. Outbound only (no inbound messages, no webhook)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SendOutcome:
    """Result of one attempt. kind: 'sent' (accepted), 'retry' (temporary failure, may be tried again),
    'failed' (rejected, do not retry) or 'suppressed' (not deliverable right now by policy, do not retry)."""

    kind: str
    http_status: int | None = None
    error_code: int | None = None
    reason: str = ""
    sid: str | None = None


class Notifier(ABC):
    mode = "base"

    @abstractmethod
    def send(self, text: str, alert: dict) -> SendOutcome:
        """Send one message. Must not raise for network or service errors: return an outcome instead."""

    def check(self, sid: str) -> SendOutcome | None:
        """Optional later look at a message that was accepted (None = nothing to report)."""
        return None
