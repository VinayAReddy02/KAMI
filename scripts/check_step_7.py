"""Exit 0 only if Step 7 criteria hold. Includes the fresh-environment check (new venv outside the repo)."""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok &= bool(cond)


r = subprocess.run([sys.executable, "scripts/run_demo.py", "--check"], cwd=ROOT, timeout=300)
check("run_demo.py --check", r.returncode == 0)

# fresh environment: new venv, install from requirements.txt, run pytest -q
tmp = Path(tempfile.mkdtemp(prefix="kami_fresh_"))
venv = tmp / "venv"
subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
py = venv / "Scripts" / "python.exe"
inst = subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=ROOT, timeout=1500)
check("fresh venv: pip install -r requirements.txt", inst.returncode == 0)
t = subprocess.run([str(py), "-m", "pytest", "-q", "-rs", "-p", "no:warnings", "-p", "no:cacheprovider"],
                   cwd=ROOT, capture_output=True, text=True, timeout=1500)
print(t.stdout[-1500:])
check("fresh venv: pytest -q passes", t.returncode == 0)
skips = re.findall(r"SKIPPED .*", t.stdout)
check(f"only Docker-dependent tests are skipped ({len(skips)} skipped)", all("no Docker" in s for s in skips))
shutil.rmtree(tmp, ignore_errors=True)

npm = shutil.which("npm")
check("npm run build", subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", capture_output=True).returncode == 0)

summ = ROOT / "results" / "SUMMARY.md"
before = summ.read_text(encoding="utf-8") if summ.exists() else ""
subprocess.run([sys.executable, "scripts/make_summary.py"], cwd=ROOT, check=True)
after = summ.read_text(encoding="utf-8")
check("results/SUMMARY.md exists and is reproduced exactly by scripts/make_summary.py", bool(after) and before == after)
for table in ("baselines.md", "fusion_ablation.md", "confusion_matrices.md"):
    check(f"results/tables/{table} present", (ROOT / "results" / "tables" / table).is_file())
check("SUMMARY.md has a limitations section", "## 4. Limitations" in after)
check("README and architecture docs exist", (ROOT / "README.md").is_file() and "mermaid" in (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))
sys.exit(0 if ok else 1)
