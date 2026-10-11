"""Exit 0 only if the WhatsApp add-on criteria hold (PLAN_WHATSAPP.md), reading real artefacts.

    python scripts/check_whatsapp.py            # everything, including scripts/check_round2.py (slow: all earlier checks)
    python scripts/check_whatsapp.py --quick    # add-on checks only

This script can never send a WhatsApp message: it removes every credential from its own environment, points the
settings loader at a file that does not exist (so a filled-in .env is not read) and starts the system with
notifications forced to dry run.
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
SECRET_NAMES = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM", "WHATSAPP_TO")
# what a leaked Twilio credential or a real recipient number looks like in a text file
PATTERNS = {
    "Twilio Account SID": re.compile(r"\bAC[0-9a-f]{32}\b"),
    "Twilio API key SID": re.compile(r"\bSK[0-9a-f]{32}\b"),
    "Twilio auth token": re.compile(r"(?i)auth[_-]?token[\"'\s:=]+[0-9a-f]{32}\b"),
    "recipient number": re.compile(r"WHATSAPP_TO\s*[=:]\s*[\"']?whatsapp:\+\d{9,}"),
}
BINARY = {".parquet", ".png", ".npz", ".joblib", ".pdf", ".docx", ".ico", ".jpg", ".sqlite"}


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    ok &= bool(cond)
    return bool(cond)


def git(*a, code=False):
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    return r.returncode if code else r.stdout.rstrip("\n")


ap = argparse.ArgumentParser()
ap.add_argument("--quick", action="store_true")
args = ap.parse_args()

# ---------------------------------------------------------------- make sending impossible for this process
for k in (*SECRET_NAMES, "KAMI_WHATSAPP_ENABLE", "WHATSAPP_MAX_TOTAL"):
    os.environ.pop(k, None)
tmp = Path(tempfile.mkdtemp(prefix="kami_whatsapp_check_"))
os.environ["KAMI_NOTIFY_ENV_FILE"] = str(tmp / "no_such.env")
os.environ["KAMI_NOTIFY_DIR"] = str(tmp / "notifications")

# ---------------------------------------------------------------- secrets hygiene
check(".env is git-ignored and not tracked", git("check-ignore", "-q", ".env", code=True) == 0 and git("ls-files", ".env") == "")
hits = []
for rel in git("ls-files").splitlines():
    p = ROOT / rel
    if p.suffix.lower() in BINARY or not p.is_file() or p.stat().st_size > 8_000_000:
        continue
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    hits += [f"{rel}: {name}" for name, rx in PATTERNS.items() if rx.search(text)]
check(f"no tracked file contains a Twilio SID, auth token or a real recipient number {hits[:5] or ''}", not hits)
ex = (ROOT / ".env.example")
ex_text = ex.read_text(encoding="utf-8") if ex.is_file() else ""
ex_vals = dict(ln.split("=", 1) for ln in ex_text.splitlines() if "=" in ln and not ln.lstrip().startswith("#"))
check(".env.example lists the settings with placeholders only (no SID, no token, no real recipient)",
      all(k in ex_vals for k in (*SECRET_NAMES, "KAMI_WHATSAPP_ENABLE", "WHATSAPP_MAX_TOTAL"))
      and ex_vals["TWILIO_ACCOUNT_SID"] == "" and ex_vals["TWILIO_AUTH_TOKEN"] == "" and "X" in ex_vals["WHATSAPP_TO"]
      and ex_vals["KAMI_WHATSAPP_ENABLE"] == "0")
check("results/notifications/ (message logs) is git-ignored", git("check-ignore", "-q", "results/notifications/x.jsonl", code=True) == 0)

# ---------------------------------------------------------------- live: injected event -> dry-run entry with real values
import httpx  # noqa: E402

from kami.live.launch import launch  # noqa: E402
from kami.notify.message import PREFIX  # noqa: E402

PORT = 8104
h = launch(speed=3000, port=PORT, mode="fallback", temp_store=True)  # notifications default to forced dry run
base = f"http://127.0.0.1:{PORT}"
log_path = tmp / "notifications" / "dryrun_log.jsonl"
try:
    time.sleep(5)
    node = "node-3"
    name = next(n["name"] for n in httpx.get(f"{base}/network", timeout=10).json()["nodes"] if n["id"] == node)
    httpx.post(f"{base}/demo/inject", json={"type": "combined", "node": node}, timeout=10).raise_for_status()
    entry, t0 = None, time.time()
    while time.time() - t0 < 60 and entry is None:
        if log_path.exists():
            rows = [json.loads(ln) for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            entry = next((r for r in rows if r["alert"]["node_id"] == node), None)
        time.sleep(0.5)
    check(f"with no credentials, an injected combined event produces a dry-run log entry ({time.time() - t0:.1f} s)", entry is not None)
    if entry:
        a, text = entry["alert"], entry["text"]
        alerts = httpx.get(f"{base}/alerts", params={"node": node}, timeout=10).json()
        same = [x for x in alerts if x["id"] == a["id"] and x["start_ts"] == a["start_ts"]]
        print("    message:", text.replace("\n", " | ")[:300])
        check("the entry refers to a real alert of that node (same id and start time as GET /alerts)", len(same) == 1)
        check("the message carries the real values of that assessment: node name, category, priority, confidence, explanation, time",
              text.startswith(PREFIX) and name in text and a["category"] in text and a["priority"] in text
              and f"{a['confidence']:.2f}" in text and a["explanation"][:60] in text and a["ts"][:16].replace("T", " ") in text)
        check("the explanation quotes numeric evidence values", bool(re.search(r"evidence \d\.\d\d", a["explanation"])))
        check("priority is High or Critical and the text is under 600 characters", a["priority"] in ("High", "Critical") and len(text) < 600)
        check("entry is marked as a dry run", entry["mode"] == "dry_run")
    r = httpx.get(f"{base}/notifications/status", timeout=10)
    s = r.json()
    print("    status:", json.dumps(s)[:400])
    check("GET /notifications/status works: mode dry_run, counts, last send time, limits and remaining budget",
          r.status_code == 200 and s["mode"] == "dry_run" and s["sent"] >= 1 and s["last_send_utc"]
          and {"suppressed", "failed", "limits", "budget_remaining"} <= set(s))
    flat = json.dumps(s)
    check("status exposes no secrets (no SID, token or phone number; setting names may appear, values never)",
          not any(rx.search(flat) for rx in PATTERNS.values()) and "whatsapp:+" not in flat.lower()
          and not re.search(r"\+?\d{9,}", flat))
finally:
    h.stop()

# ---------------------------------------------------------------- unit tests (trigger rule, cooldown, cap, failures, secrets)
t = subprocess.run([sys.executable, "-m", "pytest", "tests/whatsapp", "-q", "-p", "no:warnings"], cwd=ROOT, capture_output=True, text=True)
print("   ", t.stdout.strip().splitlines()[-1] if t.stdout.strip() else t.stderr[-300:])
check("pytest tests/whatsapp passes (trigger rule, escalation, cooldown, hourly cap, lifetime budget, dry-run fallback, "
      "failures and retries, window-closed handling, no secrets in logs or responses, no real HTTP)", t.returncode == 0)
check("docs/notifications.md and scripts/send_test_alert.py exist",
      (ROOT / "docs" / "notifications.md").is_file() and (ROOT / "scripts" / "send_test_alert.py").is_file())

# ---------------------------------------------------------------- everything earlier still passes
if not args.quick:
    r = subprocess.run([sys.executable, "scripts/check_round2.py"], cwd=ROOT, capture_output=True, text=True)
    for ln in r.stdout.splitlines():
        if ln.startswith("FAIL"):
            print("     ", ln)
    check("scripts/check_round2.py still passes (Round 2 artefacts, every check_step_N.py, pytest -q, npm run build)", r.returncode == 0)
sys.exit(0 if ok else 1)
