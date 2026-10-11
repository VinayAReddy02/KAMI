"""Send ONE clearly labelled test alert through the alert push.

    python scripts/send_test_alert.py

A WhatsApp message is sent only when KAMI_WHATSAPP_ENABLE=1 and all four credentials are set in .env
(docs/notifications.md). In every other case nothing leaves this machine: the message is written to the dry-run log.
A real send counts against the lifetime budget (WHATSAPP_MAX_TOTAL). No credential or number is printed.
"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(env=None, transport=None, out=print, check_delay: float = 15.0) -> int:
    from kami.notify import build_manager
    from kami.notify.settings import notify_dir

    mgr = build_manager({"test": "TEST (no real node)"}, env=env, transport=transport, check_delay=check_delay)
    now = datetime.now().isoformat(timespec="seconds")
    event = {"id": 0, "node_id": "test", "category": "TEST", "priority": "High", "max_priority": "High", "start_ts": now,
             "last_ts": now, "end_ts": None, "status": "active", "confidence": None,
             "explanation": "TEST MESSAGE from scripts/send_test_alert.py. This is not an alert: no sensor data and no model produced it."}
    try:
        mgr.on_event("alert", event)
        idle = mgr.wait_idle(timeout=check_delay + 45)
        s = mgr.status()
    finally:
        mgr.stop()
    if s["mode"] == "dry_run":
        out(f"Dry run, nothing was sent ({s['detail']}).")
        out(f"The test message was written to {notify_dir(env) / 'dryrun_log.jsonl'}" if s["sent"] else f"Not written: {s['last_problem']}")
        out("To send it to WhatsApp, follow docs/notifications.md (fill .env, set KAMI_WHATSAPP_ENABLE=1).")
        return 0 if s["sent"] == 1 else 1
    if not idle:
        out("Still waiting for Twilio after the timeout; check the phone and try again later.")
        return 1
    if s["sent"] == 1:
        out(f"Test message accepted by Twilio for WhatsApp delivery. {s['budget_remaining']} of {s['limits']['max_total']} messages left in the budget.")
        return 0
    out(f"Not sent: {s['last_problem'] or 'held back (' + ', '.join(s['suppressed_by']) + ')'}")
    out(f"{s['budget_remaining']} of {s['limits']['max_total']} messages left in the budget.")
    return 1


if __name__ == "__main__":
    # Use the project's virtual environment if this was started with another Python.
    _venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if _venv_py.is_file() and Path(sys.executable).resolve() != _venv_py.resolve():
        import subprocess

        raise SystemExit(subprocess.call([str(_venv_py), str(Path(__file__).resolve()), *sys.argv[1:]]))
    raise SystemExit(main())
