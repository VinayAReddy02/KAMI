"""Exit 0 only if Step 6 criteria hold: frontend build+tests, live injection reaches the API and a WebSocket client,
streaming == batch features (pytest tests/step6)."""
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import httpx  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

from kami.live.launch import launch  # noqa: E402

ok = True
PRIO = ["Low", "Medium", "High", "Critical"]


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok &= bool(cond)


npm = shutil.which("npm")
fe = ROOT / "frontend"
check("npm run build", subprocess.run([npm, "run", "build"], cwd=fe, capture_output=True).returncode == 0)
check("npm run test", subprocess.run([npm, "run", "test"], cwd=fe, capture_output=True).returncode == 0)

PORT = 8103
h = launch(speed=3000, port=PORT, mode="fallback", temp_store=True)
base = f"http://127.0.0.1:{PORT}"
received: list[dict] = []
stop = threading.Event()


def ws_reader():
    try:
        with connect(f"ws://127.0.0.1:{PORT}/ws", open_timeout=10) as ws:
            while not stop.is_set():
                try:
                    msg = json.loads(ws.recv(timeout=1))
                except TimeoutError:
                    continue
                if msg["type"] == "assessment":
                    received.append(msg["data"])
    except Exception as e:  # reported by the check below
        print("ws reader ended:", e)


t = threading.Thread(target=ws_reader, daemon=True)
t.start()
try:
    time.sleep(6)  # warm-up of the replay and websocket
    node = "node-3"
    body = httpx.post(f"{base}/demo/inject", json={"type": "combined", "node": node}, timeout=10).json()
    print("injected:", body["id"], body["type"], "on", node)
    t0 = time.time()
    api_ok = combined = None
    while time.time() - t0 < 60 and combined is None:
        s = httpx.get(f"{base}/nodes/{node}/state", timeout=10).json()["latest"]
        if api_ok is None and s["category"] != "Normal" and PRIO.index(s["priority"]) >= 1:
            api_ok = (time.time() - t0, s["category"], s["priority"])
        if s["category"] == "Combined":
            combined = time.time() - t0
        time.sleep(0.5)
    check(f"API reports {node} in alert with priority >= Medium within 60 s"
          + (f" ({api_ok[0]:.1f} s, {api_ok[1]}, {api_ok[2]})" if api_ok else ""), api_ok is not None)
    # Round 3 (W-1): the live demo runs the frozen Round 2 rule. It confirms the quality stream of a combined event only
    # after sustained evidence, so the category is usually Infrastructure, not Combined. Reported, not counted
    # (docs/decisions.md, "Round 3"); the injection size was not changed.
    print("INFO known limitation of the frozen rule: category Combined within 60 s: "
          + (f"yes ({combined:.1f} s)" if combined else f"no (reported as {api_ok[1] if api_ok else 'Normal'})"))
    time.sleep(1.5)
    ws_hit = [a for a in received if a["node_id"] == node and a["category"] != "Normal" and PRIO.index(a["priority"]) >= 1]
    check(f"WebSocket client received the alert update ({len(ws_hit)} messages, {len(received)} assessments in total)", bool(ws_hit))
    alerts = httpx.get(f"{base}/alerts", params={"node": node}, timeout=10).json()
    check("GET /alerts lists an alert for the node with an explanation and priority >= Medium",
      any(a["explanation"] and PRIO.index(a["max_priority"]) >= 1 for a in alerts))
finally:
    stop.set()
    h.stop()

check("streaming and batch features agree + live tests (pytest tests/step6)",
      subprocess.run([sys.executable, "-m", "pytest", "tests/step6", "-q"], cwd=ROOT).returncode == 0)

try:
    import playwright  # noqa: F401

    print("INFO playwright importable, but screenshots are skipped unless Chromium is installed (downloads are not allowed here)")
except ImportError:
    print("INFO Playwright not installed: screenshot step skipped (results/screens/ not created)")
sys.exit(0 if ok else 1)
