"""Exit 0 only if the Round 2 criteria hold, reading the real artefacts.

    python scripts/check_round2.py            # everything, including pytest and every check_step_N.py (slow)
    python scripts/check_round2.py --quick    # Round 2 artefact checks only

Known, documented exception (reported, never hidden): the baselines were scored on test_v2 once before the freeze.
The clean-protocol criteria (frozen before first access, one evaluation per model) are therefore checked on test_v3,
the headline set, and test_v2 is checked for what is actually true of it.
"""
import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
R = ROOT / "results"
VOTE = "threshold voting (no fusion)"
ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name, flush=True)
    ok &= bool(cond)
    return bool(cond)


def git(*a, code=False):
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    return r.returncode if code else r.stdout.rstrip("\n")


def jload(p):
    return json.loads((R / p).read_text(encoding="utf-8"))


def ts(s):
    return datetime.datetime.fromisoformat(s)


def good(r):
    return r.get("status") == "ok"


ap = argparse.ArgumentParser()
ap.add_argument("--quick", action="store_true")
args = ap.parse_args()

# ---------------------------------------------------------------- R0, R1
check("R0 tag round1 exists", git("tag", "-l", "round1") == "round1")
check("R0 results_round1/ copy exists", (ROOT / "results_round1" / "SUMMARY.md").is_file())
for v, seed in (("v2", 20261010), ("v3", 20261011)):
    i = jload(f"splits/test_{v}_info.json")
    check(f"R1 test_{v}: recorded seed {seed}, same seed gives identical hash, no event crosses a split boundary, "
          f"12 events per type, train/val identical to Round 1, no event identical to a test_v1 event",
          i[f"seed_{v}"] == seed and i["same_seed_identical"] and i["no_straddle"] and set(i["events_per_type"].values()) == {12}
          and i["train_val_identical_to_v1"] and i["v1_identical_events"] == 0)

# ---------------------------------------------------------------- R2 and the freeze
from kami.eval.freeze import TRACKED, verify  # noqa: E402

sel = jload("round2/selection_val.json")
frozen = jload("fusion/frozen_config.json")
fin = jload("round2/final_results.json")
check("R2 selection on validation: 5 rules tuned under the 0.5/day cap on scenarios and on BattLeDIM, a fusion design selected",
      len(sel["designs"]) == 5 and len(sel["battledim"]["designs"]) == 5 and sel["cap_false_alarms_per_day"] == 0.5
      and sel["selected"] in ("F-A", "F-B") and "event-counted" in sel["objective"])
try:
    verify()  # every hashed input file, the file list, every parameter block against its source, the verdict rule
    unchanged = True
except SystemExit as e:
    print("   ", e)
    unchanged = False
check("R2/R6 frozen config verifies: inputs unchanged on disk, parameters equal their validation sources, verdict rule intact", unchanged)
check("R2 frozen config names test_v3 as the headline set and fixes the reporting rule",
      frozen.get("headline_test_set") == "test_v3" and "test_v2" in frozen.get("reporting_rule", ""))

log3 = jload("round2/test_v3_eval_log.json")
log2 = jload("round2/test_v2_eval_log.json")
first3, first2 = min(ts(r["utc"]) for r in log3), min(ts(r["utc"]) for r in log2)
commit_time = datetime.datetime.fromtimestamp(int(git("show", "-s", "--format=%ct", frozen["git_commit"])), datetime.timezone.utc)
last = git("log", "-1", "--format=%ct", "--", "results/fusion/frozen_config.json")  # last commit that touched the file
dirty = git("status", "--porcelain", "--", "results/fusion/frozen_config.json")
cfg_commit_time = datetime.datetime.fromtimestamp(int(last), datetime.timezone.utc) if last and not dirty else None
print(f"    frozen code commit {frozen['git_commit'][:10]} at {commit_time.isoformat()}; config last committed "
      f"{cfg_commit_time.isoformat() if cfg_commit_time else 'NOT COMMITTED OR MODIFIED'}; first test_v3 access {first3.isoformat()}")
check("R2 frozen config: recorded commit and creation time predate the first test_v3 access",
      commit_time <= first3 and ts(frozen["created_utc"]) <= first3)
check("R2 frozen config file was last committed before the first test_v3 access and is unmodified since",
      cfg_commit_time is not None and cfg_commit_time <= first3)
