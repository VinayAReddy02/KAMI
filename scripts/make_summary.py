"""Builds results/SUMMARY.md from the generated result files (no hand-typed numbers). Round 2 version.

Every number comes from: results/round2/final_results.json, selection_val.json, temporal_ablation.json,
incident_test_v2/incident.json, results/tables/baselines.md and results/evidence/*.json.
"""
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


def ci(v, c):
    return f"{f3(v)} [{c[0]:.3f}, {c[1]:.3f}]"


def ci2(v, c):
    return f"{v:.2f} [{c[0]:.2f}, {c[1]:.2f}]"


def order(names):
    pref = ["F-B", "F-A", "F-B (no temporal)", "F-A (no temporal)", VOTE, JOINT]
    return [n for n in pref if n in names] + sorted(n for n in names if n not in pref)


def compare(res, sel):
    """Fusion vs threshold voting on event F1 for one result set. Returns (verdict phrase, selected, voting)."""
    s, v = res[sel], res[VOTE]
    lo_s, hi_s = s["ci95"]["f1"]
    lo_v, hi_v = v["ci95"]["f1"]
    if lo_s > hi_v:
        verdict = "beats threshold voting (the 95% intervals do not overlap)"
    elif lo_v > hi_s:
        verdict = "does NOT beat threshold voting: it is worse (the 95% intervals do not overlap)"
    elif s["event"]["f1"] > v["event"]["f1"]:
        verdict = "does NOT beat threshold voting by a detectable margin: its point estimate is higher but the 95% intervals overlap"
    elif s["event"]["f1"] < v["event"]["f1"]:
        verdict = "does NOT beat threshold voting: its point estimate is lower (the 95% intervals overlap)"
    else:
        verdict = "does NOT beat threshold voting: the two are equal"
    return verdict, s, v


def headline(fin):
    sel, cap = fin["selected_design"], fin["false_alarm_cap_per_day"]
    verdict, s, v = compare(fin["results"]["test_v3"], sel)
    within = s["event"]["fa_per_day"] <= cap
    v2verdict, s2, v2 = compare(fin["results"]["test_v2"], sel)
    return "\n".join([
        f"**Outcome on the headline test set (test_v3: fresh events, method frozen first, each model evaluated once).** "
        f"With the method tuned for at most {cap} false alarms per day, the selected fusion design ({sel}) {verdict}. "
        f"Event F1: {sel} {ci(s['event']['f1'], s['ci95']['f1'])}, threshold voting on the same evidence "
        f"{ci(v['event']['f1'], v['ci95']['f1'])}. False alarms per day: {sel} "
        f"{ci2(s['event']['fa_per_day'], s['ci95']['fa_per_day'])} ({'within' if within else 'ABOVE'} the cap), threshold voting "
        f"{ci2(v['event']['fa_per_day'], v['ci95']['fa_per_day'])}.",
        "",
        f"Category accuracy per event (is the alert category the right one of Infrastructure, Quality, Combined?): {sel} "
        f"{ci(s['category_accuracy_event'], s['ci95']['category_accuracy'])}, threshold voting "
        f"{ci(v['category_accuracy_event'], v['ci95']['category_accuracy'])} (section 3).",
        "",
        f"Secondary set test_v2: {sel} {v2verdict}. Event F1 {ci(s2['event']['f1'], s2['ci95']['f1'])} versus "
        f"{ci(v2['event']['f1'], v2['ci95']['f1'])} (section 5, with the incident note).",
    ])


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def final_table(res, models, flag=None):
    out = ["| Model | Event F1 [95% CI] | Event precision [95% CI] | Event recall [95% CI] | False alarms/day [95% CI] | "
           "Latency median (h) | Rows in alert | Normal rows in alert |",
           "|---|---|---|---|---|---|---|---|"]
    for m in models:
        r = res[m]
        e, c = r["event"], r["ci95"]
        name = m + (" †" if flag and flag(m) else "")
        out.append(f"| {name} | {ci(e['f1'], c['f1'])} | {ci(e['precision'], c['precision'])} | {ci(e['recall'], c['recall'])} | "
                   f"{ci2(e['fa_per_day'], c['fa_per_day'])} | {f3(e['latency_median_h'])} | {pct(r['alert_row_fraction'])} | "
                   f"{pct(r['normal_rows_in_alert_fraction'])} |")
    return "\n".join(out)


READING = ("How to read the tables: an alert segment is a run of alerting rows (gaps up to 1 h merged). Event recall = events with "
           "any alert inside them; event precision = alert segments that overlap an event; false alarms/day = segments that "
           "overlap no event, per day of normal data. These event metrics do not penalise how long an alert lasts: a model "
           "that alerts almost all the time has few, long segments and can score well. The last two columns show that directly "
           "(share of scored rows in alert, and share of normal rows in alert).")


