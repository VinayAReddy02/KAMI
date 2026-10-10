"""Writes results/round2/incident_test_v2/incident.json from the baseline log saved at the time of the incident.

It reads only the access log (model names and timestamps). It does not read the baseline result files in that folder.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "results" / "round2" / "incident_test_v2"
log = json.loads((D / "baselines_test_eval_log_at_incident.json").read_text(encoding="utf-8"))
hits = [r for r in log if r["dataset"] == "scenarios_v2"]
out = {
    "what": "The baseline runner looped over every registered dataset, which then included the held-out set scenarios_v2, "
            "and scored the baselines on test_v2 before the configuration was frozen.",
    "dataset": "scenarios_v2 (test_v2, seed 20261010)",
    "models": [r["model"] for r in hits],
    "accesses": len(hits),
    "first_access_utc": min(r["utc"] for r in hits),
    "last_access_utc": max(r["utc"] for r in hits),
    "fusion_or_voting_models_involved": False,
    "numbers_inspected_before_decision": False,
    "consequence": "For test_v2 the baselines were not frozen before first access and are evaluated twice. "
                   "test_v3 (seed 20261011) was generated as the clean headline set; test_v2 is reported as secondary.",
    "evidence_files": sorted(p.name for p in D.iterdir() if p.name != "incident.json"),
}
(D / "incident.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("models", "accesses", "first_access_utc")}, indent=2))
