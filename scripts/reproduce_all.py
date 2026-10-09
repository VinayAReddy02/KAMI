"""Run every experiment in order and regenerate results/SUMMARY.md."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    ["scripts/build_datasets.py"],
    ["-m", "kami.eval.run_baselines"],
    ["-m", "kami.eval.run_evidence"],
    ["-m", "kami.eval.run_fusion"],
    ["scripts/make_summary.py"],
]

for s in STEPS:
    print(">>", " ".join(s), flush=True)
    if subprocess.run([sys.executable, *s], cwd=ROOT).returncode != 0:
        sys.exit(f"failed: {' '.join(s)}")
print("all results regenerated")
