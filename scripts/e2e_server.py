"""Start the demo for the browser tests, the screenshots and the accessibility check.

    python scripts/e2e_server.py --port 8210

Fallback mode, temporary store, replay from the usual fixed start. Alert messages are forced to dry run and this process
cannot reach Telegram at all: the settings loader is pointed at a file that does not exist (a filled-in .env is not
read), the alert-push settings are removed from the environment, the dry-run log goes to a temporary folder, and every
HTTP request from this process to another machine is refused. Started by frontend/playwright.config.ts.
"""
import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def seed_test_ticket(tickets) -> None:
    """One complaint ticket made from a generated picture (not a citizen photo), about 1.2 km from node-5, clear of the node labels."""
    import io

    from PIL import Image, ImageDraw

    im = Image.new("RGB", (640, 480), (70, 90, 110))
    d = ImageDraw.Draw(im)
    d.rectangle((60, 200, 580, 260), fill=(150, 150, 150))
    d.text((70, 60), "GENERATED TEST PICTURE - not a citizen photo", fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "JPEG")
    assert tickets.add_photo("e2e", buf.getvalue(), source="test").kind == "need_location"
    assert tickets.add_location("e2e", 12.925, 79.121, source="test").kind == "ticket"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8210)
    ap.add_argument("--speed", type=float, default=1200.0)  # one of the speeds offered in the dashboard
    ap.add_argument("--mode", choices=["fallback", "docker"], default="fallback", help="docker: MQTT + TimescaleDB, three processes (the stack must be up)")
    a = ap.parse_args()
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        print("frontend/dist is missing: run `npm run build` in frontend/ first", flush=True)
        return 1
    from kami.notify.lock import lock_to_dry_run

    notify = lock_to_dry_run()
    os.environ["KAMI_CITIZEN_DIR"] = str(notify.parent / "citizen")  # uploads of this run: a temporary folder
    from kami.live.launch import launch

    if a.mode == "docker":
        import httpx

        from kami import config
        from kami.citizen.settings import work_dir
        from kami.citizen.tickets import TicketService
        from kami.live.launch import launch_docker
        from kami.live.system import load_nodes_config
        from kami.store.timescale_store import TimescaleStore

        h = launch_docker(speed=a.speed, port=a.port, lock=True)  # the three processes inherit this locked environment; alerts forced to dry run
        mode = httpx.get(h.url + "/notifications/status", timeout=10).json()["mode"]
        store = TimescaleStore(config.PG_DSN)
        tickets = TicketService(store, load_nodes_config()["nodes"], work_dir() / "uploads")  # the API process serves the same folder
    else:
        h = launch(speed=a.speed, port=a.port, mode="fallback", temp_store=True)  # notifications: forced dry run (the default)
        mode = h.stack.extras["notifications"].status()["mode"]
        tickets = h.stack.extras["citizen"].tickets
    if mode != "dry_run":  # cannot happen with the lock above; never continue if it does
        h.stop()
        print(f"refusing to run: alert push is in {mode} mode", flush=True)
        return 1
    seed_test_ticket(tickets)
    print(f"KAMI test server on {h.url} ({a.mode} mode; alerts: dry run, citizen bot: off, 1 generated test ticket)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        h.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