# Round 3 adds live/notification code under src/kami that is not an input of the evaluation. The comparison therefore
# covers the frozen inputs themselves (the folders hashed by eval/freeze.py), not the whole of src/kami.
assert "src/kami" in TRACKED
paths = ["src/kami/models", "src/kami/features", "src/kami/eval", "src/kami/data", "src/kami/simulator/scenarios.py"]     + [p for p in TRACKED if p != "src/kami"]
check("R2 the tracked frozen inputs are byte-for-byte what the recorded commit contains (git diff against it is empty)",
      git("diff", "--quiet", frozen["git_commit"], "--", *paths, ":(exclude)results/baselines/test_eval_log.json", code=True) == 0)
check("R6 final results were produced under this frozen configuration",
      fin["frozen_commit"] == frozen["git_commit"] and fin["frozen_files_list_sha256"] == frozen["files_list_sha256"]
      and fin["verdict_rule"] == frozen["verdict_rule"] and fin["mode"] == "real" and fin["split_evaluated"] == "test")

# ---------------------------------------------------------------- R6 logs and stored predictions
res3, res2 = fin["results"]["test_v3"], fin["results"]["test_v2"]
m3 = sorted(res3)
check(f"R6 test_v3 log: exactly one evaluation per model ({len(m3)} models), each with counter, key hash and completion time",
      sorted(r["model"] for r in log3) == m3 and len({r["key"] for r in log3}) == len(log3)
      and [r["count"] for r in log3] == list(range(1, len(log3) + 1)) and all(r["dataset"] == "scenarios_v3" for r in log3)
      and all("completed_utc" in r for r in log3))
check("R6 test_v3: every model has a completed evaluation (none interrupted, none opened twice)",
      all(good(r) for r in res3.values()) and not fin.get("second_access_after_interruption", {}).get("test_v3"))
check("R6 test_v2 log: exactly one evaluation per model after the freeze, all completed",
      sorted(r["model"] for r in log2) == sorted(res2) and len({r["key"] for r in log2}) == len(log2) and commit_time <= first2
      and all("completed_utc" in r for r in log2) and all(good(r) for r in res2.values()))
stray = []
for p in R.rglob("*eval_log*.json"):
    if "incident_test_v2" in p.parts or p.name in ("test_v3_eval_log.json", "test_v2_eval_log.json"):
        continue
    stray += [f"{p.relative_to(R)}:{r['model']}" for r in json.loads(p.read_text(encoding="utf-8"))
              if r["dataset"] in ("scenarios_v2", "scenarios_v3")]
check("R6 no other log shows an access to test_v2 or test_v3", not stray)
from kami.eval.run_final import slug  # noqa: E402

missing = [f"{k}/{m}" for k, res in fin["results"].items() for m, r in res.items()
           if good(r) and not (R / "round2" / "predictions" / k / f"{slug(m)}.npz").is_file()]
check("R6 per-row predictions and the evaluation frame are stored for every evaluated model (metrics can be recomputed without a new access)",
      not missing and all((R / "round2" / "predictions" / k / "frame.parquet").is_file() for k in fin["results"]))

# the documented exception
inc = jload("round2/incident_test_v2/incident.json")
dec = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
summ = (R / "SUMMARY.md").read_text(encoding="utf-8")
before = ts(inc["last_access_utc"]) < ts(frozen["created_utc"])
print(f"    KNOWN EXCEPTION: {inc['accesses']} baseline accesses to test_v2 at {inc['first_access_utc'][:19]} UTC, before the freeze "
      f"({'confirmed by timestamps' if before else 'TIMESTAMPS DO NOT CONFIRM'}); the criteria 'frozen before first access' and "
      f"'once per model' do NOT hold for the baselines on test_v2.")
check("incident is documented in docs/decisions.md, in results/SUMMARY.md and by a kept evidence folder",
      "INCIDENT" in dec and "Incident" in summ and "test_v2" in summ and len(inc["evidence_files"]) >= 9 and before)
check("incident touched baselines only (no fusion design, voting rule or the single joint classifier)",
      all(m.split("-")[0] in ("fixed_threshold", "isolation_forest", "ocsvm") for m in inc["models"]))
check("the test_v3 decision, the user's approval and the dry-run loading of the test_v3 file are recorded in docs/decisions.md",
      "test_v3" in dec and "20261011" in dec and "User approval" in dec and "loaded and featurised" in dec)

# ---------------------------------------------------------------- R3, R4, intervals, verdict
tmp = jload("round2/temporal_ablation.json")
check("R3 temporal ablation: 5 seeds, 4 variants each, a plain verdict per design family",
      len(tmp["seeds"]) == 5 and len(tmp["rows"]) == 20 and set(tmp["verdict"]) == {"F-A", "F-B"})
