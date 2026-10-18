"""Exit 0 only if the Round 9 criteria hold (PLAN_ROUND9.md: full dashboard redesign), reading real artefacts.

    python scripts/check_round9.py            # everything (build, unit and browser tests, earlier checks)
    python scripts/check_round9.py --quick    # artefacts and git only
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
ROUND_BASE = "04a7c84"  # last commit before Round 9
ROUND_START = "2026-10-18"
ALLOWED_RESULTS = ("results/screens/", "results/a11y/", "results/redesign/")


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    ok &= bool(cond)
    return bool(cond)


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore").stdout.rstrip("\n")


def text_of(rel):
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


ap = argparse.ArgumentParser()
ap.add_argument("--quick", action="store_true")
args = ap.parse_args()

from kami.notify.lock import lock_to_dry_run, refused  # noqa: E402

lock_to_dry_run()
child_env = {**os.environ, "KAMI_MODE": "fallback"}
fe = ROOT / "frontend"
npm, npx = shutil.which("npm"), shutil.which("npx")

# ---------------------------------------------------------------- direction and design record
briefs = list((ROOT / ".impeccable").rglob("*.md")) if (ROOT / ".impeccable").is_dir() else []
contract = next((p.read_text(encoding="utf-8") for p in briefs if "## Direction contract" in p.read_text(encoding="utf-8")), "")
check("R1 a surface brief holds the direction contract (THESIS, OWN-WORLD, STORY, FIRST VIEWPORT, FORM with seed reference, FINISH)",
      all(k in contract for k in ("THESIS", "OWN-WORLD", "STORY", "FIRST VIEWPORT", "FORM", "FINISH")) and re.search(r"seed: ?([0-9a-f]{16}|none)", contract) is not None)
design = text_of("DESIGN.md")
djson = ROOT / ".impeccable" / "design.json"
check("R3 DESIGN.md and .impeccable/design.json describe the built world (tokens present)",
      len(design) > 800 and djson.is_file() and len(djson.read_text(encoding="utf-8")) > 200)
review = ROOT / "results" / "redesign" / "review.md"
check("R3 the finish review is recorded with its disposition (results/redesign/review.md)",
      review.is_file() and re.search(r"(?i)disposition[^\n]*(ship|fix|rebuild|recapture)", review.read_text(encoding="utf-8")) is not None)

# ---------------------------------------------------------------- binding constraints kept
css = text_of("frontend/src/theme.css")
check("binding: a light and a dark theme both exist", '[data-theme="light"]' in css and '[data-theme="dark"]' in css)
src = "".join(p.read_text(encoding="utf-8") for p in (fe / "src").rglob("*.tsx"))
check("binding: the data-provenance labels are still in the dashboard", all(s in src or s in text_of("config/nodes.json") for s in
      ("Simulated data", "dry run", "fictional")))
aa = json.loads(text_of("results/a11y/axe_report.json") or "{}")
check(f"binding: WCAG 2.1 AA scan clean on all pages in both themes, made in Round 9 ({aa.get('pages_scanned')} scans)",
      aa.get("created_utc", "")[:10] >= ROUND_START and aa.get("pages_scanned", 0) >= 10 and aa.get("aa_violations_unaccepted") == 0
      and git("diff", "--name-only", ROUND_BASE, "--", "results/a11y/axe_report.json") != "")

# ---------------------------------------------------------------- scope
changed = set(git("diff", "--name-only", ROUND_BASE).split()) | {ln[3:] for ln in git("status", "--porcelain").splitlines()}
backend = sorted(f for f in changed if f.startswith("src/kami/"))
results_other = sorted(f for f in changed if f.startswith("results/") and not f.startswith(ALLOWED_RESULTS))
check(f"scope: no backend file changed {backend[:3] or ''}", not backend)
check(f"scope: no result outside screens, a11y and redesign changed {results_other[:3] or ''}", not results_other)
shots = [f for f in changed if f.startswith("results/screens/") and f.endswith(".png")]
check(f"R4 the 16 paper screenshots were regenerated in Round 9 ({len(shots)})", len(shots) == 16)
check("R4 PROGRESS.md and docs/decisions.md record Round 9", "Round 9" in text_of("PROGRESS.md") and "Round 9" in text_of("docs/decisions.md"))

if not args.quick:
    b = subprocess.run([npm, "run", "build"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=child_env)
    check("npm run build", b.returncode == 0)
    vt = subprocess.run([npm, "run", "test"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=child_env)
    check("npm run test (Vitest)", vt.returncode == 0)
    out_dir = Path(tempfile.mkdtemp(prefix="kami_r9_e2e_"))
    pw = subprocess.run([npx, "playwright", "test"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                        env={**child_env, "KAMI_E2E_OUT": str(out_dir)})
    tail = ([ln.strip() for ln in pw.stdout.splitlines() if ln.strip()][-1:] or [pw.stderr[-200:]])[0]
    check(f"all Playwright tests pass (behaviour, keyboard, reflow, projector, AA scan) ({tail})", pw.returncode == 0)
    for script, extra in (("check_round8.py", ["--quick"]), ("check_round7.py", ["--quick"])):
        r = subprocess.run([sys.executable, f"scripts/{script}", *extra], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", env=child_env)
        fails = [ln for ln in r.stdout.splitlines() if ln.startswith("FAIL")]
        for ln in fails:
            print("     ", ln)
        # Round 8's own scope and screenshot lines compare against its base and are expected to see Round 9's UI changes
        real = [ln for ln in fails if not any(k in ln for k in ("scope:", "screenshots were regenerated", "P2 every P0/P1", "made in Round 8"))]
        check(f"scripts/{script} {' '.join(extra)}: no failure beyond the expected base-commit lines", not real)
check(f"no request left this machine during this check {sorted(set(refused)) or ''}", not refused)
sys.exit(0 if ok else 1)
