"""Exit 0 only if the Round 8 criteria hold (PLAN_ROUND8.md: demo polish, WCAG 2.1 AA), reading real artefacts.

    python scripts/check_round8.py            # everything (build, unit and browser tests, earlier quick checks)
    python scripts/check_round8.py --quick    # artefacts and git only

This process is locked to dry run; the browser tests use their own locked test server (scripts/e2e_server.py).
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
ROUND_BASE = "21b8448"  # last commit before Round 8
ROUND_START = "2026-10-18"
ALLOWED_RESULTS = ("results/screens/", "results/a11y/", "results/demo_polish/")


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

# ---------------------------------------------------------------- audit and its findings
audit = text_of("results/demo_polish/audit.md")
check("P1 results/demo_polish/audit.md exists with the health score and ranked findings",
      "Audit Health Score" in audit and re.search(r"\[P[0-3]\]", audit) is not None)
blocks = re.split(r"\n(?=### \[P[0-3]\])", audit)
major = [b for b in blocks if re.match(r"### \[P[01]\]", b)]
open_major = [b.splitlines()[0][:80] for b in major if not re.search(r"\*\*Status:\*\* fixed\b.*test", b)]
check(f"P2 every P0/P1 finding is marked fixed and names its test ({len(major)} found; open: {open_major[:3] or 'none'})", not open_major)

# ---------------------------------------------------------------- WCAG 2.1 AA scan (written by the a11y spec)
aa = {}
p = ROOT / "results" / "a11y" / "axe_report.json"
if p.is_file():
    aa = json.loads(p.read_text(encoding="utf-8"))
check("P2 the axe report uses the WCAG 2.1 A and AA rule tags and was made in Round 8",
      aa.get("created_utc", "")[:10] >= ROUND_START and all(t in json.dumps(aa.get("rule_set", "")) for t in ("wcag2a", "wcag2aa", "wcag21a", "wcag21aa")))
check(f"P2 the WCAG 2.1 AA scan is clean on all pages in both themes ({aa.get('pages_scanned')} scans, {aa.get('aa_violations_unaccepted')} unaccepted violations)",
      aa.get("pages_scanned", 0) >= 10 and aa.get("aa_violations_unaccepted") == 0)

# ---------------------------------------------------------------- scope: only the presentation layer changed
changed = set(git("diff", "--name-only", ROUND_BASE).split()) | {ln[3:] for ln in git("status", "--porcelain").splitlines()}
backend = sorted(f for f in changed if f.startswith("src/kami/"))
results_other = sorted(f for f in changed if f.startswith("results/") and not f.startswith(ALLOWED_RESULTS))
check(f"scope: no backend file changed {backend[:3] or ''}", not backend)
check(f"scope: no result outside screens, a11y and demo_polish changed {results_other[:3] or ''}", not results_other)
shots = [f for f in changed if f.startswith("results/screens/") and f.endswith(".png")]
check(f"P3 the 16 paper screenshots were regenerated in Round 8 ({len(shots)})", len(shots) == 16)
check("P0 the locally installed skill files stay out of git",
      all(x in text_of(".gitignore") for x in (".agents/", ".claude/skills/", "skills-lock.json")) and not git("ls-files", ".agents", ".claude/skills", "skills-lock.json"))
check("P4 PROGRESS.md and docs/decisions.md record Round 8", "Round 8" in text_of("PROGRESS.md") and "Round 8" in text_of("docs/decisions.md"))

if not args.quick:
    b = subprocess.run([npm, "run", "build"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=child_env)
    check("npm run build", b.returncode == 0)
    vt = subprocess.run([npm, "run", "test"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore", env=child_env)
    check("npm run test (Vitest)", vt.returncode == 0)
    out_dir = Path(tempfile.mkdtemp(prefix="kami_r8_e2e_"))
    pw = subprocess.run([npx, "playwright", "test"], cwd=fe, capture_output=True, text=True, encoding="utf-8", errors="ignore",
                        env={**child_env, "KAMI_E2E_OUT": str(out_dir)})
    tail = ([ln.strip() for ln in pw.stdout.splitlines() if ln.strip()][-1:] or [pw.stderr[-200:]])[0]
    check(f"Playwright tests pass, including the AA scan, keyboard and projector tests ({tail})", pw.returncode == 0)
    run_aa = out_dir / "a11y" / "axe_report.json"
    fresh = json.loads(run_aa.read_text(encoding="utf-8")) if run_aa.is_file() else {}
    check("this run's AA scan is clean as well", fresh.get("pages_scanned", 0) >= 10 and fresh.get("aa_violations_unaccepted") == 0)
    for script, extra in (("check_round7.py", ["--quick"]), ("check_round6.py", ["--quick", "--part", "a", "--part", "c"])):
        r = subprocess.run([sys.executable, f"scripts/{script}", *extra], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", env=child_env)
        for ln in r.stdout.splitlines():
            if ln.startswith("FAIL"):
                print("     ", ln)
        check(f"scripts/{script} {' '.join(extra)} still passes", r.returncode == 0)
check(f"no request left this machine during this check {sorted(set(refused)) or ''}", not refused)
sys.exit(0 if ok else 1)
