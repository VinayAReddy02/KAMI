"""Frozen configuration of the Round 2 method: written after validation-only tuning and BEFORE any held-out test access.

`build()`  writes results/fusion/frozen_config.json: selected design, every parameter, the verdict rule, the git commit
           and the sha256 of every input file. It refuses to run when the tree has uncommitted changes in those inputs,
           when the tuned parameters were produced by other code or data than is on disk now, or when a held-out test
           set has already been opened (a freeze is final).
`verify()` re-hashes the inputs and re-derives the parameter blocks from their sources; the final evaluation and every
           held-out access refuse to run if anything differs.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess

from .data import LOCKED_LOGS, RES, ROOT
from .hashing import sha256_file

CONFIG = RES / "fusion" / "frozen_config.json"
FINAL = RES / "round2" / "final_results.json"
# everything the final evaluation reads or executes
GLOBS = [
    "src/kami/models/*.py", "src/kami/features/*.py", "src/kami/eval/*.py", "src/kami/data/*.py",
    "src/kami/simulator/scenarios.py",
    "results/round2/selection_val.json", "results/baselines/*.json",
    "results/splits/*.json", "results/splits/*.csv",
    "data/processed/models/evidence_*.joblib", "data/processed/evidence_scenarios.parquet",
    "data/processed/scenarios_semi_synthetic.parquet", "data/processed/scenarios_v2_semi_synthetic.parquet",
    "data/processed/scenarios_v3_semi_synthetic.parquet", "data/processed/battledim_network_semi_synthetic.parquet",
]
VOLATILE = {"test_eval_log.json"}  # access logs of the Round-1 runners: new timestamps on every re-run, not inputs
TRACKED = ["src/kami", "results/round2/selection_val.json", "results/baselines", "results/splits"]  # git-tracked inputs
# inputs of the validation tuning (run_round2_select) and of the baseline tuning (run_baselines)
TUNING_GLOBS = [
    "src/kami/eval/fusion_tune.py", "src/kami/eval/fast_eval.py", "src/kami/eval/metrics.py", "src/kami/eval/round2_data.py",
    "src/kami/eval/data.py", "src/kami/eval/run_round2_select.py", "src/kami/eval/run_fusion.py", "src/kami/eval/run_evidence.py",
    "src/kami/models/fusion.py", "src/kami/models/evidence.py", "src/kami/features/*.py", "src/kami/data/splits.py",
    "results/splits/*.json", "results/splits/battledim_events.csv",
    "data/processed/models/evidence_*.joblib", "data/processed/evidence_scenarios.parquet",
    "data/processed/scenarios_semi_synthetic.parquet", "data/processed/battledim_network_semi_synthetic.parquet",
]
BASELINE_GLOBS = [
    "src/kami/eval/run_baselines.py", "src/kami/eval/metrics.py", "src/kami/eval/data.py", "src/kami/models/baselines.py",
    "src/kami/features/causal.py", "src/kami/data/splits.py", "results/splits/scenarios.json", "results/splits/battledim.json",
    "results/splits/battledim_events.csv",
    "data/processed/scenarios_semi_synthetic.parquet", "data/processed/battledim_network_semi_synthetic.parquet",
]
VERDICT_RULE = {
    "headline_set": "test_v3",
    "metric": "event-counted F1 (the objective tuned on validation): recall = detected events / events, precision = "
              "detected events / (detected events + false alarms), each detected event counted once",
    "comparison": "paired bootstrap of F1(selected fusion design) minus F1(threshold voting): the same resampled events and "
                  "days are applied to both models (1000 resamples, seed 12345)",
    "beats": "the 95% interval of the difference lies entirely above 0 AND the fusion design's false alarms/day on that test "
             "set are within the cap",
    "worse": "the 95% interval of the difference lies entirely below 0",
    "otherwise": "no detectable difference",
    "also_reported": "the same paired difference for segment-based F1, false alarms/day and category accuracy, and the cap "
                     "status of both models; these do not change the verdict",
}


def _rel(p) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def _hash_globs(globs) -> dict:
    files = set()
    for g in globs:
        files |= {p for p in ROOT.glob(g) if p.name not in VOLATILE}
    return {_rel(p): sha256_file(p) for p in sorted(files)}


def tuning_inputs() -> dict:
    return _hash_globs(TUNING_GLOBS)


def baseline_inputs() -> dict:
    return _hash_globs(BASELINE_GLOBS)


def _git(*a) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.rstrip("\n")


def _pick(d: dict) -> dict:
    keys = ("final_params", "oof_event_f1", "oof_false_alarms_per_day", "feasible_at_cap")
    return {k: {x: v[x] for x in keys} for k, v in d.items()}


def _derived() -> dict:
    """Parameter blocks copied from their (hashed) sources; verify() re-derives them and requires equality."""
    sel = json.loads((RES / "round2" / "selection_val.json").read_text(encoding="utf-8"))
    base = {}
    for p in sorted((RES / "baselines").glob("*__*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        base[p.name] = {"params": d["params"], "val_event_f1": d["val"]["event"]["f1"],
                        "val_false_alarms_per_day": d["val"]["false_alarms_per_day"]}
    return {"selected_design": sel["selected"], "selection_reason": sel["selection_reason"],
            "false_alarm_cap_per_day": sel["cap_false_alarms_per_day"], "tuning_objective": sel["objective"],
            "designs": _pick(sel["designs"]), "battledim_designs": _pick(sel["battledim"]["designs"]), "baselines": base}


def build() -> dict:
    opened = [p.name for p in LOCKED_LOGS.values() if p.exists()] + ([FINAL.name] if FINAL.exists() else [])
    if opened:
        raise SystemExit(f"refusing to freeze: a held-out test set has already been opened ({opened}). A freeze is final.")
    sel = json.loads((RES / "round2" / "selection_val.json").read_text(encoding="utf-8"))
    if sel.get("tuning_inputs_sha256") != tuning_inputs():
        raise SystemExit("refusing to freeze: selection_val.json was tuned with different code or data than is on disk now; "
                         "re-run `python -m kami.eval.run_round2_select` first")
    prov = RES / "baselines" / "provenance.json"
    if not prov.exists() or json.loads(prov.read_text(encoding="utf-8")) != baseline_inputs():
        raise SystemExit("refusing to freeze: the baseline parameters were tuned with different code or data than is on disk "
                         "now; re-run `python -m kami.eval.run_baselines` first")
    dirty = [ln for ln in _git("status", "--porcelain", "--", *TRACKED).splitlines() if not ln.endswith("test_eval_log.json")]
    if dirty:
        raise SystemExit("refusing to freeze: uncommitted changes in the frozen inputs (commit them first):\n  " + "\n  ".join(dirty))
    files = _hash_globs(GLOBS)
    cfg = {
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_commit_utc": datetime.datetime.fromtimestamp(int(_git("show", "-s", "--format=%ct", "HEAD")),
                                                          datetime.timezone.utc).isoformat(),
        "git_tracked_inputs_clean": True,
        **_derived(),
        "joint_model": {"type": "HistGradientBoostingClassifier", "max_depth": 6, "max_iter": 150, "class_weight": "balanced",
                        "random_state": 0, "tuned_for_cap": False},
        "bootstrap": {"resamples": 1000, "seed": 12345},
        "verdict_rule": VERDICT_RULE,
        "headline_test_set": "test_v3",
        "test_sets": {"test_v3": {"seed": 20261011, "role": "headline: frozen first, every model evaluated once"},
                      "test_v2": {"seed": 20261010, "role": "secondary: baselines were scored on it once before the freeze "
                                                            "(results/round2/incident_test_v2); other models never evaluated on it"},
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
    """Load the frozen config and make sure nothing changed since the freeze: every input file, the list itself and the
    parameter blocks derived from those files. Raises SystemExit otherwise (FileNotFoundError if there is no freeze)."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    now = _hash_globs(GLOBS)
    changed = sorted(k for k, h in cfg["files_sha256"].items() if now.get(k) != h)
    extra = sorted(k for k in now if k not in cfg["files_sha256"])
    if changed or extra:
        raise SystemExit(f"frozen config does not match the files on disk; changed: {changed}, new: {extra}. Refusing to run.")
    listed = hashlib.sha256("\n".join(f"{k} {v}" for k, v in sorted(cfg["files_sha256"].items())).encode()).hexdigest()
    if listed != cfg["files_list_sha256"]:
        raise SystemExit("frozen config is inconsistent (file list hash). Refusing to run.")
    for k, v in _derived().items():
        if cfg.get(k) != v:
            raise SystemExit(f"frozen config block '{k}' differs from the hashed source it was copied from. Refusing to run.")
    if cfg.get("verdict_rule") != VERDICT_RULE:
        raise SystemExit("frozen verdict rule differs from the code. Refusing to run.")
    return cfg
