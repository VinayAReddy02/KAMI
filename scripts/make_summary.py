"""Builds results/SUMMARY.md from the generated result files (no hand-typed numbers). Round 2 version.

Every number comes from: results/round2/final_results.json (metrics, intervals and the frozen verdict), selection_val.json,
temporal_ablation.json, incident_test_v2/incident.json, results/baselines/*.json and results/evidence/*.json.

    python scripts/make_summary.py
    python scripts/make_summary.py --final <dry-run final_results.json> --out <file>    # smoke test of the report only
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"
VOTE = "threshold voting (no fusion)"
JOINT = "single joint model (no separated evidence)"
BD = "battledim_test_previously_exposed"


def jload(p):
    return json.loads((R / p).read_text(encoding="utf-8"))


def f3(x):
    return "n/a" if x is None else f"{x:.3f}"


def f2(x):
    return "n/a" if x is None else f"{x:.2f}"


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def ci(v, c):
    return f"{f3(v)} [{c[0]:.3f}, {c[1]:.3f}]"


def ci2(v, c):
    return f"{v:.2f} [{c[0]:.2f}, {c[1]:.2f}]"


def order(names):
    pref = ["F-B", "F-A", "F-B (no temporal)", "F-A (no temporal)", VOTE, JOINT]
    return [n for n in pref if n in names] + sorted(n for n in names if n not in pref)


def ok(r):
    return r.get("status") == "ok"


# ---------------------------------------------------------------------------------------------- verdict sentences
def verdict_phrase(v):
    """Words for the frozen verdict (final_results.json 'verdicts'); the rule itself is in freeze.VERDICT_RULE."""
    d = v["difference_selected_minus_voting"]["f1_event_counted"]
    lo, hi = v["paired_ci95"]["f1_event_counted"]["ci95"]
    diff = f"paired difference {d:+.3f}, 95% interval [{lo:+.3f}, {hi:+.3f}]"
    o = v["outcome"]
    if o == "beats":
        return f"beats threshold voting ({diff}, and it is within the false-alarm cap)"
    if o == "higher_f1_but_above_cap":
        return f"does NOT beat threshold voting: its event F1 is detectably higher ({diff}) but its false alarms exceed the cap on this set"
    if o == "worse":
        return f"does NOT beat threshold voting: it is detectably worse ({diff})"
    where = "higher" if d > 0 else "lower" if d < 0 else "the same"
    return f"does NOT beat threshold voting: no detectable difference (its point estimate is {where}; {diff})"


def cap_word(within):
    return "within the cap" if within else "ABOVE the cap"


def headline(fin):
    sel, cap = fin["selected_design"], fin["false_alarm_cap_per_day"]
    out = []
    v = fin["verdicts"].get("test_v3")
    r3 = fin["results"]["test_v3"]
    if v is None or not (ok(r3.get(sel, {})) and ok(r3.get(VOTE, {}))):
        return ("**Outcome on the headline test set (test_v3): NOT AVAILABLE.** The selected fusion design or threshold voting has "
                "no completed evaluation on test_v3 (see section 2), so no statement can be made on whether fusion beats threshold voting.")
    s, t = r3[sel], r3[VOTE]
    out.append(
        f"**Outcome on the headline test set (test_v3: fresh events, method frozen first, each model evaluated once).** "
        f"Tuned on validation for at most {cap} false alarms per day, the selected fusion design ({sel}) {verdict_phrase(v)}. "
        f"Event F1, each detected event counted once: {sel} {ci(s['event']['f1_event_counted'], s['ci95']['f1_event_counted'])}, "
        f"threshold voting on the same evidence {ci(t['event']['f1_event_counted'], t['ci95']['f1_event_counted'])}. "
        f"False alarms per day: {sel} {ci2(s['event']['fa_per_day'], s['ci95']['fa_per_day'])} ({cap_word(v['selected_within_cap'])}), "
        f"threshold voting {ci2(t['event']['fa_per_day'], t['ci95']['fa_per_day'])} ({cap_word(v['voting_within_cap'])}).")
    c = v["paired_ci95"]["category_accuracy"]["ci95"]
    out.append(
        f"Category accuracy per event (does the alert name the right streams: Infrastructure, Quality or both?): {sel} "
        f"{ci(s['category_accuracy_event'], s['ci95']['category_accuracy'])}, threshold voting "
        f"{ci(t['category_accuracy_event'], t['ci95']['category_accuracy'])}; paired difference "
        f"{v['difference_selected_minus_voting']['category_accuracy']:+.3f} [{c[0]:+.3f}, {c[1]:+.3f}]. "
        f"With the Round-1 segment-based F1 (every alert fragment counted) the two score "
        f"{f3(s['event']['f1'])} and {f3(t['event']['f1'])}.")
    extra = []
    for key, label in (("test_v2", "Secondary set test_v2"), (BD, "BattLeDIM test (exposed, 8 events)")):
        vv = fin["verdicts"].get(key)
        if vv:
            extra.append(f"{label}: {sel} {verdict_phrase(vv)}.")
    if extra:
        out.append(" ".join(extra))
    return "\n\n".join(out)


# ---------------------------------------------------------------------------------------------- tables
READING = ("How to read the tables. An alert segment is a run of alerting rows (gaps up to 1 h merged). **Event recall** = events "
           "with any alert inside them. **Event precision** = detected events / (detected events + false alarms), where a false "
           "alarm is a segment that overlaps no event; each detected event counts once. **Event F1** combines the two and is the "
           "objective that was tuned. **False alarms/day** = false segments per day of normal data. The Round-1 *segment-based* "
           "precision (true segments / all segments) is shown in the second table: it counts every fragment of a broken-up alert "
           "as a separate hit and is therefore higher. Neither version penalises how long an alert lasts, so the last two columns "
           "show the share of scored rows in alert and the share of normal rows in alert. Intervals are bootstrap 95%: events are "
           "resampled for recall, precision, F1 and category accuracy, whole days for false alarms. An interval of zero width "
           "means every resampled unit agreed, not that the value is certain.")


def final_table(res, models, flag=None):
    out = ["| Model | Event F1 [95% CI] | Event precision [95% CI] | Event recall [95% CI] | False alarms/day [95% CI] | "
           "Latency median / p90 (h) | Rows in alert | Normal rows in alert |", "|---|---|---|---|---|---|---|---|"]
    for m in models:
        r = res[m]
        name = m + (" †" if flag and flag(m) else "")
        if not ok(r):
            out.append(f"| {name} | not evaluated: {r.get('status')} | | | | | | |")
            continue
        e, c = r["event"], r["ci95"]
        out.append(f"| {name} | {ci(e['f1_event_counted'], c['f1_event_counted'])} | "
                   f"{ci(e['precision_event_counted'], c['precision_event_counted'])} | {ci(e['recall'], c['recall'])} | "
                   f"{ci2(e['fa_per_day'], c['fa_per_day'])} | {f2(e['latency_median_h'])} / {f2(e['latency_p90_h'])} | "
                   f"{pct(r['alert_row_fraction'])} | {pct(r['normal_rows_in_alert_fraction'])} |")
    return "\n".join(out)


def observations(res, sel):
    """Plain sentences computed from one result set: how slow and how partial detection is, how close the best baseline
    comes, and which model names the category best."""
    good = {m: r for m, r in res.items() if ok(r)}
    if sel not in good or VOTE not in good:
        return ""
    s, t = good[sel], good[VOTE]
    out = [f"Detection is slow and partial at these strict thresholds: {sel} first alerts a median of "
           f"{f2(s['event']['latency_median_h'])} h after an event starts (90th percentile {f2(s['event']['latency_p90_h'])} h) and "
           f"alerts on {pct(s['point_any_alert']['recall'])} of the rows inside events; threshold voting: "
           f"{f2(t['event']['latency_median_h'])} h, {f2(t['event']['latency_p90_h'])} h and {pct(t['point_any_alert']['recall'])}."]
    base = {m: r for m, r in good.items() if m.startswith("baseline")}
    if base:
        b = max(base, key=lambda m: base[m]["event"]["f1_event_counted"])
        rb = base[b]
        out.append(f"The best baseline on event F1 is {b.replace('baseline: ', '')} at "
                   f"{ci(rb['event']['f1_event_counted'], rb['ci95']['f1_event_counted'])} with {f2(rb['event']['fa_per_day'])} false "
                   f"alarms/day and category accuracy {f3(rb['category_accuracy_event'])}; threshold voting is at "
                   f"{ci(t['event']['f1_event_counted'], t['ci95']['f1_event_counted'])}.")
    c = max(good, key=lambda m: good[m]["category_accuracy_event"])
    out.append(f"The highest category accuracy per event belongs to {c} "
               f"({ci(good[c]['category_accuracy_event'], good[c]['ci95']['category_accuracy'])}; event F1 "
               f"{f3(good[c]['event']['f1_event_counted'])}, {f2(good[c]['event']['fa_per_day'])} false alarms/day)"
               + ("." if c == sel else f", which is not the selected design ({sel} was selected on validation event F1)."))
    return " ".join(out)


def detail_table(res, models, flag=None):
    out = ["| Model | Segment-based F1 [95% CI] | Segment-based precision [95% CI] | Detected / events | True / false segments | "
           "Row-level alert P / R / F1 | Infrastructure-stream event F1 | Quality-stream event F1 |", "|---|---|---|---|---|---|---|---|"]
    for m in models:
        r = res[m]
        if not ok(r):
            continue
        e, c, p = r["event"], r["ci95"], r["point_any_alert"]
        name = m + (" †" if flag and flag(m) else "")
        out.append(f"| {name} | {ci(e['f1'], c['f1'])} | {ci(e['precision'], c['precision'])} | {e['detected_events']} / {e['events']} | "
                   f"{e['true_segments']} / {e['false_segments']} | {f3(p['precision'])} / {f3(p['recall'])} / {f3(p['f1'])} | "
                   f"{f3(r['infra_domain_event_f1'])} | {f3(r.get('quality_domain_event_f1'))} |")
    return "\n".join(out)


def category_table(res, models, flag=None):
    models = [m for m in models if ok(res[m])]
    types = sorted({t for m in models for t in res[m]["per_type"]})
    out = ["| Model | Category accuracy per event [95% CI] | Macro-F1 (rows) | Row recall Infrastructure | Row recall Quality | "
           "Row recall Combined | " + " | ".join(f"{t}: category correct" for t in types) + " |",
           "|---|---|---|---|---|---|" + "---|" * len(types)]
    for m in models:
        r = res[m]
        pc = r["per_category_point_recall"]
        name = m + (" †" if flag and flag(m) else "")
        cells = [f"{r['per_type'][t]['category_correct']:.2f} (n={r['per_type'][t]['events']})" if t in r["per_type"] else "-" for t in types]
        out.append(f"| {name} | {ci(r['category_accuracy_event'], r['ci95']['category_accuracy'])} | {f3(r['macro_f1'])} | "
                   f"{f3(pc['Infrastructure'])} | {f3(pc['Quality'])} | {f3(pc['Combined'])} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def type_recall_table(res, models, flag=None):
    models = [m for m in models if ok(res[m])]
    types = sorted({t for m in models for t in res[m]["per_type"]})
    out = ["| Model | " + " | ".join(f"{t}: detected" for t in types) + " |", "|---|" + "---|" * len(types)]
    for m in models:
        r = res[m]
        name = m + (" †" if flag and flag(m) else "")
        out.append(f"| {name} | " + " | ".join(
            f"{r['per_type'][t]['detected_recall']:.2f} (n={r['per_type'][t]['events']})" if t in r["per_type"] else "-" for t in types) + " |")
    return "\n".join(out)


def validation_table(designs):
    out = ["| Design | OOF event F1 | OOF false alarms/day | Feasible at cap | OOF segment-based F1 | Detected / events | "
           "True / false segments | Rows in alert | Normal rows in alert | OOF category acc. | Frozen parameters |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in designs.items():
        out.append(f"| {k} | {v['oof_f1_event_counted']:.3f} | {v['oof_false_alarms_per_day']:.2f} | {'yes' if v['feasible_at_cap'] else 'NO'} | "
                   f"{v['oof_event_f1']:.3f} | {v['oof_detected_events']} / {v['oof_events']} | {v['oof_true_segments']} / {v['oof_false_segments']} | "
                   f"{pct(v['oof_alert_row_fraction'])} | {pct(v['oof_normal_rows_in_alert_fraction'])} | "
                   f"{v['oof_category_accuracy_event']:.3f} | {v['final_params']} |")
    return "\n".join(out)


def same_rule_note(designs):
    """F-B without temporal features has reliability 1, i.e. the rule p >= threshold: the voting rule."""
    nt, vote = [float(x) for x in designs["F-B (no temporal)"]["final_params"][3:]], [float(x) for x in designs[VOTE]["final_params"]]
    base = ("F-B without temporal features has reliability fixed at 1, so its rule is `p >= threshold` per stream, which is the "
            "threshold-voting rule; the two differ only in the threshold grid searched. ")
    if nt == vote:
        return base + f"Here both froze to the same thresholds {vote}, so their rows are identical by construction."
    return base + f"Here they froze to different thresholds ({nt} vs {vote}), so their rows can differ."


def baseline_table(cap):
    out = ["| Dataset | Stream | Baseline | Val event F1 | Val false alarms/day | Met the cap on validation | Tuned parameters |",
           "|---|---|---|---|---|---|---|"]
    infeasible = []
    for f in sorted((R / "baselines").glob("*__*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        v = d["val"]
        feas = v["false_alarms_per_day"] <= cap
        if not feas:
            infeasible.append(f"{d['dataset']} {d['domain']} {d['model']} ({v['false_alarms_per_day']:.2f}/day)")
        out.append(f"| {d['dataset']} | {d['domain']} | {d['model']} | {v['event']['f1_event_counted']:.3f} | {v['false_alarms_per_day']:.2f} | "
                   f"{'yes' if feas else 'NO'} | {d['params']} |")
    note = ("Every baseline met the cap on validation." if not infeasible else
            "These baselines could not meet the cap at any setting on validation, so the setting with the fewest false alarms was "
            "taken: " + "; ".join(infeasible) + ". Their false alarms on test are therefore expected to exceed the cap.")
    return "\n".join(out), note


def temporal_table(t):
    out = ["| Design family | Metric | With temporal (mean ± sd) | Without (mean ± sd) | Paired difference ± SE | Detectable (95%) |",
           "|---|---|---|---|---|---|"]
    for k, v in t["summary"].items():
        fam, metric = k.split("/")
        out.append(f"| {fam} | {metric} | {v['with_mean']:.3f} ± {v['with_sd']:.3f} | {v['without_mean']:.3f} ± {v['without_sd']:.3f} | "
                   f"{v['paired_diff_mean']:+.3f} ± {v['paired_diff_se']:.3f} | {'yes' if v['detectable_at_95pct'] else 'no'} |")
    return "\n".join(out)


def temporal_extra(t):
    """The verdict covers the three metrics PLAN_ROUND2 names. Say plainly if another tabulated metric differs detectably."""
    named = set(t["verdict_metrics"])
    other = [f"{k.replace('/', ' ')} ({v['paired_diff_mean']:+.3f} ± {v['paired_diff_se']:.3f})" for k, v in t["summary"].items()
             if k.split("/")[1] not in named and v["detectable_at_95pct"]]
    base = "The verdicts cover event F1 (event-counted), false alarms/day and category accuracy per event. "
    if other:
        return base + "Outside those three, a detectable paired difference appears for: " + "; ".join(other) + "."
    return base + "No other tabulated metric shows a detectable paired difference."


def evidence_table():
    lines = ["| Dataset | Stream | Model | Val segment-based event F1 | Best baseline on validation (same metric, baselines as now tuned) | "
             "Val Brier | Test event F1 (exposed split) | Test Brier |", "|---|---|---|---|---|---|---|---|"]
    for f in sorted((R / "evidence").glob("*__*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        b = d["best_baseline_val"]
        lines.append(f"| {d['dataset']} | {d['domain']} | {d['model_selected']} | {d['val']['event']['f1']:.3f} | "
                     f"{b['model']} {b['val_event_f1']:.3f} | {d['val']['brier']:.3f} | {d['test']['event']['f1']:.3f} | "
                     f"{d['test']['brier']:.3f} |")
    return "\n".join(lines)


def incident_note(inc):
    kinds = ", ".join(sorted(set(m.split("-")[0] for m in inc["models"])))
    return (f"**Incident (my mistake, disclosed).** {inc['what']} {inc['accesses']} baseline runs ({kinds}; "
            f"`isolation_forest-joint` is the Isolation Forest fitted on all four signals, a baseline) opened test_v2 at "
            f"{inc['first_access_utc'][:19]} UTC. No fusion design, threshold-voting rule or the single joint classifier was "
            f"involved, and the numbers were not inspected before the decision that followed. {inc['consequence']} "
            f"Rows marked † are baselines: their numbers here come from a second access. Evidence is kept in "
            f"`results/round2/incident_test_v2/`.")


def access_note(fin):
    notes = []
    for key, res in fin["results"].items():
        bad = [m for m, r in res.items() if not ok(r)]
        if bad:
            notes.append(f"{key}: not evaluated ({', '.join(bad)}; the test split was opened in a run that stopped before the "
                         f"predictions were stored, and it was not opened again)")
        twice = fin.get("second_access_after_interruption", {}).get(key, [])
        if twice:
            notes.append(f"{key}: evaluated on a second, separately logged access after an interrupted first one ({', '.join(twice)})")
    return ("**Access notes.** " + "; ".join(notes) + ".") if notes else "Every model has exactly one completed evaluation on every test set."


LIMITS = """- **No real field data with labels.** The infrastructure data (BattLeDIM) are simulated hydraulics with exact leak labels; quality data (USGS river stations) are real but unlabelled, so all quality events are injected.
- **Fusion is tested on semi-synthetic scenarios** (events injected into real/simulated backgrounds). Event shapes and sizes are assumptions (docs/scenarios.md); good scores show the method recovers those assumptions, not that it works on real incidents.
- **Test-set history.** test_v1 and the BattLeDIM test split were seen while F-B's decision rule was being changed in Round 1 and are reported only as "exposed"; the BattLeDIM split cannot be refreshed. test_v2 was scored by the baselines before the freeze by mistake, so it is secondary. test_v3 is the headline set: frozen first, each model evaluated once. Its file was loaded and featurised once by a dry run before the freeze; no model or metric used its test rows before the final run.
- **Metric definitions changed during Round 2, before the freeze and on validation data only.** The tuned objective and the verdict use event-counted F1 (the Round-1 segment-based F1 counts every alert fragment and is shown separately). Category accuracy now compares the set of streams reported during an event with the streams the event contains (the Round-1 "most frequent category" rule marked correct predictions wrong on Combined events). Numbers in `results_round1/` use the old definitions and are not comparable.
- **Alert duration is not penalised** by the event metrics or by the tuning objective. On BattLeDIM every tuned rule alerts on most rows (see "Rows in alert"), which is why its event scores are high; those BattLeDIM scores say little about detection quality.
- **Category accuracy is strict.** One alerting row of the wrong stream inside an event makes that event wrong, and the real river backgrounds contain unlabelled quality disturbances.
- **Same backgrounds in every scenario set.** test_v2 and test_v3 have new events but share the background series (and their drift from unlabelled BattLeDIM leaks) with test_v1; they refresh the events, not the background. One test_v3 event starts at the same time on the same node as a test_v1 event of the same type (chance; it is a different event).
- **Tuning grid edges.** Several tuned thresholds sit at the strict end of their grid (0.9 to 0.98) on the scenarios and at the permissive end on BattLeDIM; the validation optimum may lie beyond the grid.
- **Baselines and the joint model.** Baselines were re-tuned on validation per stream with the same objective; some cannot meet the cap (section 8). The joint model has no tunable alert threshold and was not tuned for the cap.
- **Mixed-origin nodes.** Scenario nodes pair BattLeDIM infrastructure series with Virginia river quality series; the 8 demo nodes are a fictional layout near Vellore.
- **Low-cost sensor caveats** (drift, fouling, noise, calibration) are not modelled beyond what the public series contain. TDS is a conductance proxy (0.64 x conductance).
- **Rule-based priority.** The escalation rule is a documented heuristic, not validated against operator judgement.
- **Small test sets and approximate intervals.** 60 scenario events per test set and 8 BattLeDIM test events. The bootstrap resamples events and days independently of each other and ignores dependence between neighbouring days; a zero-width interval means all resampled units agreed, not certainty.
- **Evidence modules are supervised** while the baselines are unsupervised; the comparison shows the value of labelled training, not a like-for-like detector contest.
- **Temporal-ablation caveat.** The five validation seeds share the background rows used to fit the calibrators.
- **The live demo runs the rule frozen here** (since Round 3, 2026-10-11; a deployment change, nothing was re-tuned or re-evaluated). With it, the demo's injected combined event is reported as Infrastructure, not Combined (docs/decisions.md, Round 3).
- **LeakDB not used** (30-minute sampling does not fit the 5-minute design; 13.9 GB archive).
- **Docker path exercised later (Round 6), not for these numbers.** Every result in this summary was produced in the fallback mode (SQLite plus in-process bus). The MQTT/TimescaleDB path was run and tested in Round 6 (three separate processes, `results/docker/part_b.json`); the evaluation uses neither the message bus nor the store, so no number here depends on it."""


def main(final_path=None, out_path=None):
    """final_path/out_path are only for smoke-testing the report on dry-run output; the real report uses the defaults."""
    if final_path:
        fin = json.loads(Path(final_path).read_text(encoding="utf-8"))
        alias = {"test_v3": "val_scenarios", "test_v2": "val_scenarios", "test_v1_exposed": "val_scenarios", BD: "val_battledim"}
        fin["results"] = {k: fin["results"][v] for k, v in alias.items()}
        fin["verdicts"] = {k: fin["verdicts"][v] for k, v in alias.items() if v in fin["verdicts"]}
    else:
        fin = jload("round2/final_results.json")
    sel = jload("round2/selection_val.json")
    tmp = jload("round2/temporal_ablation.json")
    inc = jload("round2/incident_test_v2/incident.json")
    cap = fin["false_alarm_cap_per_day"]
    r3, r2, r1, bd = fin["results"]["test_v3"], fin["results"]["test_v2"], fin["results"]["test_v1_exposed"], fin["results"][BD]
    models, bd_models = order(list(r3)), order(list(bd))
    is_base = lambda m: m.startswith("baseline")  # noqa: E731
    base_tab, base_note = baseline_table(cap)
    rule = fin["verdict_rule"]
    parts = [
        "# KAMI results summary (Round 2)" + (": SMOKE TEST ON VALIDATION ROWS, NOT RESULTS" if final_path else ""), "",
        headline(fin), "",
        "Generated by `python scripts/make_summary.py` from files in `results/`. Round 1 numbers are kept in `results_round1/` and "
        "use older metric definitions (see Limitations). Simulated-hydraulics BattLeDIM results and semi-synthetic scenario results "
        "are reported separately. Everything below uses the configuration frozen on validation "
        f"(`results/fusion/frozen_config.json`, commit `{fin['frozen_commit'][:10]}`). Intervals are bootstrap 95% "
        f"({fin['bootstrap']['resamples']} resamples, seed {fin['bootstrap']['seed']}). {access_note(fin)}", "",
        f"Verdict rule (fixed in the frozen configuration before any test access): metric = {rule['metric']}; {rule['comparison']}; "
        f"\"beats\" = {rule['beats']}; \"worse\" = {rule['worse']}; otherwise {rule['otherwise']}.", "",
        "## 1. Validation: constrained tuning and selection", "",
        f"Objective: {sel['objective']} (cap {sel['cap_false_alarms_per_day']} false alarms/day), out-of-fold (OOF) over four validation "
        f"time blocks. Selected fusion design: **{sel['selected']}** ({sel['selection_reason']}; the choice is between F-A and F-B). "
        f"Threshold voting is tuned the same way and is the comparison, not a candidate.", "", validation_table(sel["designs"]), "",
        "Parameter order: F-B = (r_min, tau, lambda, gamma_infra, gamma_quality); F-A and voting = (infrastructure threshold, quality "
        "threshold). " + same_rule_note(sel["designs"]), "",
        "## 2. Final evaluation on test_v3 (headline)", "", READING, "", final_table(r3, models), "",
        observations(r3, fin["selected_design"]), "", detail_table(r3, models), "",
        "## 3. Category separation on test_v3 (Infrastructure vs Quality vs Combined)", "",
        "Category accuracy per event = share of events for which the set of streams the model reports during the event equals the "
        "streams the event contains (Infrastructure reported if any row in the event window is predicted Infrastructure or "
        "Combined; Quality likewise; an undetected event counts as wrong). Row recall = share of labelled rows of that category "
        "predicted as exactly that category.", "", category_table(r3, models), "",
        "Detection by event type (share of events of that type with any alert inside them):", "", type_recall_table(r3, models), "",
        "## 4. Temporal features: with vs without (validation, five seeds)", "",
        f"- {tmp['verdict']['F-A']}", f"- {tmp['verdict']['F-B']}", "", temporal_extra(tmp), "", temporal_table(tmp), "",
        f"Caveat: {tmp['caveat']}", "",
        "## 5. test_v2 (secondary)", "", incident_note(inc), "", final_table(r2, models, is_base), "",
        detail_table(r2, models, is_base), "", category_table(r2, models, is_base), "",
        "## 6. BattLeDIM test (real labels on simulated data; exposed in Round 1; 8 events)", "",
        fin["notes"][BD] + " Read the \"Rows in alert\" column first: every tuned rule alerts on most rows here, so high event "
        "scores mean little, and a zero-width interval on 8 events is not certainty.", "", final_table(bd, bd_models), "",
        detail_table(bd, bd_models), "",
        f"BattLeDIM validation tuning ({sel['battledim']['validation_events']} validation events; {sel['battledim']['note']}):", "",
        validation_table(sel["battledim"]["designs"]), "", same_rule_note(sel["battledim"]["designs"]), "",
        "## 7. test_v1 (exposed, for reference only)", "", final_table(r1, models), "",
        "## 8. Baselines: validation tuning per stream (same objective and cap, including One-Class SVM)", "", base_tab, "", base_note, "",
        "Per-stream baseline results on the exposed splits (Round-1 style table): `results/tables/baselines.md`.", "",
        "## 9. Evidence modules (calibrated, Round 1; test numbers are on exposed splits)", "", evidence_table(), "",
        "Reliability curves: `results/figures/reliability_*.png`.", "",
        "## 10. Limitations", "", LIMITS, ""]
    out = Path(out_path) if out_path else R / "SUMMARY.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--final", default=None, help="smoke test only: read final results from this file")
    ap.add_argument("--out", default=None, help="smoke test only: write the report here instead of results/SUMMARY.md")
    a = ap.parse_args()
    if bool(a.final) != bool(a.out):
        ap.error("--final and --out must be given together (a smoke-test report must never overwrite results/SUMMARY.md)")
    main(a.final, a.out)