def category_table(res, models, flag=None):
    types = sorted({t for m in models for t in res[m]["per_type"]})
    out = ["| Model | Category accuracy per event [95% CI] | Macro-F1 (rows) | Row recall Infrastructure | Row recall Quality | "
           "Row recall Combined | " + " | ".join(f"{t}: category correct" for t in types) + " |",
           "|---|---|---|---|---|---|" + "---|" * len(types)]
    for m in models:
        r = res[m]
        pc = r["per_category_point_recall"]
        name = m + (" †" if flag and flag(m) else "")
        cells = [f"{r['per_type'][t]['category_correct']:.2f} (n={r['per_type'][t]['events']})" if t in r["per_type"] else "-"
                 for t in types]
        out.append(f"| {name} | {ci(r['category_accuracy_event'], r['ci95']['category_accuracy'])} | {f3(r['macro_f1'])} | "
                   f"{f3(pc['Infrastructure'])} | {f3(pc['Quality'])} | {f3(pc['Combined'])} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def same_rule_note(designs):
    """F-B without temporal features has reliability 1, i.e. the rule p >= threshold: the voting rule."""
    nt, vote = designs["F-B (no temporal)"]["final_params"][3:], designs[VOTE]["final_params"]
    base = ("Note: F-B without temporal features has reliability fixed at 1, so its rule is `p >= threshold` per stream, which is "
            "the threshold-voting rule; the two differ only in the threshold grid searched. ")
    if [float(x) for x in nt] == [float(x) for x in vote]:
        return base + f"Here both froze to the same thresholds {vote}, so their rows below are identical by construction."
    return base + f"Here they froze to different thresholds ({nt} vs {vote})."


def validation_table(designs):
    out = ["| Design | OOF event F1 | OOF false alarms/day | Feasible at cap | OOF macro-F1 | OOF category acc. | Frozen parameters |",
           "|---|---|---|---|---|---|---|"]
    for k, v in designs.items():
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
    lines = ["| Dataset | Domain | Model | Val event F1 | Best baseline (val, Round 1 tuning) | Val Brier | Test event F1 (exposed split) | Test Brier |",
             "|---|---|---|---|---|---|---|---|"]
    for f in sorted((R / "evidence").glob("*__*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        b = d["best_baseline_val"]
        lines.append(f"| {d['dataset']} | {d['domain']} | {d['model_selected']} | {d['val']['event']['f1']:.3f} | "
                     f"{b['model']} {b['val_event_f1']:.3f} | {d['val']['brier']:.3f} | {d['test']['event']['f1']:.3f} | "
                     f"{d['test']['brier']:.3f} |")
    return "\n".join(lines)


def incident_note(inc):
    return (f"**Incident (my mistake, disclosed).** {inc['what']} {inc['accesses']} baseline runs "
            f"({', '.join(sorted(set(m.split('-')[0] for m in inc['models'])))}) opened test_v2 at {inc['first_access_utc'][:19]} UTC. "
            f"No fusion, voting or joint model was involved, and the numbers were not inspected before the decision that followed. "
            f"{inc['consequence']} Rows marked † are baselines: their numbers here come from a second access. "
            f"Evidence is kept in `results/round2/incident_test_v2/`.")


LIMITS = """- **No real field data with labels.** The infrastructure data (BattLeDIM) are simulated hydraulics with exact leak labels; quality data (USGS river stations) are real but unlabelled, so all quality events are injected.
- **Fusion is tested on semi-synthetic scenarios** (events injected into real/simulated backgrounds). Event shapes and sizes are assumptions (docs/scenarios.md); good scores show the method recovers those assumptions, not that it works on real incidents.
- **Test-set history.** test_v1 and the BattLeDIM test split were seen while F-B's decision rule was being changed in Round 1 and are reported only as "exposed"; the BattLeDIM split cannot be refreshed. test_v2 was scored by the baselines before the freeze by mistake, so it is secondary. test_v3 is the only set with a clean history: generated after that incident, frozen first, each model evaluated once.
- **Same backgrounds in every scenario set.** test_v2 and test_v3 have new events but share the background series (and their drift from unlabelled BattLeDIM leaks) with test_v1; they refresh the events, not the background. One test_v3 event starts at the same time on the same node as a test_v1 event of the same type (chance; it is a different event).
- **Tuning grid edges.** Several tuned thresholds sit at the strict end of their grid (0.95 to 0.98); the validation optimum may lie beyond it.
- **Baselines and the joint model.** Baselines were re-tuned on validation under the same false-alarm cap per domain; the joint model has no tunable alert threshold and was not tuned for the cap.
- **Mixed-origin nodes.** Scenario nodes pair BattLeDIM infrastructure series with Virginia river quality series; the 8 demo nodes are a fictional layout near Vellore.
- **Low-cost sensor caveats** (drift, fouling, noise, calibration) are not modelled beyond what the public series contain. TDS is a conductance proxy (0.64 x conductance).
- **Rule-based priority.** The escalation rule is a documented heuristic, not validated against operator judgement.
- **Small test sets.** 60 scenario events per test set and 8 BattLeDIM test events. The bootstrap intervals show how wide the uncertainty is; they resample events, alert segments and days independently and ignore dependence between neighbouring days, so they are approximate.
- **Evidence modules are supervised** while the baselines are unsupervised; the comparison shows the value of labelled training, not a like-for-like detector contest.
- **Temporal-ablation caveat.** The five validation seeds share the background rows used to fit the calibrators.
- **LeakDB not used** (30-minute sampling does not fit the 5-minute design; 13.9 GB archive).
- **No Docker run.** The MQTT/TimescaleDB path is implemented but was not exercised in this environment (fallback SQLite plus in-process bus was used)."""


def main():
    fin = jload("round2/final_results.json")
    sel = jload("round2/selection_val.json")
    tmp = jload("round2/temporal_ablation.json")
    inc = jload("round2/incident_test_v2/incident.json")
    r3, r2 = fin["results"]["test_v3"], fin["results"]["test_v2"]
    bd = fin["results"]["battledim_test_previously_exposed"]
    models = order(list(r3))
    is_base = lambda m: m.startswith("baseline")  # noqa: E731
    parts = [
        "# KAMI results summary (Round 2)", "", headline(fin), "",
        "Generated by `python scripts/make_summary.py` from files in `results/`. Round 1 numbers are kept in `results_round1/`. "
        "Simulated-hydraulics BattLeDIM results and semi-synthetic scenario results are reported separately. Everything below uses "
        "the configuration frozen on validation (`results/fusion/frozen_config.json`). Intervals are bootstrap 95% "
        f"({fin['bootstrap']['resamples']} resamples, seed {fin['bootstrap']['seed']}).", "",
        "## 1. Validation: constrained tuning and selection", "",
        f"Objective: maximise event F1 subject to at most {sel['cap_false_alarms_per_day']} false alarms per day, out-of-fold over "
        f"four validation time blocks. Selected: **{sel['selected']}** ({sel['selection_reason']}). Frozen at commit "
        f"`{fin['frozen_commit'][:10]}` before any test_v3 access.", "", validation_table(sel["designs"]), "",
        "Parameter order: F-B = (r_min, tau, lambda, gamma_infra, gamma_quality); F-A and voting = (infra threshold, quality threshold). "
        + same_rule_note(sel["designs"]), "",
        "## 2. Final evaluation on test_v3 (headline)", "", READING, "", final_table(r3, models), "",
        "## 3. Category separation on test_v3 (Infrastructure vs Quality vs Combined)", "",
        "Category accuracy per event = share of events whose most frequent alert category inside the event window is the true "
        "category (an undetected event counts as wrong). Row recall = share of labelled rows of that category predicted as it.", "",
        category_table(r3, models), "",
        "## 4. Temporal features: with vs without (validation, five seeds)", "",
        f"- {tmp['verdict']['F-A']}", f"- {tmp['verdict']['F-B']}", "", temporal_table(tmp), "", f"Caveat: {tmp['caveat']}", "",
        "## 5. test_v2 (secondary)", "", incident_note(inc), "", final_table(r2, models, is_base), "",
        category_table(r2, models, is_base), "",
        "## 6. BattLeDIM test (real labels on simulated data; previously exposed for F-B; 8 events)", "",
        fin["notes"]["battledim_test_previously_exposed"], "", final_table(bd, order(list(bd))), "",
        f"BattLeDIM validation tuning ({sel['battledim']['validation_events']} validation events; {sel['battledim']['note']}):", "",
        validation_table(sel["battledim"]["designs"]), "",
        "## 7. test_v1 (exposed, for reference only)", "", final_table(fin["results"]["test_v1_exposed"], models), "",
        "## 8. Baselines per domain (validation-tuned under the same cap, including One-Class SVM; evaluated on exposed splits)", "",
        body("tables/baselines.md"), "",
        "## 9. Evidence modules (calibrated, Round 1; test numbers are on exposed splits)", "", evidence_table(), "",
        "Reliability curves: `results/figures/reliability_*.png`.", "",
        "## 10. Limitations", "", LIMITS, ""]
    (R / "SUMMARY.md").write_text("\n".join(parts), encoding="utf-8")
    print("wrote results/SUMMARY.md")


if __name__ == "__main__":
    main()
