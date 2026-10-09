"""Exit 0 only if Step 4 criteria hold."""
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


r = subprocess.run([sys.executable, "-m", "kami.eval.run_evidence"], cwd=ROOT, timeout=1800)
check("run_evidence finished", r.returncode == 0)
files = sorted((ROOT / "results" / "evidence").glob("*__*.json"))
check("results/evidence/*.json exist (3 modules)", len(files) == 3)
decisions = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
for f in files:
    d = json.loads(f.read_text(encoding="utf-8"))
    tag = f"{d['dataset']}/{d['domain']}"
    check(f"{tag}: calibration metrics present", "brier" in d["val"] and bool(d["reliability_val"]))
    v, b = d["val"]["event"]["f1"], d["best_baseline_val"]["val_event_f1"]
    explained = bool(re.search(rf"Step 4.*{re.escape(tag)}", decisions, re.S))
    print(f"   val event F1 {v:.3f} vs best baseline {b:.3f} ({d['best_baseline_val']['model']})")
    check(f"{tag}: val event F1 >= best baseline, or explained in decisions.md", v >= b or explained)
for fig in ("battledim_infra", "scenarios_infra", "scenarios_quality"):
    check(f"reliability figure {fig}", (ROOT / "results" / "figures" / f"reliability_{fig}.png").is_file())
p = subprocess.run([sys.executable, "-m", "pytest", "tests/step4", "-q"], cwd=ROOT)
check("pytest tests/step4", p.returncode == 0)
sys.exit(0 if ok else 1)
