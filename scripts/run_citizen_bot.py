"""Run only the citizen bot (no sensor replay, no dashboard).

    python scripts/run_citizen_bot.py

The bot answers on Telegram only when KAMI_CITIZEN_ENABLE=1 and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in
.env (docs/citizen.md). It answers only the allowed chats. Without the sensor pipeline there is no live network state:
the schedule uses today's date and the time of this computer, no ward is marked as "possibly delayed", and a ward's
sensor status is reported as not available. Tickets are stored in data/processed/citizen_bot.sqlite.
To have the live state and the dashboard as well, start scripts/run_demo.py instead. Stop with Ctrl+C.
The token and chat ids are never printed.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    import logging

    from kami import config
    from kami.citizen.service import build_citizen
    from kami.runtime import Stack
    from kami.store import SqliteStore

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    store = SqliteStore(config.SQLITE_PATH.with_name("citizen_bot.sqlite"))
    store.init()
    stack = Stack.create(mode="fallback", store=store)
    svc = build_citizen(stack, None, allow_inbound=True)
    if not svc.enabled:
        print(f"Citizen bot: off ({svc.detail}). See docs/citizen.md.")
        return 1
    svc.start()
    print("Citizen bot: on. The speech models are loading in the background; text questions work at once. Ctrl+C to stop.")
    try:
        while svc.poller.state == "polling":
            time.sleep(1)
        print(f"Citizen bot stopped ({svc.poller.state}).")
        return 1
    except KeyboardInterrupt:
        svc.stop()
        return 0


if __name__ == "__main__":
    # Use the project's virtual environment if this was started with another Python.
    _venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if _venv_py.is_file() and Path(sys.executable).resolve() != _venv_py.resolve():
        import subprocess

        raise SystemExit(subprocess.call([str(_venv_py), str(Path(__file__).resolve()), *sys.argv[1:]]))
    raise SystemExit(main())
