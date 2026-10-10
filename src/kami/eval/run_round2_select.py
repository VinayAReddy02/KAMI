"""R2: constrained tuning and selection on validation only -> results/round2/selection_val.json

python -m kami.eval.run_round2_select
Never touches a test split.

Scenarios (both evidence streams): all five decision rules are tuned out-of-fold on the scenario validation split and
the fusion design is SELECTED here. BattLeDIM (infrastructure stream only, its own evidence module with a different
calibration): the same rules are tuned with the same procedure and cap on the BattLeDIM validation split, because
decision thresholds do not transfer between differently calibrated evidence modules (Round 1 also fitted BattLeDIM
rules on BattLeDIM validation). No selection is made on BattLeDIM.

The output records the sha256 of every input (code and data) so the freeze can refuse parameters that were tuned
with different code or evidence than the ones being frozen.
"""
from __future__ import annotations

import json
import time

from ..models.fusion import macro_f1
from .access import SplitData
from .data import RES
from .freeze import tuning_inputs
from .fusion_tune import CAP, TIE, all_designs, fusion_mask, oof_tune, select
from .round2_data import any_events_from_frame, battledim_frame
from .run_evidence import events_for
from .run_fusion import build_frame


def validation_frame(name: str):
    """Validation rows only. Scenarios: Round-1 evidence table (cross-fitted calibration). BattLeDIM: label-free
    temporal features (round2_data.battledim_frame)."""
    full = build_frame("scenarios") if name == "scenarios" else battledim_frame()
    return SplitData(full, name).val().reset_index(drop=True)


def tune_dataset(name: str) -> tuple[dict, dict, dict]:
    val = validation_frame(name)
    events = any_events_from_frame(val) if name == "scenarios" else events_for(name, val, "infra")
    mask = fusion_mask(val)
    y = val.y.to_numpy()
    print(f"[{name}] validation rows {len(val)} (scored {int(mask.sum())}), events {len(events)}", flush=True)
    results, report = {}, {}
    for d in all_designs():
        r = oof_tune(d, val, events)
        results[d.name] = r
        o, pred = r["oof"], r["oof_pred"]
        report[d.name] = {
            "oof_event_f1": o["f1"], "oof_event_precision": o["precision"], "oof_event_recall": o["recall"],
            "oof_false_alarms_per_day": o["fa_per_day"], "feasible_at_cap": r["feasible"],
            "oof_f1_event_counted": o["f1_event_counted"], "oof_precision_event_counted": o["precision_event_counted"],
            "oof_true_segments": o["true_segments"], "oof_false_segments": o["false_segments"],
            "oof_detected_events": o["detected"], "oof_events": o["events"],
            "oof_alert_row_fraction": o["alert_fraction"], "oof_normal_rows_in_alert_fraction": o["normal_alert_fraction"],
            "oof_macro_f1": macro_f1(y[mask], pred[mask]), "oof_point_accuracy": float((y[mask] == pred[mask]).mean()),
            "oof_category_accuracy_event": r["oof_category_accuracy"],
            "fold_params": [[float(x) for x in p] for p in r["fold_params"]],
            "final_params": [float(x) for x in r["final_params"]],
            "in_sample_event_f1": r["in_sample"]["f1"], "in_sample_fa_per_day": r["in_sample"]["fa_per_day"],
            "in_sample_alert_row_fraction": r["in_sample"]["alert_fraction"],
        }
        print(f"[{name}] {d.name:30s} OOF F1 {o['f1']:.3f} (event-counted {o['f1_event_counted']:.3f}) FA/day {o['fa_per_day']:.2f} "
              f"rows in alert {100 * o['alert_fraction']:.1f}% cat.acc {r['oof_category_accuracy']:.3f} "
              f"params {report[d.name]['final_params']}", flush=True)
    return results, report, {"validation_rows": len(val), "validation_scored_rows": int(mask.sum()), "validation_events": len(events)}


def main():
    t0 = time.time()
    results, report, info = tune_dataset("scenarios")
    selected, reason = select(results)
    _, bd_report, bd_info = tune_dataset("battledim")
    out = {"cap_false_alarms_per_day": CAP, "tie": TIE, "selected": selected, "selection_reason": reason,
           "objective": "maximise out-of-fold event-counted F1 (each detected event counted once) subject to false "
                        "alarms/day <= cap; if infeasible the fewest false alarms; exact ties go to the setting with fewer "
                        "rows in alert",
           "designs": report, **info,
           "battledim": {"note": "same procedure and cap on the BattLeDIM validation split (infrastructure stream only; "
                                 "8 validation events, so these out-of-fold numbers are very noisy); no selection here",
                         "designs": bd_report, **bd_info},
           "tuning_inputs_sha256": tuning_inputs()}
    (RES / "round2").mkdir(parents=True, exist_ok=True)
    (RES / "round2" / "selection_val.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"selected {selected} ({reason}); done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
