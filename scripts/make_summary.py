"""Builds results/SUMMARY.md from the generated result files (no hand-typed numbers). Round 2 version."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"
VOTE = "threshold voting (no fusion)"
JOINT = "single joint model (no separated evidence)"


def jload(p):
    return json.loads((R / p).read_text(encoding="utf-8"))


def body(p):
    return (R / p).read_text(encoding="utf-8").split("\n", 1)[1].strip()


def f3(x):
    return "n/a" if x is None else f"{x:.3f}"


def ci(v, ci_):
    return f"{f3(v)} [{ci_[0]:.3f}, {ci_[1]:.3f}]"


def ci2(v, ci_):
    return f"{v:.2f} [{ci_[0]:.2f}, {ci_[1]:.2f}]"


def order(names, selected):
    pref = ["F-B", "F-A", "F-B (no temporal)", "F-A (no temporal)", VOTE, JOINT]
    rest = sorted(n for n in names if n not in pref)
    return [n for n in pref if n in names] + rest


def headline(fin):
    sel = fin["selected_design"]
    cap = fin["false_alarm_cap_per_day"]
    res = fin["results"]["test_v2"]
    s, v = res[sel], res[VOTE]
    lo_s, hi_s = s["ci95"]["f1"]
    lo_v, hi_v = v["ci95"]["f1"]
    higher = s["event"]["f1"] > v["event"]["f1"]
    overlap = not (lo_s > hi_v or lo_v > hi_s)
    within = s["event"]["fa_per_day"] <= cap
    if higher and not overlap:
        verdict = "beats threshold voting"
    elif (not higher) and not overlap:
        verdict = "does NOT beat threshold voting (it is worse, intervals do not overlap)"
    else:
        verdict = "does NOT beat threshold voting by a detectable margin (95% intervals overlap)"
    lines = [
        f"**Outcome on the fresh test set (test_v2, frozen method, evaluated once).** At the cap of {cap} false alarms per day, "
        f"the selected fusion design ({sel}) {verdict} on event F1: {ci(s['event']['f1'], s['ci95']['f1'])} versus "
        f"{ci(v['event']['f1'], v['ci95']['f1'])} for simple threshold voting on the same evidence. False alarms per day: "
        f"{ci2(s['event']['fa_per_day'], s['ci95']['fa_per_day'])} ({'within' if within else 'ABOVE'} the cap) versus "
        f"{ci2(v['event']['fa_per_day'], v['ci95']['fa_per_day'])}.",
        "",
        f"Category accuracy per event (is the alert category Infrastructure, Quality or Combined the right one?): "
        f"{sel} {ci(s['category_accuracy_event'], s['ci95']['category_accuracy'])}, threshold voting "
        f"{ci(v['category_accuracy_event'], v['ci95']['category_accuracy'])}. See section 3.",
    ]
    return "\n".join(lines)


def final_table(res, models):
    out = ["| Model | Event F1 [95% CI] | Event precision [95% CI] | Event recall [95% CI] | False alarms/day [95% CI] | Latency median (h) |",
           "|---|---|---|---|---|---|"]
    for m in models:
        r = res[m]
        e, c = r["event"], r["ci95"]
        out.append(f"| {m} | {ci(e['f1'], c['f1'])} | {ci(e['precision'], c['precision'])} | {ci(e['recall'], c['recall'])} | "
                   f"{ci2(e['fa_per_day'], c['fa_per_day'])} | {f3(e['latency_median_h'])} |")
    return "\n".join(out)


def category_table(res, models, has_q=True):
    types = sorted({t for m in models for t in res[m]["per_type"]})
    head = ("| Model | Category accuracy per event [95% CI] | Macro-F1 (point) | Recall Infrastructure | Recall Quality | Recall Combined | "
            + " | ".join(f"{t} correct" for t in types) + " |")
    out = [head, "|---|---|---|---|---|---|" + "---|" * len(types)]
    for m in models:
        r = res[m]
        pc = r["per_category_point_recall"]
        out.append(f"| {m} | {ci(r['category_accuracy_event'], r['ci95']['category_accuracy'])} | {f3(r['macro_f1'])} | "
                   f"{f3(pc['Infrastructure'])} | {f3(pc['Quality'])} | {f3(pc['Combined'])} | "
                   + " | ".join(f"{r['per_type'][t]['category_correct']:.2f} (n={r['per_type'][t]['events']})" if t in r["per_type"] else "-" for t in types)
                   + " |")
    return "\n".join(out)


def validation_table(sel):
    out = ["| Design | OOF event F1 | OOF false alarms/day | Feasible at cap | OOF macro-F1 | OOF category acc. | Frozen parameters |",
           "|---|---|---|---|---|---|---|"]
    for k, v in sel["designs"].items():
        out.append(f"| {k} | {v['oof_event_f1']:.3f} | {v['oof_false_alarms_per_day']:.2f} | {'yes' if v['feasible_at_cap'] else 'NO'} | "
                   f"{v['oof_macro_f1']:.3f} | {v['oof_category_accuracy_event']:.3f} | {v['final_params']} |")
    return "\n".join(out)


def temporal_table(t):
    out = ["| Design family | Metric | With temporal (mean ± sd) | Without (mean ± sd) | Paired difference ± SE | Detectable (95%) |",
           "|---|---|---|---|---|---|"]
    for k, v in t["summary"].items():
        fam, metric = k.split("/")
        out.append(f"| {fam} | {metric} | {v['with_mean']:.3f} ± {v['with_sd']:.3f} | {v['without_mean']:.3f} ± {v['without_sd']:.3f} | "
                   f"{v['paired_diff_mean']:+.3f} ± {v['paired_diff_se']:.3f} | {'yes' if v['detectable_at_95pct'] else 'no'} |")
    return "\n".join(out)


def evidence_table():
    lines = ["| Dataset | Domain | Model | Val event F1 | Best baseline (val) | Val Brier | Test event F1 (exposed split) | Test Brier |",
             "|---|---|---|---|---|---|---|---|"]
    for f in sorted((R / "evidence").glob("*__*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        b = d["best_baseline_val"]
        lines.append(f"| {d['dataset']} | {d['domain']} | {d['model_selected']} | {d['val']['event']['f1']:.3f} | "
                     f"{b['model']} {b['val_event_f1']:.3f} | {d['val']['brier']:.3f} | {d['test']['event']['f1']:.3f} | "
                     f"{d['test']['brier']:.3f} |")
    return "\n".join(lines)


LIMITS = """- **No real field data with labels.** The infrastructure data (BattLeDIM) are simulated hydraulics with exact leak labels; quality data (USGS river stations) are real but unlabelled, so all quality events are injected.
- **Fusion is tested on semi-synthetic scenarios** (events injected into real/simulated backgrounds). Event shapes and sizes are assumptions (docs/scenarios.md); good scores show the method recovers those assumptions, not that it works on real incidents.
- **Test-set history.** test_v1 and the BattLeDIM test split were seen while F-B's decision rule was being changed (Round 1) and are reported only as "exposed". test_v2 was generated after the method was frozen on validation and evaluated once per model. The BattLeDIM split cannot be refreshed.
- **Tuning grid edges.** Several tuned thresholds sit at the strict end of their grid (0.95 to 0.98); the validation optimum may lie beyond it.
- **Same backgrounds in all scenario sets.** test_v2 has new events but shares the background series (and their drift from unlabelled BattLeDIM leaks) with test_v1 and validation; it refreshes the events, not the background.
- **Mixed-origin nodes.** Scenario nodes pair BattLeDIM infrastructure series with Virginia river quality series; the 8 demo nodes are a fictional layout near Vellore.
- **Low-cost sensor caveats** (drift, fouling, noise, calibration) are not modelled beyond what the public series contain. TDS is a conductance proxy (0.64 x conductance).
- **Rule-based priority.** The escalation rule is a documented heuristic, not validated against operator judgement.
- **Small test sets.** 60 scenario events per test set and 8 BattLeDIM test events; the bootstrap intervals show how wide the uncertainty is (events, alert segments and days are resampled; temporal dependence between neighbouring days is ignored).
- **Evidence modules are supervised** while the baselines are unsupervised; the comparison shows the value of labelled training, not a like-for-like detector contest.
- **Temporal-ablation caveat.** The five validation seeds share the background rows used to fit the calibrators.
- **LeakDB not used** (30-minute sampling vs the 5-minute design; 13.9 GB archive).
- **No Docker run.** The MQTT/TimescaleDB path is implemented but was not exercised in this environment (fallback SQLite plus in-process bus was used)."""


def main():
    fin = jload("round2/final_results.json")
    sel = jload("round2/selection_val.json")
    tmp = jload("round2/temporal_ablation.json")
    res2 = fin["results"]["test_v2"]
    models = order(list(res2), fin["selected_design"])
    parts = ["# KAMI results summary (Round 2)", "",
             headline(fin), "",
             "Generated by `python scripts/make_summary.py` from files in `results/`. Round 1 numbers are kept in "
             "`results_round1/`. Simulated-hydraulics BattLeDIM results and semi-synthetic scenario results are reported separately. "
             "Everything below uses the configuration frozen on validation (`results/fusion/frozen_config.json`).", "",
             "## 1. Validation: constrained tuning and selection",
             "", f"Objective: maximise event F1 subject to at most {sel['cap_false_alarms_per_day']} false alarms per day, "
             f"out-of-fold over four validation time blocks. Selected: **{sel['selected']}** ({sel['selection_reason']}). "
             f"Frozen at commit `{fin['frozen_commit'][:10]}` before any test_v2 access.", "",
             validation_table(sel), "",
             "## 2. Final evaluation on test_v2 (fresh events, evaluated once per model)", "",
             final_table(res2, models), "",
             "## 3. Category separation (Infrastructure vs Quality vs Combined), test_v2", "",
             category_table(res2, models), "",
             "## 4. Temporal features: with vs without (validation, five seeds)", "",
             f"- {tmp['verdict']['F-A']}", f"- {tmp['verdict']['F-B']}", "", temporal_table(tmp), "",
             f"Caveat: {tmp['caveat']}", "",
             "## 5. BattLeDIM test (real labels on simulated data; previously exposed for F-B, 8 events)", "",
             final_table(fin["results"]["battledim_test_previously_exposed"], order(list(fin["results"]["battledim_test_previously_exposed"]), "")), "",
             "## 6. test_v1 (exposed, for reference only)", "",
             final_table(fin["results"]["test_v1_exposed"], models), "",
             "## 7. Baselines (validation-tuned under the same cap, including One-Class SVM; evaluated on exposed test_v1 / BattLeDIM)", "",
             body("tables/baselines.md"), "",
             "## 8. Evidence modules (calibrated, Round 1; test numbers are on exposed splits)", "", evidence_table(), "",
             "Reliability curves: `results/figures/reliability_*.png`.", "",
             "## 9. Limitations", "", LIMITS, ""]
    (R / "SUMMARY.md").write_text("\n".join(parts), encoding="utf-8")
    print("wrote results/SUMMARY.md")


if __name__ == "__main__":
    main()
