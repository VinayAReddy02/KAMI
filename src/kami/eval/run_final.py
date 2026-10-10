"""R6: final evaluation from the frozen configuration.

    python -m kami.eval.run_final --dry-run     # whole pipeline on VALIDATION rows; no held-out file is read; throw-away output
    python -m kami.eval.run_final --rehearse    # the real code path on the two EXPOSED test sets only, throw-away logs and
                                                # output, including interruption and resume; prints no metric
    python -m kami.eval.run_final               # preflight (= dry run), then the real thing

Real run, in this order, each model evaluated ONCE per test set (counter + key hash + completion time in the log):
  test_v3   headline: fresh events (seed 20261011). Its file was loaded and featurised once by a dry run before the
            freeze; no model or metric used its test rows before this run
  test_v2   secondary: fresh events (seed 20261010). The baselines were scored on it once BEFORE the freeze by mistake
            (results/round2/incident_test_v2, docs/decisions.md); every other model is evaluated on it here for the first time
  test_v1   exposed (Round 1), reference only
  BattLeDIM test: real labels on simulated data, exposed in Round 1, cannot be refreshed

Two phases, so that nothing can go wrong between opening a test set and keeping what was obtained:
  A (access)   per model: open the test split (logged), compute the per-row predicted category, write it to
               results/round2/predictions/<set>/ at once, then mark the log entry completed. Nothing else happens here.
  B (metrics)  every number is computed from the stored predictions and the stored evaluation frame (labels, events,
               scoring mask). Phase B never opens a test set and can be repeated.
A re-run never re-opens a test set: stored predictions are reused; a model that was opened but has no stored predictions
(interrupted in between) is reported as `interrupted` and left alone unless --retry-interrupted is given, which makes a
second, separately logged access.

Refuses to run unless the frozen configuration verifies, is committed and unmodified, and belongs to the stored results.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ..models.fusion import CATS, macro_f1
from .access import SplitData, final_evaluation, is_logged, mark_completed
from .bootstrap import N_BOOT, SEED, intervals, replicates
from .data import LOCKED_LOGS, RES, ROOT, load_dataset
from .fast_eval import AnyEvaluator
from .final_models import baseline_models, fusion_models, joint_model, scenario_models
from .freeze import CONFIG, TRACKED, verify
from .fusion_tune import fusion_mask
from .metrics import domain_events, evaluate
from .round2_data import any_events_from_frame, attach_evidence, battledim_frame, load_modules
from .run_evidence import events_for
from .run_fusion import build_frame, confusion
from .verdict import VOTE, decide

OUT = RES / "round2"
FRAME_COLS = ["node_id", "ts", "y", "any_flag", "infra_flag", "quality_flag", "event_id", "event_type"]
REAL_SETS = [("scenarios_v3", "test_v3"), ("scenarios_v2", "test_v2"), ("scenarios", "test_v1_exposed"),
             ("battledim", "battledim_test_previously_exposed")]
DRY_SETS = [("scenarios", "val_scenarios"), ("battledim", "val_battledim")]
REHEARSE_SETS = [("scenarios", "test_v1_exposed"), ("battledim", "battledim_test_previously_exposed")]
RETRY_SUFFIX = " [second access after an interrupted first access]"
NOTES = {
    "test_v3": "HEADLINE. Fresh scenario test events (seed 20261011), generated after the test_v2 incident. Frozen first, "
               "then every model evaluated exactly once. Its file was loaded and featurised once by a dry run before the "
               "freeze; no model or metric used its test rows before the final run.",
    "test_v2": "SECONDARY. Fresh scenario test events (seed 20261010). The baselines (fixed_threshold, isolation_forest, ocsvm) "
               "were scored on this set once before the freeze by mistake, so their rows here are a second access; all other "
               "models are evaluated on it here for the first time.",
    "test_v1_exposed": "Round-1 scenario test events; exposed for F-B. Reference only.",
    "battledim_test_previously_exposed": "BattLeDIM test split (8 events); exposed for F-B in Round 1, cannot be refreshed. "
                                         "Infrastructure evidence only. Decision parameters were tuned on the BattLeDIM "
                                         "validation split with the same procedure and cap.",
}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _prf(tp: float, fp: float, fn: float) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0}


def full_metrics(df: pd.DataFrame, events: pd.DataFrame, pred: np.ndarray, mask: np.ndarray, kind: str) -> tuple[dict, dict]:
    """All reported numbers for one model on one evaluation frame, and its bootstrap replicates.
    `pred` = predicted category per row (0 Normal, 1 Infrastructure, 2 Quality, 3 Combined)."""
    pred = np.where(mask, np.asarray(pred, int), 0)
    ev = AnyEvaluator(df, events, mask)
    d = ev(pred > 0, details=True)
    cat_ok, types = ev.category_correct(pred)
    det = d.pop("detail")
    reps = replicates(det, cat_ok, n=N_BOOT, seed=SEED)
    y = df.y.to_numpy()
    cm = np.array(confusion(y[mask], pred[mask]))
    alert, truth = pred[mask] > 0, y[mask] > 0
    event = {k: d[k] for k in ("f1_event_counted", "precision_event_counted", "recall", "fa_per_day", "f1", "precision",
                               "latency_median_h", "latency_p90_h")}
    event.update(events=int(d["events"]), detected_events=int(d["detected"]), alert_segments=int(d["segments"]),
                 true_segments=int(d["true_segments"]), false_segments=int(d["false_segments"]))
    out = {
        "status": "ok",
        "event": event,
        "ci95": intervals(reps),
        "category_accuracy_event": float(cat_ok.mean()) if len(cat_ok) else 0.0,
        "per_type": {str(t): {"events": int((types == t).sum()), "detected_recall": float(det["event_detected"][types == t].mean()),
                              "category_correct": float(cat_ok[types == t].mean())} for t in sorted(set(types))},
        "per_category_point_recall": {CATS[i]: (float(cm[i, i] / cm[i].sum()) if cm[i].sum() else None) for i in range(4)},
        "point_any_alert": _prf(float((alert & truth).sum()), float((alert & ~truth).sum()), float((~alert & truth).sum())),
        "macro_f1": macro_f1(y[mask], pred[mask]), "point_accuracy": float((y[mask] == pred[mask]).mean()),
        "confusion": cm.tolist(), "scored_rows": int(mask.sum()),
        # the event metrics ignore alert duration, so the time spent in alert is reported next to them
        "alert_row_fraction": float(d["alert_fraction"]), "normal_rows_in_alert_fraction": float(d["normal_alert_fraction"]),
    }
    infra_events = events if kind == "battledim" else domain_events(df, "infra")
    out["infra_domain_event_f1"] = evaluate(df, np.isin(pred, [1, 3]), "infra", events=infra_events, scored=mask)["event"]["f1_event_counted"]
    if kind != "battledim":
        out["quality_domain_event_f1"] = evaluate(df, np.isin(pred, [2, 3]), "quality", events=domain_events(df, "quality"),
                                                  scored=mask)["event"]["f1_event_counted"]
    return out, reps


class Runner:
    def __init__(self, frozen: dict, mode: str, base: Path, logs: dict, retry_interrupted: bool = False, quiet: bool = False):
        self.frozen, self.mode, self.base, self.logs = frozen, mode, base, logs
        self.split = "val" if mode == "dry" else "test"
        self.retry, self.quiet = retry_interrupted, quiet
        self.out_path, self.pred_dir = base / "final_results.json", base / "predictions"
        self.modules = load_modules()
        self.interrupted: dict[str, list[str]] = {}
        self.second_access: dict[str, list[str]] = {}
        if self.out_path.exists():
            old = json.loads(self.out_path.read_text(encoding="utf-8"))
            if old.get("frozen_files_list_sha256") != frozen["files_list_sha256"]:
                raise SystemExit("existing final_results.json was produced under a different frozen configuration. Refusing to resume.")
            self.second_access = old.get("second_access_after_interruption", {})

    # ------------------------------------------------------------------ phase A: access, predict, store
    def _frame(self, data: SplitData, model_id: str, dataset: str) -> pd.DataFrame:
        if self.mode == "dry":
            return data.val()
        with final_evaluation(model_id, dataset, self.logs[dataset]):
            return data.test()

    def access_set(self, dataset: str, key: str, models: dict, data: SplitData, prepare) -> None:
        d = self.pred_dir / key
        cache = None
        for name, fn in models.items():
            pfile = d / f"{slug(name)}.npz"
            if pfile.exists():
                continue  # already evaluated: stored predictions are reused, the test set is not opened again
            model_id = name
            if self.mode != "dry" and is_logged(name, dataset, self.logs[dataset]):
                # opened in an earlier run, but no predictions were stored
                if not self.retry or is_logged(name + RETRY_SUFFIX, dataset, self.logs[dataset]):
                    self.interrupted.setdefault(key, []).append(name)
                    print(f"  [{key}] {name}: opened earlier without a stored result; NOT re-opened", flush=True)
                    continue
                model_id = name + RETRY_SUFFIX
                if name not in self.second_access.setdefault(key, []):
                    self.second_access[key].append(name)
            raw = self._frame(data, model_id, dataset)
            if cache is None:
                df, events, mask = prepare(raw)
                cache = (df, mask)
                if not (d / "frame.parquet").exists():
                    d.mkdir(parents=True, exist_ok=True)
                    keep = df[FRAME_COLS + (["ambiguous"] if "ambiguous" in df else [])].assign(mask=mask)
                    keep.to_parquet(d / "frame.parquet.tmp")
                    os.replace(d / "frame.parquet.tmp", d / "frame.parquet")
                    _atomic_write(d / "events.csv", events.to_csv(index=False).encode("utf-8"))
            df, mask = cache
            pred = np.where(mask, np.asarray(fn(df), int), 0).astype(np.int8)
            tmp = d / f"{slug(name)}.tmp.npz"
            np.savez_compressed(tmp, pred=pred, model=np.array(name))
            os.replace(tmp, pfile)
            if self.mode != "dry":
                mark_completed(model_id, dataset, self.logs[dataset], rows=int(len(pred)))
            print(f"  [{key}] {name}: predictions stored", flush=True)

    # ------------------------------------------------------------------ phase B: metrics from the stored predictions
    def metrics_set(self, key: str, model_names: list[str], kind: str) -> tuple[dict, dict]:
        d = self.pred_dir / key
        res, reps = {}, {}
        if not (d / "frame.parquet").exists():
            return res, reps
        df = pd.read_parquet(d / "frame.parquet")
        mask = df["mask"].to_numpy(bool)
        events = pd.read_csv(d / "events.csv", parse_dates=["start", "end"])
        for name in model_names:
            pfile = d / f"{slug(name)}.npz"
            if not pfile.exists():
                continue
            pred = np.load(pfile)["pred"].astype(int)
            res[name], reps[name] = full_metrics(df, events, pred, mask, kind)
            if not self.quiet:
                r = res[name]
                c = r["ci95"]["f1_event_counted"]
                print(f"  [{key}] {name:45s} event-counted F1 {r['event']['f1_event_counted']:.3f} [{c[0]:.3f}, {c[1]:.3f}] "
                      f"(segment-based {r['event']['f1']:.3f}) FA/day {r['event']['fa_per_day']:.2f} "
                      f"rows in alert {100 * r['alert_row_fraction']:.1f}% cat.acc {r['category_accuracy_event']:.3f}", flush=True)
        return res, reps

    def finish(self, sets: list[tuple[str, str, list[str], str]]) -> dict:
        results, verdicts = {}, {}
        sel, cap = self.frozen["selected_design"], self.frozen["false_alarm_cap_per_day"]
        for _, key, names, kind in sets:
            res, reps = self.metrics_set(key, names, kind)
            for name in self.interrupted.get(key, []):
                res[name] = {"status": "interrupted", "note": "the test split was opened for this model in an earlier run that "
                             "stopped before its predictions were stored; it was not opened again"}
            for name in self.second_access.get(key, []):
                if name in res and res[name].get("status") == "ok":
                    res[name]["access_count"] = 2
            results[key] = res
            if sel in reps and VOTE in reps:
                verdicts[key] = decide(res[sel], res[VOTE], reps[sel], reps[VOTE], cap)
        out = {"frozen_commit": self.frozen["git_commit"], "frozen_files_list_sha256": self.frozen["files_list_sha256"],
               "selected_design": sel, "headline_test_set": "test_v3", "false_alarm_cap_per_day": cap,
               "bootstrap": {"resamples": N_BOOT, "seed": SEED,
                             "method": "events resampled for recall, precision, F1 and category accuracy (true segments stay "
                                       "with their event); whole days resampled for false alarms; same draws for every model "
                                       "on a set; percentile intervals"},
               "verdict_rule": self.frozen["verdict_rule"], "verdicts": verdicts,
               "split_evaluated": self.split, "mode": self.mode, "results": results, "notes": NOTES,
               "second_access_after_interruption": self.second_access}
        _atomic_write(self.out_path, json.dumps(out, indent=2, default=float).encode("utf-8"))
        return out


def _git(*a) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.rstrip("\n")


def require_committed_freeze() -> None:
    """The frozen configuration must be in git, unmodified, and the frozen inputs must have no uncommitted change."""
    rel = str(CONFIG.relative_to(ROOT)).replace("\\", "/")
    if not _git("log", "-1", "--format=%H", "--", rel):
        raise SystemExit(f"{rel} is not committed. Commit the frozen configuration before opening a test set.")
    dirty = [ln for ln in _git("status", "--porcelain", "--", rel, *TRACKED).splitlines() if not ln.endswith("test_eval_log.json")]
    if dirty:
        raise SystemExit("uncommitted changes in the frozen configuration or its inputs:\n  " + "\n  ".join(dirty))


def run(mode: str, base: Path | None = None, retry_interrupted: bool = False, quiet: bool = False) -> dict:
    """mode: 'dry' (validation rows), 'rehearse' (exposed test sets, temp logs) or 'real'."""
    t0 = time.time()
    frozen = verify()
    if mode == "real":
        require_committed_freeze()
    base = base or (OUT if mode == "real" else Path(tempfile.mkdtemp(prefix=f"kami_{mode}_")))
    if mode == "real":
        logs = {"scenarios_v3": LOCKED_LOGS["scenarios_v3"], "scenarios_v2": LOCKED_LOGS["scenarios_v2"],
                "scenarios": OUT / "test_v1_eval_log.json", "battledim": OUT / "battledim_test_eval_log.json"}
    else:
        logs = {"scenarios": base / "test_v1_eval_log.json", "battledim": base / "battledim_test_eval_log.json"}
    sets = {"dry": DRY_SETS, "rehearse": REHEARSE_SETS, "real": REAL_SETS}[mode]
    print(f"[{mode}] frozen config verified (commit {frozen['git_commit'][:10]}, design {frozen['selected_design']}); output {base}", flush=True)
    runner = Runner(frozen, mode, base, logs, retry_interrupted, quiet)

    sc_val = build_frame("scenarios")
    sc_val = sc_val[sc_val.split == "val"]  # the only rows used to fit F-A's regression (scenario validation)
    sc_models = scenario_models(frozen, sc_val)
    bd = battledim_frame()
    bd_models = fusion_models(frozen, bd[bd.split == "val"], "battledim_designs")
    bd_feat = load_dataset("battledim")
    bd_models["single joint model (no separated evidence)"] = joint_model(bd_feat, "battledim")
    bd_models.update(baseline_models("battledim", bd_feat, ["infra"]))
    print(f"[{mode}] models built: {len(sc_models)} scenario, {len(bd_models)} BattLeDIM ({time.time() - t0:.0f}s)", flush=True)

    def scenario_prepare(raw):
        df = attach_evidence(raw, runner.split, runner.modules).reset_index(drop=True)
        return df, any_events_from_frame(df), fusion_mask(df)

    def battledim_prepare(raw):
        df = raw.reset_index(drop=True)
        return df, events_for("battledim", df, "infra"), fusion_mask(df)

    plan = []
    for dataset, key in sets:
        if dataset == "battledim":
            runner.access_set(dataset, key, bd_models, SplitData(bd, "battledim"), battledim_prepare)
            plan.append((dataset, key, list(bd_models), "battledim"))
        else:
            # a held-out file is loaded only here, in a real run, after the freeze has been verified
            runner.access_set(dataset, key, sc_models, SplitData(load_dataset(dataset), dataset), scenario_prepare)
            plan.append((dataset, key, list(sc_models), "scenarios"))
    out = runner.finish(plan)
    print(f"[{mode}] wrote {runner.out_path} in {time.time() - t0:.0f}s", flush=True)
    return out


def rehearse() -> bool:
    """Exercise the real code path (final_evaluation + test split, storing, resume, interruption) on the two exposed test
    sets with throw-away logs. Prints PASS/FAIL lines and no metric."""
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name, flush=True)
        ok &= bool(cond)

    def logs_of(base):
        return {k: json.loads((base / f).read_text(encoding="utf-8"))
                for k, f in (("scenarios", "test_v1_eval_log.json"), ("battledim", "battledim_test_eval_log.json"))}

    def same(a, b):
        return json.dumps(a, sort_keys=True, default=float) == json.dumps(b, sort_keys=True, default=float)

    base = Path(tempfile.mkdtemp(prefix="kami_rehearsal_"))
    first = run("rehearse", base, quiet=True)
    n = {k: len(v) for k, v in first["results"].items()}
    check(f"first pass: every model evaluated on both exposed sets {n}",
          all(r.get("status") == "ok" for v in first["results"].values() for r in v.values()) and min(n.values()) >= 7)
    logs = logs_of(base)
    check("every access is logged once and marked completed", all("completed_utc" in r for lg in logs.values() for r in lg)
          and all(len({r["key"] for r in lg}) == len(lg) for lg in logs.values()))
    second = run("rehearse", base, quiet=True)
    check("second pass opens nothing (logs unchanged) and reproduces identical results",
          logs_of(base) == logs and same(second["results"], first["results"]) and same(second["verdicts"], first["verdicts"]))
    # simulate an interruption after the access was logged but before the predictions were stored
    (base / "predictions" / "test_v1_exposed" / f"{slug(VOTE)}.npz").unlink()
    third = run("rehearse", base, quiet=True)
    check("an interrupted model is reported as interrupted and NOT re-opened",
          third["results"]["test_v1_exposed"][VOTE].get("status") == "interrupted" and logs_of(base) == logs)
    check("no verdict is produced when one of the two compared models is missing", "test_v1_exposed" not in third["verdicts"])
    fourth = run("rehearse", base, retry_interrupted=True, quiet=True)
    logs4 = logs_of(base)
    check("--retry-interrupted makes one extra, separately logged access and flags the row",
          len(logs4["scenarios"]) == len(logs["scenarios"]) + 1 and logs4["scenarios"][-1]["model"].endswith(RETRY_SUFFIX)
          and fourth["results"]["test_v1_exposed"][VOTE].get("access_count") == 2
          and fourth["results"]["test_v1_exposed"][VOTE]["event"] == first["results"]["test_v1_exposed"][VOTE]["event"])
    fifth = run("rehearse", base, retry_interrupted=True, quiet=True)
    check("a further run makes no further access", logs_of(base) == logs4
          and fifth["results"]["test_v1_exposed"][VOTE].get("access_count") == 2)
    check("verdict block present for both sets", set(fourth["verdicts"]) == {"test_v1_exposed", "battledim_test_previously_exposed"})
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="validation rows only, throw-away output, no held-out file is read")
    ap.add_argument("--rehearse", action="store_true", help="real code path on the exposed test sets only, throw-away logs")
    ap.add_argument("--retry-interrupted", action="store_true",
                    help="real run only: make a second, separately logged access for models whose first access was interrupted")
    ap.add_argument("--out", default=None, help="dry run only: directory for the throw-away output")
    a = ap.parse_args()
    if a.dry_run:
        run("dry", Path(a.out) if a.out else None)
    elif a.rehearse:
        raise SystemExit(0 if rehearse() else 1)
    else:
        print("preflight: complete pipeline on validation rows (no held-out file is read)", flush=True)
        run("dry", quiet=True)
        print("preflight passed; opening the test sets", flush=True)
        run("real", retry_interrupted=a.retry_interrupted)
