"""Exit 0 only if the Round 5 criteria hold (PLAN_ROUND5.md), reading real artefacts.

    python scripts/check_round5.py            # everything, including scripts/check_telegram.py (slow: all earlier checks)
    python scripts/check_round5.py --quick    # Round 5 checks only

Nothing here can send a Telegram message: this process is locked to dry run (kami.notify.lock), every child process
gets an environment without the alert-push settings and with a settings file that does not exist, the browser tests
start scripts/e2e_server.py (locked the same way), and the Telegram tests refuse every real request.
The browser tests write into a temporary folder here, so a check run does not rewrite results/screens or results/a11y.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ok = True
ROUND_BASE = "5aa9bcf"  # last commit before Round 5
ROUND_START = "2026-10-12"
SETTING_NAMES = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "KAMI_TELEGRAM_ENABLE")
PAGES = ("overview", "node_detail_injected_event", "alerts", "method")
SHOTS = [f"{p}_{t}_{s}.png" for s in ("desktop_1440x900", "phone_390x844") for t in ("dark", "light") for p in PAGES]
CAUSE_WORDS = ("leak", "burst", "contamin", "pollut", "sewage", "rupture", "because")
M1_TESTS = ("test_the_first_real_alert_in_the_new_wording", "test_message_has_plain_reasons_and_action_line_and_names_no_cause",
            "test_longest_message_stays_under_600_characters", "test_words_follow_the_numbers")
GUARD_TEST = "test_a_real_request_is_refused_and_would_fail_the_test"


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    ok &= bool(cond)
    return bool(cond)


def git(*a, code=False):
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.returncode if code else r.stdout.rstrip("\n")


def load(rel):
    p = ROOT / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


ap = argparse.ArgumentParser()
ap.add_argument("--quick", action="store_true")
args = ap.parse_args()

# ---------------------------------------------------------------- make sending impossible, here and in every child process
from kami.notify.lock import lock_to_dry_run, refused  # noqa: E402

notify_dir = lock_to_dry_run()
tmp = Path(tempfile.mkdtemp(prefix="kami_round5_check_"))
child_env = {k: v for k, v in os.environ.items() if k not in SETTING_NAMES}
child_env["KAMI_NOTIFY_DIR"] = str(tmp / "child_notifications")
child_env["KAMI_E2E_OUT"] = str(tmp / "e2e")
decisions = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")

# ---------------------------------------------------------------- M1: alert wording
t = subprocess.run([sys.executable, "-m", "pytest", "tests/telegram", "-vv", "-p", "no:warnings", "-p", "no:cacheprovider"],
                   cwd=ROOT, capture_output=True, text=True, env=child_env)
print("   ", t.stdout.strip().splitlines()[-1] if t.stdout.strip() else t.stderr[-300:])
check("M1 pytest tests/telegram passes (mocked HTTP only)", t.returncode == 0)
check("M1 the wording tests ran and passed: first real alert in the new wording, plain reasons + action line + no cause, longest case under 600",
      all(re.search(rf"{name}\S* PASSED", t.stdout) for name in M1_TESTS))
check("no real Telegram request: the test that proves a real request is refused (and fails the test) passed",
      bool(re.search(rf"{GUARD_TEST}\S* PASSED", t.stdout)))

import httpx  # noqa: E402

from kami.live.launch import launch  # noqa: E402
from kami.notify.message import PREFIX  # noqa: E402

PORT = 8105
h = launch(speed=3000, port=PORT, mode="fallback", temp_store=True)  # notifications default to forced dry run
base = f"http://127.0.0.1:{PORT}"
try:
    time.sleep(5)
    node = "node-2"
    name = next(n["name"] for n in httpx.get(f"{base}/network", timeout=10).json()["nodes"] if n["id"] == node)
    httpx.post(f"{base}/demo/inject", json={"type": "infra_burst", "node": node}, timeout=10).raise_for_status()
    entry, t0 = None, time.time()
    while time.time() - t0 < 60 and entry is None:
        log = notify_dir / "dryrun_log.jsonl"
        if log.exists():
            rows = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
            entry = next((x for x in rows if x["alert"]["node_id"] == node), None)
        time.sleep(0.5)
    mode = httpx.get(f"{base}/notifications/status", timeout=10).json()["mode"]
finally:
    h.stop()
if check("M1 an injected event in the live pipeline produces a dry-run message (alert push in dry run)", entry is not None and mode == "dry_run"):
    a, text = entry["alert"], entry["text"]
    lines = text.split("\n")
    print("    message:", text.replace("\n", " | "))
    check("M1 the live message keeps the prefix and the Replay time line and is under 600 characters",
          lines[0] == PREFIX == "[KAMI DEMO - simulated data]" and lines[-1].startswith("Replay time: ") and len(text) < 600)
    check("M1 the live message has the plain-language reason built from the real values (model score, confidence labelled as the fused value)",
          f"model score {a['p_infra']:.2f}" in text and f"Confidence: {a['confidence']:.2f} (final fused value, not the model score)" in text
          and re.search(r"Flow/pressure: unusual for [\d.]+ (min|h), (started suddenly|built up gradually)", text) is not None
          and "above threshold" not in text and "evidence" not in text)
    check("M1 the live message has the generic action line for its category and names no cause",
          f"Action: Check pressure and flow at {name}." in lines and not any(w in text.lower() for w in CAUSE_WORDS))

# ---------------------------------------------------------------- P1, P2, P3: browser tests (output into a temporary folder)
npm, npx = shutil.which("npm"), shutil.which("npx")
fe = ROOT / "frontend"
check("npm run build", subprocess.run([npm, "run", "build"], cwd=fe, capture_output=True, env=child_env).returncode == 0)
pw = subprocess.run([npx, "playwright", "test"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=child_env)
tail = [ln for ln in pw.stdout.splitlines() if ln.strip()][-1:] or [pw.stderr[-300:]]
print("    playwright:", tail[0].strip())
check("P1/P2/P3 the Playwright tests pass (dashboard, accessibility scan, screenshots)", pw.returncode == 0)
check("P1 the five dashboard tests ran: 8 markers and label, injected event in the feed, node detail, alert filters, theme toggle",
      len(re.findall(r"^\s+ok\s+\d+ .*dashboard\.spec\.ts", pw.stdout, flags=re.M)) == 5)
made = {f.name: f.stat().st_size for f in (tmp / "e2e" / "screens").glob("*.png")} if (tmp / "e2e" / "screens").is_dir() else {}
check(f"P2 this run produced all 16 screenshots, none empty ({len(made)} files)", set(made) == set(SHOTS) and min(made.values(), default=0) > 5000)
run_axe = json.loads((tmp / "e2e" / "a11y" / "axe_report.json").read_text(encoding="utf-8")) if (tmp / "e2e" / "a11y" / "axe_report.json").is_file() else {}
check("P3 this run scanned 4 pages x 2 themes with axe-core and left no serious or critical finding unresolved",
      run_axe.get("pages_scanned") == 8 and run_axe.get("serious_or_critical_unresolved") == 0)

# ---------------------------------------------------------------- P2, P3: the stored artefacts
kept = {f.name: f.stat().st_size for f in (ROOT / "results" / "screens").glob("*.png")}
manifest = load("results/screens/manifest.json") or {}
check(f"P2 results/screens/ holds every expected screenshot, none empty (4 pages x 2 themes x 2 sizes = 16; found {len(kept)})",
      set(kept) == set(SHOTS) and min(kept.values(), default=0) > 5000)
check("P2 the manifest lists the same 16 files, the replay time and the injected event; made by the Playwright spec",
      sorted(f["file"] for f in manifest.get("files", [])) == sorted(SHOTS) and manifest.get("replay_time")
      and manifest.get("injected_event", {}).get("node") == "node-2" and "not edited by hand" in manifest.get("made_by", ""))
axe = load("results/a11y/axe_report.json") or {}
accepted = load("frontend/e2e/a11y_accepted.json")
blocking = [(s["page"], s["theme"], v["id"]) for s in axe.get("scans", []) for v in s["violations"] if v["impact"] in ("serious", "critical")]
unlisted = sorted({rule for _, _, rule in blocking if f"`{rule}`" not in decisions})
check("P3 results/a11y/axe_report.json and .md exist; 8 scans (4 pages x 2 themes)",
      axe.get("pages_scanned") == 8 and len(axe.get("scans", [])) == 8 and (ROOT / "results" / "a11y" / "axe_report.md").is_file())
check(f"P3 no serious or critical finding is unresolved unless its rule is listed in docs/decisions.md {unlisted or ''}",
      not unlisted and axe.get("serious_or_critical_unresolved") == 0 and isinstance(accepted, list)
      and all(f"`{x['id']}`" in decisions and x.get("reason") for x in accepted))
check("P3 docs/decisions.md records the accessibility check and what was fixed", "Accessibility check" in decisions and "axe" in decisions)

# ---------------------------------------------------------------- Q1: quiet-demo measurement
q = load("results/demo_quiet/quiet_demo.json")
skipped = re.search(r"Q1 (was )?(skipped|not run)", decisions) is not None
if q is None:
    check("Q1 results/demo_quiet/quiet_demo.json exists, or docs/decisions.md records why Q1 was skipped", skipped)
else:
    al, eps = q["alerts"], q["episodes"]
    check("Q1 quiet_demo.json was produced by a run in this round (run date, commit at or after the round's base, made by the script)",
          q["run_utc"][:10] >= ROUND_START and q["made_by"] == "scripts/quiet_demo.py"
          and git("merge-base", "--is-ancestor", ROUND_BASE, q["git_commit"], code=True) == 0)
    check("Q1 the run had no injection, used the forced dry run, covered 8 nodes over a fixed window and read no held-out data",
          q["setup"]["injections"] == 0 and q["setup"]["alert_push"] == "forced dry run" and q["setup"]["nodes"] == 8
          and q["setup"]["simulated_days"] >= 14 and "no held-out test set is read" in q["data"]["period"]
          and q["data"]["latest_source_row"] < load("results/splits/battledim.json")["train_end"])
    check("Q1 the counts are consistent with the listed episodes (totals, per node, per day, by category, by priority)",
          al["episodes_opened"] == len(eps) == sum(v["episodes_opened"] for v in q["per_node"].values()) == sum(al["per_day"].values())
          == sum(al["by_highest_priority"].values()) == sum(al["by_category_at_open"].values())
          and al["high_or_critical_episodes"] == sum(e["highest_priority"] in ("High", "Critical") for e in eps)
          and al["per_simulated_day_mean"] == round(len(eps) / q["setup"]["simulated_days"], 2))
    check("Q1 the positive control (one injected event, same code) did produce an alert, so a low count is meaningful",
          q["positive_control"]["episodes_at_injected_node"] >= 1)
    md = (ROOT / "results" / "demo_quiet" / "quiet_demo.md").read_text(encoding="utf-8") if (ROOT / "results" / "demo_quiet" / "quiet_demo.md").is_file() else ""
    check("Q1 quiet_demo.md has the same counts and says that this is replayed demo data, not a false-alarm rate",
          f"| Alert episodes opened | {al['episodes_opened']} |" in md and "not a false-alarm rate" in md and "simulated" in md and "real river" in md)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    check("Q1 README has the one-line expectation with the measured numbers",
          re.search(rf"[Ww]ith no injection.*\b{re.escape(str(al['per_simulated_day_mean']))}\b.*alert", readme) is not None)

# ---------------------------------------------------------------- no real Telegram request; everything earlier still passes
AUTO = "notifications=" + '"auto"'  # in two pieces so that this file does not match itself
launchers = [p.name for p in (ROOT / "scripts").glob("*.py") if AUTO in p.read_text(encoding="utf-8")]
check(f"only scripts/run_demo.py can start the system with real sending allowed {launchers}", launchers == ["run_demo.py"])
check(f"no request left this machine during this check {sorted(set(refused)) or ''}", not refused)
if not args.quick:
    r = subprocess.run([sys.executable, "scripts/check_telegram.py"], cwd=ROOT, capture_output=True, text=True, env=child_env)
    for ln in r.stdout.splitlines():
        if ln.startswith(("FAIL", "      FAIL")):
            print("     ", ln.strip())
    check("scripts/check_telegram.py still passes (Round 4 checks, check_round2, every check_step_N.py, pytest -q, npm run build and test)",
          r.returncode == 0)

# Compared with git after the earlier checks have run. results/fusion/test_eval_log.json is the Round 1 access log of the
# exposed test_v1; scripts/check_step_5.py rewrites its time stamps on every run, so it is compared without "utc" fields.
R1_LOG = "results/fusion/test_eval_log.json"


def without_time(o):
    if isinstance(o, dict):
        return {k: without_time(v) for k, v in o.items() if k != "utc"}
    return [without_time(x) for x in o] if isinstance(o, list) else o


FINAL = ("results/fusion", "results/round2")
changed = set(git("diff", "--name-only", ROUND_BASE, "--", *FINAL).split()) | {ln[3:] for ln in git("status", "--porcelain", "--", *FINAL).splitlines()}
log_same = True
if R1_LOG in changed:
    log_same = without_time(json.loads(git("show", f"{ROUND_BASE}:{R1_LOG}"))) == without_time(json.loads((ROOT / R1_LOG).read_text(encoding="utf-8")))
    print("    INFO the Round 1 access log has new time stamps from the Round 1 checks; its content is " + ("unchanged" if log_same else "DIFFERENT"))
check(f"no file under results/fusion/ or results/round2/ changed in this round (git, against {ROUND_BASE}) {sorted(changed - {R1_LOG}) or ''}",
      not (changed - {R1_LOG}) and log_same)
sys.exit(0 if ok else 1)
