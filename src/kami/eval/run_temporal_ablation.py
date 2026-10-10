"""R3: with/without temporal features across 5 scenario-generation seeds, VALIDATION period only.

For each seed a new labelled scenario set is generated (same rules, same backgrounds, seeds different from the training
seed 42 and the test_v2 seed). Evidence probabilities come from the Round-1 modules (trained on the train period); their
calibrators were fitted on the Round-1 validation split, so the background rows are not fresh but the events are.
For each seed the same constrained out-of-fold tuning as R2 is run for F-A, F-B and their no-temporal variants.
Writes results/round2/temporal_ablation.json. Never touches a test split.
"""
from __future__ import annotations

import json
import time

import numpy as np

from ..data.loaders import build_scenario_background
from ..data.splits import load_splits
from ..simulator.scenarios import generate_scenarios
from .data import RES
from .fusion_tune import FusionADesign, FusionBDesign, fusion_mask, oof_tune
from .round2_data import any_events_from_frame, attach_evidence, featurize, load_modules
from .run_fusion import eval_category

SEEDS = [7001, 7002, 7003, 7004, 7005]
T_CRIT_4DF = 2.776  # two-sided 95% for n = 5 paired seeds


def main():
    t0 = time.time()
    sp = load_splits(RES / "splits" / "scenarios.json")
    bg, _ = build_scenario_background()
    modules = load_modules()
    designs = lambda: {"F-A": FusionADesign(True), "F-B": FusionBDesign(True),  # noqa: E731
                       "F-A (no temporal)": FusionADesign(False), "F-B (no temporal)": FusionBDesign(False)}
    rows = []
    for seed in SEEDS:
        raw, _ = generate_scenarios(bg, sp, seed=seed, per_type=4)
        full = featurize(raw)
        val = attach_evidence(full, "val", modules).reset_index(drop=True)
        events = any_events_from_frame(val)
        for name, d in designs().items():
            r = oof_tune(d, val, events)
            cat = eval_category(val, r["oof_pred"], fusion_mask(val), "scenarios")
            rows.append({"seed": seed, "design": name, "event_f1": r["oof"]["f1"], "fa_per_day": r["oof"]["fa_per_day"],
                         "category_accuracy": cat["event_category_accuracy"], "macro_f1": cat["macro_f1"],
                         "final_params": [float(x) for x in r["final_params"]]})
            print(f"seed {seed} {name:20s} F1 {r['oof']['f1']:.3f} FA {r['oof']['fa_per_day']:.2f} catacc {cat['event_category_accuracy']:.3f}",
                  flush=True)
    summary = {}
    for fam in ("F-A", "F-B"):
        for metric in ("event_f1", "fa_per_day", "category_accuracy", "macro_f1"):
            w = np.array([r[metric] for r in rows if r["design"] == fam])
            n = np.array([r[metric] for r in rows if r["design"] == f"{fam} (no temporal)"])
            diff = w - n
            se = diff.std(ddof=1) / np.sqrt(len(diff))
            detectable = bool(abs(diff.mean()) > T_CRIT_4DF * se) if se > 0 else bool(diff.mean() != 0)
            summary[f"{fam}/{metric}"] = {"with_mean": float(w.mean()), "with_sd": float(w.std(ddof=1)),
                                          "without_mean": float(n.mean()), "without_sd": float(n.std(ddof=1)),
                                          "paired_diff_mean": float(diff.mean()), "paired_diff_se": float(se),
                                          "detectable_at_95pct": detectable}
    def verdict(fam):
        f1 = summary[f"{fam}/event_f1"]
        fa = summary[f"{fam}/fa_per_day"]
        ca = summary[f"{fam}/category_accuracy"]
        better = [m for m, s, sign in (("event F1", f1, 1), ("false alarms/day", fa, -1), ("category accuracy", ca, 1))
                  if s["detectable_at_95pct"] and sign * s["paired_diff_mean"] > 0]
        worse = [m for m, s, sign in (("event F1", f1, 1), ("false alarms/day", fa, -1), ("category accuracy", ca, 1))
                 if s["detectable_at_95pct"] and sign * s["paired_diff_mean"] < 0]
        if better and not worse:
            return f"temporal features HELP {fam} on: {', '.join(better)}"
        if worse and not better:
            return f"temporal features HURT {fam} on: {', '.join(worse)}"
        if better and worse:
            return f"temporal features MIXED for {fam}: help on {', '.join(better)}; hurt on {', '.join(worse)}"
        return f"NO DETECTABLE DIFFERENCE for {fam} with 5 seeds (paired 95% test)"
    out = {"seeds": SEEDS, "rows": rows, "summary": summary,
           "verdict": {"F-A": verdict("F-A"), "F-B": verdict("F-B")},
           "caveat": "Calibrators were fitted on the Round-1 validation split; events are new, background rows are shared."}
    (RES / "round2").mkdir(parents=True, exist_ok=True)
    (RES / "round2" / "temporal_ablation.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out["verdict"], indent=2), f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
