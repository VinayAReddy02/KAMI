"""Start the demo for the browser tests, the screenshots and the accessibility check.

    python scripts/e2e_server.py --port 8210

Fallback mode, temporary store, replay from the usual fixed start. Alert messages are forced to dry run and this process
cannot reach Telegram at all: the settings loader is pointed at a file that does not exist (a filled-in .env is not
read), the alert-push settings are removed from the environment, the dry-run log goes to a temporary folder, and every
HTTP request from this process to another machine is refused. Started by frontend/playwright.config.ts.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8210)
    ap.add_argument("--speed", type=float, default=1200.0)  # one of the speeds offered in the dashboard
    a = ap.parse_args()
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        print("frontend/dist is missing: run `npm run build` in frontend/ first", flush=True)
        return 1
    from kami.notify.lock import lock_to_dry_run

    lock_to_dry_run()
    from kami.live.launch import launch

    h = launch(speed=a.speed, port=a.port, mode="fallback", temp_store=True)  # notifications: forced dry run (the default)
    mode = h.stack.extras["notifications"].status()["mode"]
    if mode != "dry_run":  # cannot happen with the lock above; never continue if it does
        h.stop()
        print(f"refusing to run: alert push is in {mode} mode", flush=True)
        return 1
    print(f"KAMI test server on {h.url} (alerts: dry run)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        h.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
