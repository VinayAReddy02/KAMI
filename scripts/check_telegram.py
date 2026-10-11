"""Exit 0 only if the Round 4 criteria hold (PLAN_ROUND4.md), reading real artefacts.

    python scripts/check_telegram.py            # everything, including scripts/check_round2.py (slow: all earlier checks)
    python scripts/check_telegram.py --quick    # Round 4 checks only

This script can never reach Telegram: it removes the alert-push settings from its own environment, points the settings
loader at a file that does not exist (so a filled-in .env is not read), starts the system with notifications forced to
dry run, and refuses every HTTP request that would leave this machine.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ok = True
ROUND_BASE = "38232dd"  # last commit before Round 4
SETTING_NAMES = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "KAMI_TELEGRAM_ENABLE")
OLD_CHANNEL = "|".join(["whats" + "app", "twi" + "lio"])  # written in pieces so that this file does not match itself
HISTORY = ("docs/decisions.md", "PLAN_" + "WHATS" + "APP.md", "PLAN_ROUND4.md", "PLAN_ROUND5.md", "PROGRESS.md", "CLAUDE.md", "docs/reference/")
TOKEN_RX = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35}")  # what a real bot token looks like
BINARY = {".parquet", ".png", ".npz", ".joblib", ".pdf", ".docx", ".ico", ".jpg", ".sqlite"}
# fake values for this process only: they prove that complete settings do not switch a check run to real sending
FAKE_TOKEN, FAKE_CHAT = "123456:CHECK-TOKEN-not-real", "424242000111"


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    ok &= bool(cond)
    return bool(cond)


def git(*a, code=False):
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.returncode if code else r.stdout.rstrip("\n")


ap = argparse.ArgumentParser()
ap.add_argument("--quick", action="store_true")
args = ap.parse_args()

# ---------------------------------------------------------------- make sending impossible for this process
tmp = Path(tempfile.mkdtemp(prefix="kami_telegram_check_"))
child_env = {k: v for k, v in os.environ.items() if k not in SETTING_NAMES}
child_env["KAMI_NOTIFY_ENV_FILE"] = str(tmp / "no_such.env")
child_env["KAMI_NOTIFY_DIR"] = str(tmp / "child_notifications")
os.environ["KAMI_NOTIFY_ENV_FILE"] = str(tmp / "no_such.env")
os.environ["KAMI_NOTIFY_DIR"] = str(tmp / "notifications")
os.environ.update({"TELEGRAM_BOT_TOKEN": FAKE_TOKEN, "TELEGRAM_CHAT_ID": FAKE_CHAT, "KAMI_TELEGRAM_ENABLE": "1"})

import httpx  # noqa: E402

outside: list[str] = []


def _refuse(self, request):
    outside.append(request.url.host)
    raise RuntimeError("check_telegram.py refuses HTTP requests that leave this machine")


_real_handle = httpx.HTTPTransport.handle_request
httpx.HTTPTransport.handle_request = lambda self, request: (
    _real_handle(self, request) if request.url.host in ("127.0.0.1", "localhost") else _refuse(self, request))

# ---------------------------------------------------------------- the old channel is gone
hits = [ln.split(":", 1)[0] for ln in git("grep", "-l", "-i", "-E", OLD_CHANNEL).splitlines()]
left = sorted(f for f in hits if not any(f == h or (h.endswith("/") and f.startswith(h)) for h in HISTORY))
check(f"no mention of the old channel outside the history files {left[:6] or ''}", not left)
tracked = git("ls-files").splitlines()
gone = ["src/kami/notify/" + "twi" + "lio.py", "scripts/check_" + "whats" + "app.py"]
check("the old notifier, its check script and its test folder are removed from git",
      not any(f in tracked for f in gone) and not any(f.startswith("tests/" + "whats" + "app/") for f in tracked))

# ---------------------------------------------------------------- secrets hygiene
check(".env is git-ignored and not tracked", git("check-ignore", "-q", ".env", code=True) == 0 and git("ls-files", ".env") == "")
leaks = []
for rel in tracked:
    p = ROOT / rel
    if p.suffix.lower() in BINARY or not p.is_file() or p.stat().st_size > 8_000_000:
        continue
    try:
        if TOKEN_RX.search(p.read_text(encoding="utf-8", errors="ignore")):
            leaks.append(rel)
    except OSError:
        continue
check(f"no tracked file contains a string that looks like a Telegram bot token {leaks[:5] or ''}", not leaks)
ex = ROOT / ".env.example"
ex_vals = dict(ln.split("=", 1) for ln in (ex.read_text(encoding="utf-8") if ex.is_file() else "").splitlines()
               if "=" in ln and not ln.lstrip().startswith("#"))
check(".env.example lists the three settings with placeholders only (empty token, empty chat id, sending off)",
      set(ex_vals) == set(SETTING_NAMES) and ex_vals["TELEGRAM_BOT_TOKEN"] == "" and ex_vals["TELEGRAM_CHAT_ID"] == ""
      and ex_vals["KAMI_TELEGRAM_ENABLE"] == "0")
check("results/notifications/ (message log and state) is git-ignored", git("check-ignore", "-q", "results/notifications/x.jsonl", code=True) == 0)

# ---------------------------------------------------------------- status endpoint, in process, complete (fake) settings present
from fastapi.testclient import TestClient  # noqa: E402

from kami.api.app import create_app  # noqa: E402
from kami.ingest.bus import InProcessBus  # noqa: E402
from kami.live.system import build_live  # noqa: E402
from kami.notify.message import PREFIX  # noqa: E402
from kami.runtime import Stack  # noqa: E402
from kami.store import SqliteStore  # noqa: E402

stack = Stack.create(mode="fallback", store=SqliteStore(":memory:"), bus=InProcessBus())
app = create_app(stack)
build_live(stack, speed=0)  # the default every check, test and launch() uses
with TestClient(app) as c:
    r = c.get("/notifications/status")
    s = r.json()
print("    status:", json.dumps(s)[:300])
check("GET /notifications/status (in-process client) is dry_run by default, even with complete settings in the environment",
      r.status_code == 200 and s["mode"] == "dry_run" and {"sent", "suppressed", "failed", "last_send_utc", "limits"} <= set(s))
check("the status response contains no token and no chat id", FAKE_TOKEN not in r.text and FAKE_CHAT not in r.text
      and FAKE_TOKEN.split(":")[1] not in r.text and not TOKEN_RX.search(r.text))
stack.extras["notifications"].stop()

# ---------------------------------------------------------------- live: injected event -> dry-run entry with real values
from kami.live.launch import launch  # noqa: E402

PORT = 8104
h = launch(speed=3000, port=PORT, mode="fallback", temp_store=True)  # notifications default to forced dry run
base = f"http://127.0.0.1:{PORT}"
log_path = tmp / "notifications" / "dryrun_log.jsonl"
state_path = tmp / "notifications" / "state.json"
try:
    time.sleep(5)
    node = "node-3"
    name = next(n["name"] for n in httpx.get(f"{base}/network", timeout=10).json()["nodes"] if n["id"] == node)
    httpx.post(f"{base}/demo/inject", json={"type": "combined", "node": node}, timeout=10).raise_for_status()
    entry, t0 = None, time.time()
    while time.time() - t0 < 60 and entry is None:
        if log_path.exists():
            rows = [json.loads(ln) for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            entry = next((x for x in rows if x["alert"]["node_id"] == node), None)
        time.sleep(0.5)
    check(f"an injected event produces a dry-run log entry ({time.time() - t0:.1f} s)", entry is not None)
    if entry:
        a, text = entry["alert"], entry["text"]
        alerts = httpx.get(f"{base}/alerts", params={"node": node}, timeout=10).json()
        print("    message:", text.replace("\n", " | ")[:300])
        check("the entry refers to a real alert of that node (same id and start time as GET /alerts)",
              len([x for x in alerts if x["id"] == a["id"] and x["start_ts"] == a["start_ts"]]) == 1)
        check("the message carries the real values of that assessment: node name, category, priority, confidence, explanation, time",
              text.startswith(PREFIX) and name in text and a["category"] in text and a["priority"] in text
              and f"{a['confidence']:.2f}" in text and a["explanation"][:60] in text and a["ts"][:16].replace("T", " ") in text)
        check("priority is High or Critical, the text is under 600 characters and the entry is marked as a dry run",
              a["priority"] in ("High", "Critical") and len(text) < 600 and entry["mode"] == "dry_run")
    time.sleep(1.0)
    st = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    files = "".join(f.read_text(encoding="utf-8") for f in (tmp / "notifications").glob("*") if f.is_file())
    check("the state file has the counts and the last send time, and no file in the notification folder has the token or the chat id",
          st.get("sent", 0) >= 1 and st.get("last_send_utc") and {"suppressed", "failed", "mode"} <= set(st)
          and FAKE_TOKEN not in files and FAKE_CHAT not in files)
finally:
    h.stop()
check(f"no request left this machine during the checks above {sorted(set(outside)) or ''}", not outside)

# ---------------------------------------------------------------- tests
t = subprocess.run([sys.executable, "-m", "pytest", "tests/telegram", "-vv", "-p", "no:warnings", "-p", "no:cacheprovider"],
                   cwd=ROOT, capture_output=True, text=True, env=child_env)
print("   ", t.stdout.strip().splitlines()[-1] if t.stdout.strip() else t.stderr[-300:])
check("pytest tests/telegram passes (mocked HTTP only)", t.returncode == 0)
check("at least one test proves that a real request would be refused and would fail the test",
      bool(re.search(r"test_a_real_request_is_refused\S* PASSED", t.stdout)))
t = subprocess.run([sys.executable, "-m", "pytest", "tests/live/test_live_frozen.py", "-q", "-p", "no:warnings"],
                   cwd=ROOT, capture_output=True, text=True, env=child_env)
check("pytest tests/live/test_live_frozen.py passes (live path equals the batch frozen rule)", t.returncode == 0)
check("docs/notifications.md, scripts/send_test_alert.py and scripts/telegram_find_chat.py exist",
      all((ROOT / f).is_file() for f in ("docs/notifications.md", "scripts/send_test_alert.py", "scripts/telegram_find_chat.py")))

# ---------------------------------------------------------------- nothing final was touched; everything earlier still passes
check("no file under results/fusion/ or results/round2/ changed in this round (git diff against the round's base commit, and no untracked file)",
      git("diff", "--quiet", ROUND_BASE, "--", "results/fusion", "results/round2", code=True) == 0
      and git("status", "--porcelain", "--", "results/fusion", "results/round2") == "")
if not args.quick:
    r = subprocess.run([sys.executable, "scripts/check_round2.py"], cwd=ROOT, capture_output=True, text=True, env=child_env)
    for ln in r.stdout.splitlines():
        if ln.startswith("FAIL"):
            print("     ", ln)
    check("scripts/check_round2.py still passes (Round 2 artefacts, every check_step_N.py, pytest -q, npm run build)", r.returncode == 0)
sys.exit(0 if ok else 1)
