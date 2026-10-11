"""Outbound alert push (WhatsApp through Twilio, dry run by default). See docs/notifications.md."""
from __future__ import annotations

import logging

from .base import Notifier, SendOutcome
from .dryrun import DryRunNotifier
from .manager import NotificationManager, load_used
from .message import PREFIX, format_message
from .rules import Decision, TriggerRule
from .settings import Settings, load_settings, notify_dir
from .twilio import TwilioWhatsAppNotifier

log = logging.getLogger("kami.notify")
__all__ = ["Decision", "DryRunNotifier", "NotificationManager", "Notifier", "PREFIX", "SendOutcome", "Settings", "TriggerRule",
           "TwilioWhatsAppNotifier", "build_manager", "format_message", "load_settings", "notify_dir"]


def build_manager(node_names: dict | None = None, force_dry_run: bool = False, env=None, transport=None, **kw) -> NotificationManager:
    """The Twilio notifier is used only when KAMI_WHATSAPP_ENABLE=1 AND all four credentials are usable AND the caller
    did not force a dry run. In every other case messages go to the dry-run log, and the reason is logged (names only)."""
    settings = load_settings(env)
    directory = notify_dir(env)
    if settings.ready and not force_dry_run:
        state = directory / "state.json"
        used, problem = load_used(state, settings.max_total)
        mgr = NotificationManager(TwilioWhatsAppNotifier(settings, transport=transport),
                                  TriggerRule(max_total=settings.max_total, used_total=used), node_names, settings.describe(), state, **kw)
        if problem:
            mgr.last_problem = problem
            log.warning(problem)
        log.warning("Alerts: WhatsApp on (%d of %d messages left in the lifetime budget)", mgr.rule.budget_remaining, settings.max_total)
        return mgr
    detail = "dry run: forced for this run (checks and tests never send)" if force_dry_run else settings.describe()
    (log.warning if settings.enable_requested and not force_dry_run else log.info)("Alerts: %s", detail)
    return NotificationManager(DryRunNotifier(directory), TriggerRule(max_total=settings.max_total), node_names, detail, None, **kw)
