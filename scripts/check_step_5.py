"""Exit 0 only if Step 5 criteria hold."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok &= bool(cond)


r = subprocess.run([sys.executable, "-m", "kami.eval.run_fusion"], cwd=ROOT, timeout=1800)
check("run_fusion finished", r.returncode == 0)
tab = (ROOT / "results" / "tables" / "fusion_ablation.md").read_text(encoding="utf-8")
for name in ("scenarios", "battledim"):
    sec = tab.split(f"## {name}")[1].split("##")[0]
    n = sum(1 for ln in sec.splitlines() if ln.startswith("| ") and not ln.startswith("| Model") and "---" not in ln)
    check(f"ablation table for {name} has >= 5 rows ({n})", n >= 5)
conf = list((ROOT / "results" / "confusion").glob("*.json"))
check("confusion matrices saved", len(conf) >= 16 and (ROOT / "results" / "tables" / "confusion_matrices.md").is_file())
sel = json.loads((ROOT / "results" / "fusion" / "selection.json").read_text(encoding="utf-8"))
dec = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
m = re.search(r"### Step 5.*", dec, re.S)
logged = bool(m) and all(f"{sel['val_macro_f1'][k]:.3f}" in m.group(0) for k in ("F-A", "F-B"))
check(f"selection ({sel['selected']}) logged in decisions.md with the validation numbers", logged)
log = json.loads((ROOT / "results" / "fusion" / "test_eval_log.json").read_text(encoding="utf-8"))
check("test split opened exactly once per model and dataset (log keys unique)", len({x["key"] for x in log}) == len(log) == 17)
check("docs/fusion.md exists", (ROOT / "docs" / "fusion.md").is_file())
subprocess.run([sys.executable, "scripts/make_summary.py"], cwd=ROOT)
sm = (ROOT / "results" / "SUMMARY.md").read_text(encoding="utf-8")
check("results/SUMMARY.md states plainly whether fusion beats threshold voting", ("beats threshold voting" in sm or "does NOT beat threshold voting" in sm))
p = subprocess.run([sys.executable, "-m", "pytest", "tests/step5", "-q"], cwd=ROOT)
check("pytest tests/step5", p.returncode == 0)
sys.exit(0 if ok else 1)