oc = sorted(p.name for p in (R / "baselines").glob("*__ocsvm.json"))
check("R4 One-Class SVM rows exist in the baselines and in every final table",
      len(oc) == 3 and all("baseline: ocsvm" in fin["results"][k] for k in fin["results"]))
need_ci = ("f1_event_counted", "precision_event_counted", "recall", "fa_per_day", "category_accuracy", "f1", "precision")
bad = [(k, m, x) for k, res in fin["results"].items() for m, r in res.items() if good(r) for x in need_ci
       if not (isinstance(r["ci95"].get(x), list) and len(r["ci95"][x]) == 2 and r["ci95"][x][0] <= r["ci95"][x][1])]
check("R6 bootstrap 95% CIs exist for every headline metric of every evaluated model on every test set", not bad)
if bad:
    print("   ", bad[:5])
check("R6 bootstrap settings: 1000 resamples, fixed seed", fin["bootstrap"]["resamples"] == 1000 and isinstance(fin["bootstrap"]["seed"], int))
check("R6 all four result sets present (test_v3 headline, test_v2, test_v1 exposed, BattLeDIM exposed)",
      set(fin["results"]) == {"test_v3", "test_v2", "test_v1_exposed", "battledim_test_previously_exposed"}
      and fin["headline_test_set"] == "test_v3")
v = fin["verdicts"].get("test_v3", {})
check("R6 a verdict from the frozen rule exists for test_v3 (paired interval of the event-counted F1 difference)",
      v.get("outcome") in ("beats", "higher_f1_but_above_cap", "worse", "no_detectable_difference")
      and len(v.get("paired_ci95", {}).get("f1_event_counted", {}).get("ci95", [])) == 2)

# ---------------------------------------------------------------- R7 summary
first_par = summ.split("\n\n")[1] if "\n\n" in summ else ""
states = "does NOT beat threshold voting" in first_par or "beats threshold voting" in first_par
agrees = ("does NOT beat threshold voting" not in first_par) == (v.get("outcome") == "beats")
check("R7 the first paragraph of SUMMARY.md states whether fusion beats threshold voting on test_v3, and agrees with the frozen verdict",
      states and agrees and "test_v3" in first_par)
sel_name = fin["selected_design"]
nums = [f"{res3[sel_name]['event']['f1_event_counted']:.3f}", f"{res3[VOTE]['event']['f1_event_counted']:.3f}"]
check(f"R7 the first paragraph quotes the test_v3 event F1 of {sel_name} and of threshold voting from final_results.json {nums}",
      all(n in first_par for n in nums))
need = ["95% CI", "Category accuracy per event", "Temporal features", "ocsvm", "exposed", "Limitations", "test_v2 (secondary)",
        "Rows in alert", "Segment-based", "Met the cap on validation"]
missing = [n for n in need if n not in summ]
check(f"R7 SUMMARY.md has the CI tables, category table, temporal verdict, OCSVM rows, exposed tables, alert-time columns and limitations {missing or ''}",
      not missing)
subprocess.run([sys.executable, "scripts/make_summary.py"], cwd=ROOT, capture_output=True)
check("R7 SUMMARY.md is reproduced exactly by scripts/make_summary.py (reads from files)",
      (R / "SUMMARY.md").read_text(encoding="utf-8") == summ)

# ---------------------------------------------------------------- everything from Round 1 still passes
if not args.quick:
    t = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings"], cwd=ROOT, capture_output=True, text=True)
    print("   ", t.stdout.strip().splitlines()[-1] if t.stdout.strip() else "")
    check("pytest -q passes", t.returncode == 0)
    for n in range(8):
        r = subprocess.run([sys.executable, f"scripts/check_step_{n}.py"], cwd=ROOT, capture_output=True, text=True)
        check(f"scripts/check_step_{n}.py still passes", r.returncode == 0)
        for ln in r.stdout.splitlines():
            if ln.startswith("FAIL"):
                print("     ", ln)
    try:
        verify()
        still = True
    except SystemExit as e:
        print("   ", e)
        still = False
    check("frozen files are still unchanged after re-running every Round 1 check (they regenerate identically)", still)
    check("SUMMARY.md unchanged by the re-run", (R / "SUMMARY.md").read_text(encoding="utf-8") == summ)
sys.exit(0 if ok else 1)
