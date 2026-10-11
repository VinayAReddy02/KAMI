"""Outbound alert push (Telegram bot, dry run by default). See docs/notifications.md."""
from __future__ import annotations

import logging

from .base import Notifier, SendOutcome
from .dryrun import DryRunNotifier
from .manager import NotificationManager
from .message import PREFIX, format_message
from .rules import Decision, TriggerRule
from .settings import Settings, load_settings, notify_dir
from .telegram import TelegramNotifier

log = logging.getLogger("kami.notify")
__all__ = ["Decision", "DryRunNotifier", "NotificationManager", "Notifier", "PREFIX", "SendOutcome", "Settings", "TelegramNotifier",
           "TriggerRule", "build_manager", "format_message", "load_settings", "notify_dir"]


def build_manager(node_names: dict | None = None, allow_real_sending: bool = False, env=None, transport=None, **kw) -> NotificationManager:
    """Telegram is used only when KAMI_TELEGRAM_ENABLE=1 AND the bot token and the chat id are usable AND the caller
    allows real sending (scripts/run_demo.py and scripts/send_test_alert.py do; checks, tests and launch() do not).
    In every other case messages go to the dry-run log, and the reason is logged (setting names only)."""
    settings = load_settings(env)
    state = notify_dir(env) / "state.json"
    if settings.ready and allow_real_sending:
        log.warning("Alerts: Telegram on")
        return NotificationManager(TelegramNotifier(settings, transport=transport), TriggerRule(), node_names, settings.describe(), state, **kw)
    detail = settings.describe() if allow_real_sending else "forced for this run (checks and tests never send)"
    (log.warning if settings.enable_requested and allow_real_sending else log.info)("Alerts: dry run (%s)", detail)
    return NotificationManager(DryRunNotifier(notify_dir(env)), TriggerRule(), node_names, detail, state, **kw)
