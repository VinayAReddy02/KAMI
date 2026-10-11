"""Send ONE clearly labelled test alert through the alert push.

    python scripts/send_test_alert.py

A Telegram message is sent only when KAMI_TELEGRAM_ENABLE=1 and both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set
in .env (docs/notifications.md). In every other case nothing leaves this machine: the message is written to the
dry-run log. The token and the chat id are never printed.
"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(env=None, transport=None, out=print, **kw) -> int:
    from kami.notify import build_manager
    from kami.notify.settings import notify_dir

    mgr = build_manager({"test": "TEST (no real node)"}, allow_real_sending=True, env=env, transport=transport, **kw)
    now = datetime.now().isoformat(timespec="seconds")
    event = {"id": 0, "node_id": "test", "category": "TEST", "priority": "High", "max_priority": "High", "start_ts": now,
             "last_ts": now, "end_ts": None, "status": "active", "confidence": None,
             "explanation": "TEST MESSAGE from scripts/send_test_alert.py. This is not an alert: no sensor data and no model produced it."}
    try:
        mgr.on_event("alert", event)
        idle = mgr.wait_idle(timeout=120)
        s = mgr.status()
    finally:
        mgr.stop()
    if s["mode"] == "dry_run":
        out(f"Dry run, nothing was sent ({s['detail']}).")
        out(f"The test message was written to {notify_dir(env) / 'dryrun_log.jsonl'}" if s["sent"] else f"Not written: {s['last_problem']}")
        out("To send it to Telegram, follow docs/notifications.md (token and chat id in .env, KAMI_TELEGRAM_ENABLE=1).")
        return 0 if s["sent"] == 1 else 1
    if not idle:
        out("Still waiting for Telegram after the timeout; try again later.")
        return 1
    if s["sent"] == 1:
        out("Test message accepted by Telegram. Check the chat with the bot.")
        return 0
    out(f"Not sent. {s['last_problem'] or 'The message was held back.'}")
    return 1


if __name__ == "__main__":
    # Use the project's virtual environment if this was started with another Python.
    _venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if _venv_py.is_file() and Path(sys.executable).resolve() != _venv_py.resolve():
        import subprocess

        raise SystemExit(subprocess.call([str(_venv_py), str(Path(__file__).resolve()), *sys.argv[1:]]))
    raise SystemExit(main())
