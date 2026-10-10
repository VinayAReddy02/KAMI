"""Frozen configuration of the Round 2 method: written after validation-only tuning and BEFORE any test_v2 access.

`build()` writes results/fusion/frozen_config.json (design, all parameters, git commit hash, sha256 of every input file).
`verify()` recomputes the hashes; the final evaluation refuses to run if anything changed.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess

from .data import ROOT, RES

CONFIG = RES / "fusion" / "frozen_config.json"
GLOBS = [
    "src/kami/models/*.py", "src/kami/features/*.py", "src/kami/eval/*.py", "src/kami/simulator/scenarios.py",
    "results/round2/selection_val.json", "results/baselines/*.json", "results/evidence/*.json",
    "data/processed/models/*.joblib", "data/processed/scenarios_semi_synthetic.parquet",
    "data/processed/scenarios_v2_semi_synthetic.parquet", "data/processed/scenarios_v3_semi_synthetic.parquet",
    "data/processed/battledim_network_semi_synthetic.parquet", "data/processed/evidence_*.parquet",
    "results/splits/*.json", "results/splits/*.csv",
]


def _files() -> list:
    out = []
    for g in GLOBS:
        out += sorted(ROOT.glob(g))
    return sorted(set(out))


def _sha(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*a) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def build() -> dict:
    sel = json.loads((RES / "round2" / "selection_val.json").read_text(encoding="utf-8"))
    files = {str(p.relative_to(ROOT)).replace("\\", "/"): _sha(p) for p in _files()}
    base = {}
    for p in sorted((RES / "baselines").glob("*__*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        base[p.name] = {"params": d["params"], "val_event_f1": d["val"]["event"]["f1"]}
    cfg = {
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_commit_utc": datetime.datetime.fromtimestamp(int(_git("show", "-s", "--format=%ct", "HEAD")),
                                                          datetime.timezone.utc).isoformat(),
        "git_dirty_files": [ln for ln in _git("status", "--porcelain").splitlines()],
        "selected_design": sel["selected"], "selection_reason": sel["selection_reason"],
        "false_alarm_cap_per_day": sel["cap_false_alarms_per_day"],
        "designs": {k: {"final_params": v["final_params"], "oof_event_f1": v["oof_event_f1"],
                        "oof_false_alarms_per_day": v["oof_false_alarms_per_day"], "feasible_at_cap": v["feasible_at_cap"]}
                    for k, v in sel["designs"].items()},
        "baselines": base,
        "headline_test_set": "test_v3",
        "test_sets": {"test_v3": {"seed": 20261011, "role": "headline: frozen first, every model evaluated once"},
                      "test_v2": {"seed": 20261010, "role": "secondary: baselines were scored on it once before the freeze "
                                                            "(results/round2/incident_test_v2); other models never opened it"},
                      "test_v1": {"seed": 42, "role": "exposed in Round 1, reference only"}},
        "reporting_rule": "Both test_v3 and test_v2 tables are reported whatever they show; the verdict uses test_v3 only; "
                          "no pooling.",
        "files_sha256": files,
        "files_list_sha256": hashlib.sha256("\n".join(f"{k} {v}" for k, v in sorted(files.items())).encode()).hexdigest(),
    }
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def verify() -> dict:
    """Load the frozen config and make sure no input file changed since the freeze."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    changed = []
    for rel, h in cfg["files_sha256"].items():
        p = ROOT / rel
        if not p.is_file() or _sha(p) != h:
            changed.append(rel)
    extra = [str(p.relative_to(ROOT)).replace("\\", "/") for p in _files()
             if str(p.relative_to(ROOT)).replace("\\", "/") not in cfg["files_sha256"]]
    if changed or extra:
        raise SystemExit(f"frozen config does not match the files on disk; changed: {changed}, new: {extra}. Refusing to run.")
    return cfg
