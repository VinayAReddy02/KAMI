"""Start KAMI: virtual nodes -> bus -> worker -> processor -> API + dashboard, in one process.

    python scripts/run_demo.py                 # dashboard at http://127.0.0.1:8000 (builds nothing; see README)
    python scripts/run_demo.py --speed 1200    # faster replay
    python scripts/run_demo.py --check         # smoke test (Step 7)
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Use the project's virtual environment if this was started with another Python.
_venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
if _venv_py.is_file() and Path(sys.executable).resolve() != _venv_py.resolve():
    import subprocess

    raise SystemExit(subprocess.call([str(_venv_py), str(Path(__file__).resolve()), *sys.argv[1:]]))

from kami import config  # noqa: E402
from kami.live.launch import launch  # noqa: E402


def smoke(speed: float) -> int:
    import httpx

    h = launch(speed=max(speed, 3000), port=8190, mode="fallback", temp_store=True)
    ok = True
    try:
        c = httpx.Client(base_url=h.url, timeout=10)
        time.sleep(6)
        checks = {
            "health ok": c.get("/health").json()["status"] == "ok",
            "8 nodes in /network": len(c.get("/network").json()["nodes"]) == 8,
            "all nodes assessed": all(n["latest"] for n in c.get("/network").json()["nodes"]),
            "readings stored": c.get("/health").json()["readings"] > 100,
            "inject accepted": c.post("/demo/inject", json={"type": "infra_burst", "node": "node-2"}).status_code == 200,
            "bad inject rejected": c.post("/demo/inject", json={"type": "nope", "node": "node-2"}).status_code == 422,
        }
        for k, v in checks.items():
            print(("PASS " if v else "FAIL ") + k)
            ok &= v
    finally:
        h.stop()
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=600.0, help="replay speed-up vs real time (default 600 = 0.5 s per 5-min step)")
    ap.add_argument("--port", type=int, default=config.API_PORT)
    ap.add_argument("--check", action="store_true", help="run a short smoke test and exit")
    a = ap.parse_args()
    if a.check:
        return smoke(a.speed)
    h = launch(speed=a.speed, port=a.port, notifications="auto")  # WhatsApp only if enabled in .env (docs/notifications.md)
    dist = ROOT / "frontend" / "dist"
    print(f"KAMI running in {h.stack.mode} mode. API: {h.url}  (docs: {h.url}/docs)")
    print(f"Dashboard: {h.url}/" if dist.is_dir() else "Frontend not built: run `npm run build` in frontend/ (or `npm run dev` for port 5173).")
    st = h.stack.extras["notifications"].status()
    print("Alerts: " + ("WhatsApp on" if st["mode"] == "twilio" else "dry run") + f" ({st['detail']}; {st['budget_remaining']} messages left in the budget)")
    print("Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        h.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
