"""Notifier interface: one outbound alert message at a time. Outbound only (no inbound messages, no webhook, no polling)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class SendOutcome:
    """Result of one attempt.

    kind  'sent'    accepted
          'retry'   temporary failure (network error, server error): may be tried again, at most twice
          'wait'    rate limited: wait `retry_after` seconds once, then one more attempt
          'failed'  rejected: the same request cannot succeed, do not retry
    `reason` is one of the notifier's fixed sentences. It never contains a secret, a URL or text from the service."""

    kind: str
    http_status: int | None = None
    error_code: int | None = None
    reason: str = ""
    retry_after: float | None = None
    pause: bool = False  # the next messages would fail the same way (bad token, unknown chat): hold sending for a while


class Notifier(ABC):
    mode = "base"

    @abstractmethod
    def send(self, text: str, alert: dict) -> SendOutcome:
        """Send one message. Must not raise for network or service errors: return an outcome instead."""
