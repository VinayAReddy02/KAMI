"""Exit 0 only if the Round 7 criteria hold (PLAN_ROUND7.md), reading real artefacts.

    python scripts/check_round7.py            # everything, including the earlier check scripts (slow)
    python scripts/check_round7.py --quick    # Round 7 checks only
    python scripts/check_round7.py --part n   # only N1/N2 (node numbers) or g (GECCO real-data test); default: both

Nothing here can reach Telegram or Ollama or load a speech model: this process is locked to dry run and child
processes get an environment without the bot settings (as in check_round6.py).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
ok = True
ROUND_BASE = "c75640d"  # the Round 7 plan commit; nothing of Round 7 is in it
ROUND_START = "2026-10-17"
FINAL = ("results/fusion", "results/round2", "results/citizen/eval.json", "results/citizen/eval.md")
SCREENS = [f"{p}_{t}_{v}.png" for v in ("desktop_1440x900", "phone_390x844") for t in ("dark", "light")
           for p in ("overview", "node_detail_injected_event", "alerts", "method")]


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    ok &= bool(cond)
    return bool(cond)


def git(*a):
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return r.stdout.rstrip("\n")


def load(rel):
    p = ROOT / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def text_of(rel):
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


ap = argparse.ArgumentParser()
ap.add_argument("--quick", action="store_true")
ap.add_argument("--part", choices=["n", "g"], action="append")
args = ap.parse_args()
parts = set(args.part or ["n", "g"])

from kami.notify.lock import lock_to_dry_run, refused  # noqa: E402

lock_to_dry_run()  # this process and its children (they inherit the environment) cannot send anything
child_env = {**os.environ, "KAMI_MODE": "fallback"}
npm, npx = shutil.which("npm"), shutil.which("npx")
fe = ROOT / "frontend"


def pytest(*targets, k=None):
    cmd = [sys.executable, "-m", "pytest", *targets, "-vv", "-p", "no:cacheprovider"] + (["-k", k] if k else [])
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=child_env)
    return r.returncode, r.stdout


# ================================================================ N1 / N2: node numbers everywhere
if "n" in parts:
    from kami.live.labels import node_fields, node_label, node_short, ward_label
    from kami.notify.message import LIMIT, PREFIX, format_message

    nodes = json.loads(text_of("config/nodes.json"))["nodes"]
    wards = {w["node_id"]: w for w in json.loads(text_of("data/citizen/wards_demo_fictional.json"))["wards"]}
    want = {n["id"]: f"{n['name']} ({n['id']} · Ward {wards[n['id']]['number']})" for n in nodes}
    check("N1 labels.py builds 'Name (node-N · Ward N)' for all 8 nodes from config/nodes.json and the ward file",
          len(nodes) == 8 and all(node_label(i) == w for i, w in want.items()))
    check("N1 short label is 'N · Locality' (e.g. '4 · Bagayam')", node_short("node-4") == "4 · Bagayam"
          and all(node_short(n["id"]) == f"{n['id'].split('-')[1]} · {wards[n['id']]['name_en']}" for n in nodes))
    check("N1 citizen ward label names the sensor point in English and Hindi",
          ward_label(4) == "Ward 4 (Bagayam, sensor point node-4)" and ward_label(4, hi=True).startswith("वार्ड 4 (") and "node-4" in ward_label(4, hi=True))
    f = node_fields("node-4")
    check("N1 API fields number, ward, label, short", f["number"] == 4 and f["ward"] == 4 and f["label"] == want["node-4"] and f["short"] == "4 · Bagayam")

    # the longest message: longest node name, Combined (two reason lines), every number at full detail
    longest = max(nodes, key=lambda n: len(node_label(n["id"])))["id"]
    t = {f"{s}_{k}": v for s in ("infra", "quality") for k, v in (("persist_steps", 287), ("suddenness", 0.99), ("recurrence", 23))}
    msg = format_message({"node_id": longest, "category": "Combined", "priority": "Critical", "confidence": 0.99, "ts": "2018-12-31T23:55:00",
                          "p_infra": 0.999, "p_quality": 0.999, "temporal": t})
    check(f"N1 Telegram message names the node with number and ward, keeps the prefix, stays under {LIMIT} characters ({len(msg)})",
          f"Node: {node_label(longest)}" in msg and msg.startswith(PREFIX) and len(msg) < LIMIT)

    # one label source: no component builds a node text from the raw name
    raw_uses = []
    for p in list((fe / "src" / "components").glob("*.tsx")) + list((fe / "src" / "pages").glob("*.tsx")):
        if p.name.endswith(".test.tsx"):
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\b(n|info|node)\??\.name\b|node_name\b|\.name\]\)", ln) and not re.search(r"node(Label|Short)\(", ln):
                raw_uses.append(f"{p.name}:{i}")
    check(f"N1 the dashboard takes every node text from frontend/src/labels.ts (raw name uses: {raw_uses[:4] or 'none'})",
          (fe / "src" / "labels.ts").is_file() and not raw_uses)
    py_raw = [f"{p.relative_to(ROOT)}" for p in (ROOT / "src" / "kami").rglob("*.py") if p.name != "labels.py"
              and re.search(r"Ward \{[^}]*\} \(\{[^}]*name_en", p.read_text(encoding="utf-8"))]
    check(f"N1 the citizen bot names wards only through labels.ward_label ({py_raw or 'ok'})", not py_raw)

    code, out = pytest("tests/round7")
    check("N1 pytest tests/round7 (labels, API fields, message, bot replies en/hi, guard)", code == 0 and " passed" in out and "FAILED" not in out)
    code, out = pytest("tests/citizen", "tests/telegram", "tests/live")
    check("N1 the citizen, Telegram and live tests still pass (grounding guard included)", code == 0 and "FAILED" not in out)

    vt = subprocess.run([npm, "run", "test"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=child_env)
    check("N1 Vitest passes, including frontend/src/labels.test.ts", vt.returncode == 0 and "labels.test" in vt.stdout)
    specs = "".join(p.read_text(encoding="utf-8") for p in (fe / "e2e").glob("*.spec.ts"))
    check("N1 the browser tests assert numbered labels (marker, dropdown '4 · Bagayam', alerts, complaints, node title)",
          all(s in specs for s in ("4 · Bagayam", "node-4 · Ward 4", "numbered")))
    if not args.quick:
        b = subprocess.run([npm, "run", "build"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=child_env)
        out_dir = Path(tempfile.mkdtemp(prefix="kami_r7_e2e_"))
        pw = subprocess.run([npx, "playwright", "test"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                            env={**child_env, "KAMI_E2E_OUT": str(out_dir)})
        tail = ([ln.strip() for ln in pw.stdout.splitlines() if ln.strip()][-1:] or [pw.stderr[-200:]])[0]
        check(f"N1 npm run build and the Playwright tests pass ({tail})", b.returncode == 0 and pw.returncode == 0 and " passed" in tail)

    shots = ROOT / "results" / "screens"
    changed = set(git("diff", "--name-only", ROUND_BASE, "--", "results/screens").split()) | \
        {ln[3:] for ln in git("status", "--porcelain", "--", "results/screens").splitlines()}
    check(f"N1 the 16 paper screenshots exist and were regenerated in Round 7 ({len(changed)} changed vs {ROUND_BASE})",
          all((shots / s).is_file() for s in SCREENS) and all(f"results/screens/{s}" in changed for s in SCREENS))
    ax = load("results/a11y/axe_report.json") or {}
    check(f"N1 axe re-run in Round 7 on all pages, both themes: no unresolved serious or critical finding ({ax.get('created_utc', '')[:10]})",
          ax.get("created_utc", "")[:10] >= ROUND_START and ax.get("pages_scanned", 0) >= 8 and ax.get("serious_or_critical_unresolved") == 0)
    docs = {d: text_of(d) for d in ("README.md", "docs/demo_script.md", "docs/citizen.md", "docs/notifications.md")}
    check("N1 docs use numbered labels (README, demo script '4 · Bagayam', citizen sample replies, notification sample)",
          "4 · Bagayam" in docs["docs/demo_script.md"] and "sensor point node-" in docs["docs/citizen.md"]
          and "· Ward " in docs["docs/notifications.md"] and "· Ward " in docs["README.md"])
    check("N2 PROGRESS.md records the live phone test result and that nothing needed fixing",
          re.search(r"N2[^\n]*nothing to fix", text_of("PROGRESS.md")) is not None)

# ================================================================ Part G: GECCO real-data test (filled in from G0 on)
if "g" in parts:
    src = text_of("data/raw/gecco/SOURCE.md")
    check("G0 data/raw/gecco/SOURCE.md exists with URL, licence and SHA-256 hashes",
          "zenodo" in src.lower() and "CC-BY-4.0" in src and re.search(r"[0-9a-f]{64}", src) is not None)

# ================================================================ always
changed = set(git("diff", "--name-only", ROUND_BASE, "--", *FINAL).split()) | {ln[3:] for ln in git("status", "--porcelain", "--", *FINAL).splitlines()}
R1_LOG = "results/fusion/test_eval_log.json"  # rewritten (time stamps only) by the Round 1 checks; check_round6.py compares it without them
check(f"no file under results/fusion/, results/round2/ or results/citizen/eval* changed (git vs {ROUND_BASE}) {sorted(changed - {R1_LOG}) or ''}",
      not (changed - {R1_LOG}))
from kami.eval.freeze import verify  # noqa: E402

try:
    verify()
    frozen_ok = True
except (SystemExit, Exception):
    frozen_ok = False
check("the Round 2 freeze still verifies (no frozen input file changed or added)", frozen_ok)
check(f"no request left this machine during this check {sorted(set(refused)) or ''}", not refused)
if not args.quick:
    r = subprocess.run([sys.executable, "scripts/check_round6.py", "--part", "a", "--part", "c"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore", env=child_env)
    for ln in r.stdout.splitlines():
        if ln.strip().startswith("FAIL"):
            print("     ", ln.strip())
    check("scripts/check_round6.py --part a --part c still passes (and with it check_round5, check_telegram, check_round2, every check_step_N)",
          r.returncode == 0)
sys.exit(0 if ok else 1)
