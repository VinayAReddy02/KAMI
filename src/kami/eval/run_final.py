"""R6: final evaluation from the frozen configuration. Each model is evaluated ONCE on test_v2 (logged with a counter and
hash). Also: BattLeDIM test (flagged "previously exposed for F-B") and test_v1 (exposed, reference only).

    python -m kami.eval.run_final                 # real run: test_v2, BattLeDIM test, test_v1
    python -m kami.eval.run_final --dry-run       # pipeline check on the VALIDATION split with a throw-away log

Refuses to run if the frozen configuration does not match the files on disk.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

import numpy as np

from ..models.fusion import CATS
from .access import SplitData, final_evaluation
from .bootstrap import bootstrap_any
from .data import RES, load_dataset
from .fast_eval import AnyEvaluator
from .final_models import baseline_models, fusion_models, joint_model, scenario_models
from .freeze import verify
from .metrics import domain_events, evaluate
from .round2_data import any_events_from_frame, attach_evidence, load_modules
from .run_evidence import events_for
from .run_fusion import build_frame, confusion, fusion_mask as fmask_named
from ..models.fusion import macro_f1

OUT = RES / "round2"
LOG_V2 = OUT / "test_v2_eval_log.json"
LOG_V1 = OUT / "test_v1_eval_log.json"
LOG_BD = OUT / "battledim_test_eval_log.json"


def full_metrics(df, events, pred, mask, name_kind: str, seed: int) -> dict:
    ev = AnyEvaluator(df, events, mask)
    pred = np.where(mask, pred, 0)
    d = ev(pred > 0, details=True)
    cat_ok, types = ev.category_correct(pred)
    ci = bootstrap_any(d, cat_ok, seed=seed)
    y = df.y.to_numpy()
    conf = confusion(y[mask], pred[mask])
    cm = np.array(conf)
    recall_cat = {CATS[i]: (float(cm[i, i] / cm[i].sum()) if cm[i].sum() else None) for i in range(4)}
    per_type = {}
    for t in sorted(set(types)):
        sel = types == t
        per_type[t] = {"events": int(sel.sum()), "detected_recall": float(d["detected"][sel].mean()),
                       "category_correct": float(cat_ok[sel].mean())}
    out = {
        "event": {"f1": d["f1"], "precision": d["precision"], "recall": d["recall"], "fa_per_day": d["fa_per_day"],
                  "latency_median_h": d["latency_median_h"], "events": int(d["events"]), "alert_segments": int(d["segments"])},
        "ci95": ci,
        "category_accuracy_event": float(cat_ok.mean()) if len(cat_ok) else 0.0,
        "per_type": per_type, "per_category_point_recall": recall_cat,
        "macro_f1": macro_f1(y[mask], pred[mask]), "point_accuracy": float((y[mask] == pred[mask]).mean()),
        "confusion": conf,
    }
    out["infra_domain_event_f1"] = evaluate(df, np.isin(pred, [1, 3]), "infra", events=domain_events(df, "infra") if name_kind != "battledim" else events,
                                            scored=mask)["event"]["f1"]
    if name_kind != "battledim":
        out["quality_domain_event_f1"] = evaluate(df, np.isin(pred, [2, 3]), "quality", events=domain_events(df, "quality"),
                                                  scored=mask)["event"]["f1"]
    return out


def battledim_models(frozen: dict, full) -> dict:
    """Frozen designs applied to the infrastructure-only BattLeDIM data (no quality stream): F-B, F-B without temporal
    features, threshold voting, the joint model and the baselines. F-A is not evaluated here (its regression would need
    refitting on BattLeDIM validation)."""
    from .fusion_tune import FusionBDesign, VotingDesign

    out = {}
    for name, d in (("F-B", FusionBDesign(True)), ("F-B (no temporal)", FusionBDesign(False)), ("threshold voting (no fusion)", VotingDesign())):
        params = tuple(frozen["designs"][name]["final_params"])
        out[name] = (lambda df, d=d, p=params: d.decide(df, p))
    out["single joint model (no separated evidence)"] = joint_model(full, "battledim")
    out.update(baseline_models("battledim", full, ["infra"]))
    return out


def run(dry: bool) -> None:
    t0 = time.time()
    frozen = verify()
    print(f"frozen config verified (commit {frozen['git_commit'][:10]}, design {frozen['selected_design']})", flush=True)
    tmp = Path(tempfile.mkdtemp())
    log_v2, log_v1, log_bd = (tmp / "v2.json", tmp / "v1.json", tmp / "bd.json") if dry else (LOG_V2, LOG_V1, LOG_BD)
    split = "val" if dry else "test"
    modules = load_modules()

    def frame_for(data: SplitData, mname: str, dataset: str, log: Path):
        if dry:
            return data.val()
        with final_evaluation(mname, dataset, log):
            return data.test()

    results = {}
    val_frame = build_frame("scenarios")
    val_frame = val_frame[val_frame.split == "val"]  # tuning/fitting rows (validation only)
    models = scenario_models(frozen, val_frame)
    print(f"models built ({len(models)}) in {time.time() - t0:.0f}s", flush=True)

    def eval_scenarios(dataset: str, log: Path, tag: str):
        full = load_dataset(dataset)
        data = SplitData(full)
        res = {}
        for mname, fn in models.items():
            raw = frame_for(data, mname, dataset, log)
            df = attach_evidence(raw, split, modules).reset_index(drop=True)
            mask = ((df.p_infra.notna()) & (df.p_quality.notna())).to_numpy()
            pred = fn(df)
            res[mname] = full_metrics(df, any_events_from_frame(df), pred, mask, "scenarios", seed=12345)
            r = res[mname]
            print(f"  [{tag}] {mname:45s} F1 {r['event']['f1']:.3f} {r['ci95']['f1']} FA/day {r['event']['fa_per_day']:.2f} "
                  f"cat.acc {r['category_accuracy_event']:.3f}", flush=True)
        return res

    results["test_v2" if not dry else "val_dry_run"] = eval_scenarios("scenarios_v2", log_v2, "v2")
    if not dry:
        results["test_v1_exposed"] = eval_scenarios("scenarios", log_v1, "v1")

    # BattLeDIM (real labels on simulated data): previously exposed for F-B, cannot be refreshed
    bd_full = build_frame("battledim")
    bd_data = SplitData(bd_full)
    bd_models = battledim_models(frozen, load_dataset("battledim"))
    bd_res = {}
    for mname, fn in bd_models.items():
        raw = frame_for(bd_data, mname, "battledim", log_bd)
        df = raw.reset_index(drop=True)
        mask = fmask_named(df, "battledim")
        events = events_for("battledim", df, "infra")
        pred = np.where(mask, fn(df), 0)
        bd_res[mname] = full_metrics(df, events, pred, mask, "battledim", seed=12345)
        r = bd_res[mname]
        print(f"  [battledim] {mname:45s} F1 {r['event']['f1']:.3f} {r['ci95']['f1']} FA/day {r['event']['fa_per_day']:.2f}", flush=True)
    results["battledim_test_previously_exposed"] = bd_res

    out = {"frozen_commit": frozen["git_commit"], "selected_design": frozen["selected_design"],
           "false_alarm_cap_per_day": frozen["false_alarm_cap_per_day"], "bootstrap": {"resamples": 1000, "seed": 12345},
           "results": results,
           "notes": {"test_v2": "fresh scenario test events (seed 20261010), evaluated once per model",
                     "test_v1_exposed": "Round-1 scenario test events; exposed for F-B, reference only",
                     "battledim_test_previously_exposed": "BattLeDIM test split; exposed for F-B, cannot be refreshed; 8 events"}}
    path = OUT / ("_dry_run.json" if dry else "final_results.json")
    path.write_text(json.dumps(out, indent=2, default=float), encoding="utf-8")
    print(f"wrote {path.name} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    run(ap.parse_args().dry_run)
