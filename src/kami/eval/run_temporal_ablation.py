"""R3: with/without temporal features across 5 scenario-generation seeds, VALIDATION period only.

For each seed a new labelled scenario set is generated (same rules, same backgrounds, seeds different from the training
seed 42 and from the test seeds). Evidence probabilities come from the Round-1 modules (trained on the train period);
their calibrators were fitted on the Round-1 validation split, so the background rows are not fresh but the events are.
For each seed the same constrained out-of-fold tuning as R2 is run for F-A, F-B and their no-temporal variants.
Writes results/round2/temporal_ablation.json. Never touches a test split.

The verdict covers the three metrics PLAN_ROUND2 names: event F1 (event-counted, the tuned objective), false alarms
per day and category accuracy per event. Segment-based F1 and row-level macro-F1 are tabulated as well.
"""
from __future__ import annotations

import json
import time

import numpy as np

from ..data.loaders import build_scenario_background
from ..data.splits import load_splits
from ..models.fusion import macro_f1
from ..simulator.scenarios import generate_scenarios
from .data import RES
from .fusion_tune import FusionADesign, FusionBDesign, fusion_mask, oof_tune
from .round2_data import any_events_from_frame, attach_evidence, featurize, load_modules

SEEDS = [7001, 7002, 7003, 7004, 7005]
T_CRIT_4DF = 2.776  # two-sided 95% for n = 5 paired seeds
VERDICT_METRICS = (("event-counted F1", "f1_event_counted", 1), ("false alarms/day", "fa_per_day", -1),
                   ("category accuracy", "category_accuracy", 1))
ALL_METRICS = ("f1_event_counted", "fa_per_day", "category_accuracy", "f1_segment_based", "macro_f1", "alert_row_fraction")


def designs() -> dict:
    return {"F-A": FusionADesign(True), "F-B": FusionBDesign(True),
            "F-A (no temporal)": FusionADesign(False), "F-B (no temporal)": FusionBDesign(False)}


def verdict(summary: dict, fam: str) -> str:
    better = [m for m, k, sign in VERDICT_METRICS
              if summary[f"{fam}/{k}"]["detectable_at_95pct"] and sign * summary[f"{fam}/{k}"]["paired_diff_mean"] > 0]
    worse = [m for m, k, sign in VERDICT_METRICS
             if summary[f"{fam}/{k}"]["detectable_at_95pct"] and sign * summary[f"{fam}/{k}"]["paired_diff_mean"] < 0]
    if better and not worse:
        return f"temporal features HELP {fam} on: {', '.join(better)}"
    if worse and not better:
        return f"temporal features HURT {fam} on: {', '.join(worse)}"
    if better and worse:
        return f"temporal features MIXED for {fam}: help on {', '.join(better)}; hurt on {', '.join(worse)}"
    return f"NO DETECTABLE DIFFERENCE for {fam} with 5 seeds (paired 95% test)"


def main():
    t0 = time.time()
    sp = load_splits(RES / "splits" / "scenarios.json")
    bg, _ = build_scenario_background()
    modules = load_modules()
    rows = []
    for seed in SEEDS:
        raw, _ = generate_scenarios(bg, sp, seed=seed, per_type=4)
        val = attach_evidence(featurize(raw), "val", modules).reset_index(drop=True)
        events = any_events_from_frame(val)
        mask, y = fusion_mask(val), val.y.to_numpy()
        for name, d in designs().items():
            r = oof_tune(d, val, events)
            o, pred = r["oof"], r["oof_pred"]
            rows.append({"seed": seed, "design": name, "f1_event_counted": o["f1_event_counted"], "f1_segment_based": o["f1"],
                         "fa_per_day": o["fa_per_day"], "category_accuracy": r["oof_category_accuracy"],
                         "macro_f1": macro_f1(y[mask], pred[mask]), "alert_row_fraction": o["alert_fraction"],
                         "final_params": [float(x) for x in r["final_params"]]})
            print(f"seed {seed} {name:20s} event-counted F1 {o['f1_event_counted']:.3f} FA {o['fa_per_day']:.2f} "
                  f"cat.acc {r['oof_category_accuracy']:.3f}", flush=True)
    summary = {}
    for fam in ("F-A", "F-B"):
        for metric in ALL_METRICS:
            w = np.array([r[metric] for r in rows if r["design"] == fam])
            n = np.array([r[metric] for r in rows if r["design"] == f"{fam} (no temporal)"])
            diff = w - n
            se = diff.std(ddof=1) / np.sqrt(len(diff))
            detectable = bool(abs(diff.mean()) > T_CRIT_4DF * se) if se > 0 else bool(diff.mean() != 0)
            summary[f"{fam}/{metric}"] = {"with_mean": float(w.mean()), "with_sd": float(w.std(ddof=1)),
                                          "without_mean": float(n.mean()), "without_sd": float(n.std(ddof=1)),
                                          "paired_diff_mean": float(diff.mean()), "paired_diff_se": float(se),
                                          "detectable_at_95pct": detectable}
    out = {"seeds": SEEDS, "rows": rows, "summary": summary,
           "verdict_metrics": [k for _, k, _ in VERDICT_METRICS],
           "verdict": {"F-A": verdict(summary, "F-A"), "F-B": verdict(summary, "F-B")},
           "caveat": "Calibrators were fitted on the Round-1 validation split; events are new, background rows are shared."}
    (RES / "round2").mkdir(parents=True, exist_ok=True)
    (RES / "round2" / "temporal_ablation.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out["verdict"], indent=2), f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
