"""R2: constrained tuning and selection on validation only -> results/round2/selection_val.json

python -m kami.eval.run_round2_select
Never touches the test split.
"""
from __future__ import annotations

import json
import time

import numpy as np

from .data import RES
from .fusion_tune import CAP, TIE, all_designs, oof_tune, select
from .round2_data import any_events_from_frame
from .run_fusion import build_frame, eval_category, fusion_mask
from .access import SplitData


def main():
    t0 = time.time()
    full = build_frame("scenarios")
    val = SplitData(full).val().reset_index(drop=True)
    events = any_events_from_frame(val)
    print(f"validation rows {len(val)}, events {len(events)}")
    results, report = {}, {}
    for d in all_designs():
        r = oof_tune(d, val, events)
        results[d.name] = r
        mask = fusion_mask(val, "scenarios")
        cat = eval_category(val, r["oof_pred"], mask, "scenarios")
        report[d.name] = {
            "oof_event_f1": r["oof"]["f1"], "oof_event_precision": r["oof"]["precision"], "oof_event_recall": r["oof"]["recall"],
            "oof_false_alarms_per_day": r["oof"]["fa_per_day"], "feasible_at_cap": r["feasible"],
            "oof_macro_f1": cat["macro_f1"], "oof_category_accuracy_event": cat["event_category_accuracy"],
            "oof_point_accuracy": cat["accuracy"],
            "fold_params": [list(p) for p in r["fold_params"]], "final_params": list(r["final_params"]),
            "in_sample_event_f1": r["in_sample"]["f1"], "in_sample_fa_per_day": r["in_sample"]["fa_per_day"],
        }
        print(f"{d.name:32s} OOF event F1 {r['oof']['f1']:.3f} FA/day {r['oof']['fa_per_day']:.2f} "
              f"macroF1 {cat['macro_f1']:.3f} params {r['final_params']}", flush=True)
    selected, reason = select(results)
    out = {"cap_false_alarms_per_day": CAP, "tie": TIE, "selected": selected, "selection_reason": reason,
           "designs": report, "validation_rows": len(val), "validation_events": len(events)}
    (RES / "round2").mkdir(parents=True, exist_ok=True)
    (RES / "round2" / "selection_val.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"selected {selected} ({reason}); done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
