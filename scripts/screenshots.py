"""Regenerate the dashboard screenshots for the paper (and, with --a11y, the accessibility report).

    python scripts/screenshots.py            # results/screens/*.png and manifest.json (16 files: 4 pages x 2 themes x 2 sizes)
    python scripts/screenshots.py --a11y     # also results/a11y/axe_report.json and axe_report.md

Builds the frontend, then runs the Playwright specs in frontend/e2e/. They start their own demo server
(scripts/e2e_server.py), which is locked to dry run and cannot reach Telegram. Needs: npm install in frontend/ and
`npx playwright install chromium` once. The map background needs internet access (OpenStreetMap tiles).
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a11y", action="store_true", help="also run the axe-core scan and rewrite results/a11y/")
    a = ap.parse_args()
    npm, npx = shutil.which("npm"), shutil.which("npx")
    if not npm or not npx:
        print("npm/npx not found: install Node.js first")
        return 1
    env = {k: v for k, v in os.environ.items() if k != "KAMI_E2E_OUT"}  # write into results/
    if subprocess.run([npm, "run", "build"], cwd=FRONTEND, env=env).returncode != 0:
        return 1
    specs = ["screens"] + (["a11y"] if a.a11y else [])
    code = subprocess.run([npx, "playwright", "test", *specs], cwd=FRONTEND, env=env).returncode
    if code == 0:
        shots = sorted((ROOT / "results" / "screens").glob("*.png"))
        print(f"{len(shots)} screenshots in results/screens/" + ("; accessibility report in results/a11y/" if a.a11y else ""))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
