"""R6: final evaluation from the frozen configuration.

    python -m kami.eval.run_final --dry-run   # whole pipeline on the VALIDATION split, throw-away output, no test access
    python -m kami.eval.run_final             # preflight on validation, then the real thing

Real run, in this order, each model evaluated ONCE per test set (counter + key hash in the designated log):
  test_v3   headline: fresh events (seed 20261011), never opened before the freeze
  test_v2   secondary: fresh events (seed 20261010). The three baselines were scored on it once BEFORE the freeze by
            mistake (results/round2/incident_test_v2, docs/decisions.md); every other model opens it here for the first time
  test_v1   exposed (Round 1), reference only
  BattLeDIM test: real labels on simulated data, previously exposed for F-B, cannot be refreshed

Safety: refuses to run if the frozen configuration does not match the files on disk; runs the complete metric pipeline on
validation first (preflight) so that a code error cannot strike after a test set has been opened; saves results after
every model; on a re-run, models already evaluated are skipped, never re-opened.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import numpy as np

from ..models.fusion import CATS, macro_f1
from .access import SplitData, final_evaluation
from .bootstrap import bootstrap_any
from .data import LOCKED_LOGS, RES, load_dataset
from .fast_eval import AnyEvaluator
from .final_models import baseline_models, fusion_models, joint_model, scenario_models
from .freeze import verify
from .metrics import domain_events, evaluate
from .round2_data import any_events_from_frame, attach_evidence, load_modules
from .run_evidence import events_for
from .run_fusion import build_frame, confusion
from .run_fusion import fusion_mask as fusion_mask_named

OUT = RES / "round2"
FINAL = OUT / "final_results.json"
LOGS = {"scenarios_v3": LOCKED_LOGS["scenarios_v3"], "scenarios_v2": LOCKED_LOGS["scenarios_v2"],
        "scenarios": OUT / "test_v1_eval_log.json", "battledim": OUT / "battledim_test_eval_log.json"}
KEYS = {"scenarios_v3": "test_v3", "scenarios_v2": "test_v2", "scenarios": "test_v1_exposed",
        "battledim": "battledim_test_previously_exposed"}
BOOT_SEED = 12345
NOTES = {
    "test_v3": "HEADLINE. Fresh scenario test events (seed 20261011), generated after the test_v2 incident; frozen first, "
               "then every model evaluated exactly once.",
    "test_v2": "SECONDARY. Fresh scenario test events (seed 20261010). The baselines (fixed_threshold, isolation_forest, ocsvm) "
               "were scored on this set once before the freeze by mistake, so their rows here are a second access; all other "
               "models open it here for the first time.",
    "test_v1_exposed": "Round-1 scenario test events; exposed for F-B. Reference only.",
    "battledim_test_previously_exposed": "BattLeDIM test split (8 events); exposed for F-B in Round 1, cannot be refreshed. "
                                         "Infrastructure evidence only. Decision parameters were tuned on the BattLeDIM "
                                         "validation split with the same procedure and cap.",
}


def full_metrics(df, events, pred, mask, kind: str, seed: int = BOOT_SEED) -> dict:
    """All reported numbers for one model on one evaluation frame. `pred` = category index per row."""
    pred = np.where(mask, pred, 0)
    ev = AnyEvaluator(df, events, mask)
    d = ev(pred > 0, details=True)
    cat_ok, types = ev.category_correct(pred)
    ci = bootstrap_any(d, cat_ok, seed=seed)
    y = df.y.to_numpy()
    cm = np.array(confusion(y[mask], pred[mask]))
    out = {
        "event": {"f1": d["f1"], "precision": d["precision"], "recall": d["recall"], "fa_per_day": d["fa_per_day"],
                  "latency_median_h": d["latency_median_h"], "events": int(d["events"]), "alert_segments": int(d["segments"])},
        "ci95": ci,
        "category_accuracy_event": float(cat_ok.mean()) if len(cat_ok) else 0.0,
        "per_type": {t: {"events": int((types == t).sum()), "detected_recall": float(d["detected"][types == t].mean()),
                         "category_correct": float(cat_ok[types == t].mean())} for t in sorted(set(types))},
        "per_category_point_recall": {CATS[i]: (float(cm[i, i] / cm[i].sum()) if cm[i].sum() else None) for i in range(4)},
        "macro_f1": macro_f1(y[mask], pred[mask]), "point_accuracy": float((y[mask] == pred[mask]).mean()),
        "confusion": cm.tolist(), "scored_rows": int(mask.sum()),
        # Event metrics do not penalise alert duration (one continuous alert is a single "true" segment), so the share
        # of time spent in alert is reported next to them.
        "alert_row_fraction": float((pred[mask] > 0).mean()),
        "normal_rows_in_alert_fraction": float((pred[mask & (y == 0)] > 0).mean()) if (mask & (y == 0)).any() else None,
    }
    infra_events = events if kind == "battledim" else domain_events(df, "infra")
    out["infra_domain_event_f1"] = evaluate(df, np.isin(pred, [1, 3]), "infra", events=infra_events, scored=mask)["event"]["f1"]
    if kind != "battledim":
        out["quality_domain_event_f1"] = evaluate(df, np.isin(pred, [2, 3]), "quality", events=domain_events(df, "quality"),
                                                  scored=mask)["event"]["f1"]
    return out


def battledim_models(frozen: dict, full, val_frame) -> dict:
    """The same rules on the infrastructure-only BattLeDIM data, with the parameters frozen from the BattLeDIM
    validation tuning (thresholds do not transfer between differently calibrated evidence modules), plus the joint model
    and the baselines."""
    out = fusion_models(frozen, val_frame, "battledim_designs")
    out["single joint model (no separated evidence)"] = joint_model(full, "battledim")
    out.update(baseline_models("battledim", full, ["infra"]))
    return out


class Runner:
    def __init__(self, frozen: dict, dry: bool, out_path: Path, logs: dict):
        self.frozen, self.dry, self.out_path, self.logs = frozen, dry, out_path, logs
        self.split = "val" if dry else "test"
        self.modules = load_modules()
        self.results: dict = {}
        if out_path.exists():
            self.results = json.loads(out_path.read_text(encoding="utf-8")).get("results", {})

    def save(self) -> None:
        out = {"frozen_commit": self.frozen["git_commit"], "selected_design": self.frozen["selected_design"],
               "headline_test_set": "test_v3", "false_alarm_cap_per_day": self.frozen["false_alarm_cap_per_day"],
               "bootstrap": {"resamples": 1000, "seed": BOOT_SEED,
                             "method": "events resampled for recall and category accuracy, alert segments for precision, "
                                       "whole days for false alarms per day; percentile interval"},
               "split_evaluated": self.split, "results": self.results, "notes": NOTES}
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.out_path.write_text(json.dumps(out, indent=2, default=float), encoding="utf-8")

    def frame(self, data: SplitData, model: str, dataset: str):
        if self.dry:
            return data.val()
        with final_evaluation(model, dataset, self.logs[dataset]):
            return data.test()

    def run_set(self, dataset: str, models: dict, prepare, kind: str) -> None:
        """prepare(raw_frame) -> (df, events, mask) with evidence columns attached."""
        key = KEYS[dataset]
        res = self.results.setdefault(key, {})
        data = prepare("data")
        cache = None
        for name, fn in models.items():
            if name in res:
                print(f"  [{key}] {name}: already evaluated, skipped", flush=True)
                continue
            raw = self.frame(data, name, dataset)
            if cache is None:
                cache = prepare(raw)
            df, events, mask = cache
            res[name] = full_metrics(df, events, fn(df), mask, kind)
            self.save()
            r = res[name]
            print(f"  [{key}] {name:45s} event F1 {r['event']['f1']:.3f} [{r['ci95']['f1'][0]:.3f}, {r['ci95']['f1'][1]:.3f}] "
                  f"FA/day {r['event']['fa_per_day']:.2f} cat.acc {r['category_accuracy_event']:.3f}", flush=True)


def run(dry: bool, out_path: Path | None = None) -> None:
    t0 = time.time()
    frozen = verify()
    print(f"frozen config verified (commit {frozen['git_commit'][:10]}, design {frozen['selected_design']}, dry={dry})", flush=True)
    tmp = Path(tempfile.mkdtemp())
    out_path = out_path or ((tmp / "dry_run.json") if dry else FINAL)
    runner = Runner(frozen, dry, out_path, LOGS)

    val_frame = build_frame("scenarios")
    val_frame = val_frame[val_frame.split == "val"]  # the only rows used to fit F-A's regression (validation)
    sc_models = scenario_models(frozen, val_frame)
    bd_frame = build_frame("battledim")
    bd_models = battledim_models(frozen, load_dataset("battledim"), bd_frame[bd_frame.split == "val"])
    print(f"models built: {len(sc_models)} scenario, {len(bd_models)} BattLeDIM ({time.time() - t0:.0f}s)", flush=True)

    def scenario_prepare(dataset):
        full = load_dataset(dataset)

        def prepare(raw):
            if isinstance(raw, str):
                return SplitData(full, dataset)
            df = attach_evidence(raw, runner.split, runner.modules).reset_index(drop=True)
            mask = (df.p_infra.notna() & df.p_quality.notna()).to_numpy()
            return df, any_events_from_frame(df), mask
        return prepare

    def battledim_prepare(raw):
        if isinstance(raw, str):
            return SplitData(bd_frame, "battledim")
        df = raw.reset_index(drop=True)
        return df, events_for("battledim", df, "infra"), fusion_mask_named(df, "battledim")

    sets = ["scenarios_v3"] if dry else ["scenarios_v3", "scenarios_v2", "scenarios"]
    for dataset in sets:
        runner.run_set(dataset, sc_models, scenario_prepare(dataset), "scenarios")
    runner.run_set("battledim", bd_models, battledim_prepare, "battledim")
    runner.save()
    print(f"wrote {out_path} in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="validation split only, throw-away output, no test access")
    a = ap.parse_args()
    if a.dry_run:
        run(True)
    else:
        print("preflight: complete pipeline on the validation split (no test access)", flush=True)
        run(True)
        print("preflight passed; opening the test sets", flush=True)
        run(False)
