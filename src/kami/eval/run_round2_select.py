"""R2: constrained tuning and selection on validation only -> results/round2/selection_val.json

python -m kami.eval.run_round2_select
Never touches a test split.

Scenarios (both evidence streams): all five decision rules are tuned out-of-fold on the scenario validation split and
the fusion design is SELECTED here. BattLeDIM (infrastructure stream only, its own evidence module with a different
calibration): the same rules are tuned with the same procedure and cap on the BattLeDIM validation split, because
decision thresholds do not transfer between differently calibrated evidence modules (Round 1 also fitted BattLeDIM
rules on BattLeDIM validation). No selection is made on BattLeDIM.
"""
from __future__ import annotations

import json
import time

from .access import SplitData
from .data import RES
from .fusion_tune import CAP, TIE, all_designs, oof_tune, select
from .round2_data import any_events_from_frame
from .run_evidence import events_for
from .run_fusion import build_frame, eval_category, fusion_mask


def tune_dataset(name: str) -> tuple[dict, dict, dict]:
    full = build_frame(name)
    val = SplitData(full).val().reset_index(drop=True)
    events = any_events_from_frame(val) if name == "scenarios" else events_for(name, val, "infra")
    print(f"[{name}] validation rows {len(val)}, events {len(events)}", flush=True)
    results, report = {}, {}
    for d in all_designs():
        r = oof_tune(d, val, events)
        results[d.name] = r
        cat = eval_category(val, r["oof_pred"], fusion_mask(val, name), name)
        report[d.name] = {
            "oof_event_f1": r["oof"]["f1"], "oof_event_precision": r["oof"]["precision"], "oof_event_recall": r["oof"]["recall"],
            "oof_false_alarms_per_day": r["oof"]["fa_per_day"], "feasible_at_cap": r["feasible"],
            "oof_macro_f1": cat["macro_f1"], "oof_category_accuracy_event": cat["event_category_accuracy"],
            "oof_point_accuracy": cat["accuracy"],
            "fold_params": [[float(x) for x in p] for p in r["fold_params"]],
            "final_params": [float(x) for x in r["final_params"]],
            "in_sample_event_f1": r["in_sample"]["f1"], "in_sample_fa_per_day": r["in_sample"]["fa_per_day"],
        }
        print(f"[{name}] {d.name:32s} OOF event F1 {r['oof']['f1']:.3f} FA/day {r['oof']['fa_per_day']:.2f} "
              f"macroF1 {cat['macro_f1']:.3f} params {report[d.name]['final_params']}", flush=True)
    return results, report, {"validation_rows": len(val), "validation_events": len(events)}


def main():
    t0 = time.time()
    results, report, info = tune_dataset("scenarios")
    selected, reason = select(results)
    _, bd_report, bd_info = tune_dataset("battledim")
    out = {"cap_false_alarms_per_day": CAP, "tie": TIE, "selected": selected, "selection_reason": reason,
           "designs": report, **info,
           "battledim": {"note": "same procedure and cap on the BattLeDIM validation split (infrastructure stream only; "
                                 "8 validation events, so these out-of-fold numbers are very noisy); no selection here",
                         "designs": bd_report, **bd_info}}
    (RES / "round2").mkdir(parents=True, exist_ok=True)
    (RES / "round2" / "selection_val.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"selected {selected} ({reason}); done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
