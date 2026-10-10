"""Exit 0 only if Round 2 criteria hold. Extended task by task."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok &= bool(cond)


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


# R0
check("tag round1 exists", git("tag", "-l", "round1") == "round1")
check("results_round1/ copy exists", (ROOT / "results_round1" / "SUMMARY.md").is_file())
sys.exit(0 if ok else 1)
