"""Exit 0 only if Step 3 criteria hold."""
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok &= bool(cond)


t0 = time.time()
r = subprocess.run([sys.executable, "-m", "kami.eval.run_baselines"], cwd=ROOT, timeout=900)
dt = time.time() - t0
check(f"python -m kami.eval.run_baselines finished in {dt:.0f}s (< 900s)", r.returncode == 0 and dt < 900)
files = sorted((ROOT / "results" / "baselines").glob("*__*.json"))
check("results/baselines/*.json written", len(files) >= 8)
check("results/tables/baselines.md written", (ROOT / "results" / "tables" / "baselines.md").is_file())

bad = []


def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, f"{path}/{k}")
    elif isinstance(o, float):
        if math.isnan(o):
            bad.append(("nan", path))
        elif ("precision" in path or "recall" in path or "/f1" in path) and not 0 <= o <= 1:
            bad.append(("range", path, o))


for f in files:
    d = json.loads(f.read_text(encoding="utf-8"))
    walk(d["test"], f.name)
    walk(d["val"], f.name)
check("all metrics in [0,1] and none NaN", not bad)
if bad:
    print(bad[:5])
log = json.loads((ROOT / "results" / "baselines" / "test_eval_log.json").read_text(encoding="utf-8"))
check("test split opened once per model and dataset", len({r["key"] for r in log}) == len(log) == 10)
p = subprocess.run([sys.executable, "-m", "pytest", "tests/step3", "-q"], cwd=ROOT)
check("pytest tests/step3", p.returncode == 0)
sys.exit(0 if ok else 1)
