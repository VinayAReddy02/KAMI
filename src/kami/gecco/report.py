"""GECCO real-data test: the report (Round 7, G5). Reads only stored files; never opens the test file.

    python -m kami.gecco.report      # results/gecco/eval.json, eval.md and figures/

Inputs: results/gecco/predictions/<model>.csv (test predictions with their labels, written at the guarded read),
predictions/test_minutes.csv (1-minute labels, for GECCO's own point-wise score), frozen_gecco.json and
val_variant_a.json (validation results), and the sensor values of the frame (no labels) for the plots.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..eval import bootstrap
from ..eval.fast_eval import AnyEvaluator
from ..eval.metrics import domain_events
from . import data as G
from . import evaluate as E

OUT = E.OUT
NAMES = {"A": "A: frozen transfer (Round 2 module and rule, nothing refitted)", "B": "B: adapted (same features and model family, refitted on GECCO)",
         "fixed_threshold": "baseline: fixed thresholds", "isolation_forest": "baseline: Isolation Forest", "ocsvm": "baseline: One-Class SVM"}
CI_KEYS = ("recall", "precision", "precision_event_counted", "f1", "f1_event_counted", "fa_per_day")


def load_predictions(model: str) -> pd.DataFrame:
    p = pd.read_csv(E.PRED / f"{model}.csv", encoding="utf-8", keep_default_na=False)
    p["ts"] = pd.to_datetime(p.ts)
    p["node_id"] = G.NODE
    p["event_type"] = np.where(p.event_id != "", G.EVENT_TYPE, "")
    p["ambiguous"] = False
    for c in ("quality_flag", "scored", "pred"):
        p[c] = p[c].astype(str).str.lower().eq("true")
    return p


def minute_f1(pred: pd.DataFrame, minutes: pd.DataFrame) -> dict:
    """GECCO's own score (f1score.R): point-wise F1 on the 1-minute rows. A minute gets the decision of the latest
    5-minute step that ENDED at or before it (causal; up to 5 minutes late). Context only."""
    steps = pred[["ts", "pred"]].assign(end=pred.ts + pd.Timedelta("5min")).sort_values("end")
    m = minutes.sort_values("ts")
    j = pd.merge_asof(m, steps[["end", "pred"]], left_on="ts", right_on="end", direction="backward")
    yhat = j.pred.fillna(False).astype(bool).to_numpy()
    y = m.event.astype(bool).to_numpy()
    tp, fp, fn = int((yhat & y).sum()), int((yhat & ~y).sum()), int((~yhat & y).sum())
    ppv = tp / (tp + fp) if tp + fp else 0.0
    tpr = tp / (tp + fn) if tp + fn else 0.0
    return {"f1": 2 * ppv * tpr / (ppv + tpr) if ppv + tpr else 0.0, "tp": tp, "fp": fp, "fn": fn}


def model_result(p: pd.DataFrame, minutes: pd.DataFrame) -> tuple[dict, dict]:
    sc = p.scored.to_numpy()
    m = E.score(p, p.pred.to_numpy(), sc)
    det = AnyEvaluator(E.labelled(p), domain_events(E.labelled(p), "quality"), sc, flag_col="quality_flag")(p.pred.to_numpy() & sc, details=True)["detail"]
    reps = bootstrap.replicates(det, np.ones(len(det["event_detected"])))
    out = E.compact(m)
    out["ci95"] = {k: bootstrap.ci(reps[k]) for k in CI_KEYS}
    out["alert_steps"] = int((p.pred & p.scored).sum())
    out["competition_f1_1min"] = minute_f1(p, minutes)
    out["events_detail"] = {"detected": det["event_detected"].tolist(), "latency_h": [None if np.isnan(x) else float(x) for x in det["event_latency_h"]]}
    return out, reps


def event_table(preds: dict) -> list[dict]:
    p0 = next(iter(preds.values()))
    rows = []
    for eid, g in p0[p0.event_id != ""].groupby("event_id", sort=True):
        a, b = g.ts.min(), g.ts.max()
        r = {"event_id": eid, "start": a.strftime("%Y-%m-%d %H:%M"), "end": (b + pd.Timedelta("5min")).strftime("%Y-%m-%d %H:%M"),
             "steps": len(g), "scored_steps": int(g.scored.sum())}
        for mid, p in preds.items():
            w = p[(p.ts >= a) & (p.ts <= b)]
            hit = w[w.pred & w.scored]
            r[mid] = None if hit.empty else round((hit.ts.iloc[0] - a).total_seconds() / 3600, 2)
        rows.append(r)
    return rows


def figures(preds: dict, events: list[dict]) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = G.build_frame()  # sensor values only; the labels come from the stored predictions
    df = df[df.split == "test"].set_index("ts")
    out = []
    E.OUT.joinpath("figures").mkdir(parents=True, exist_ok=True)
    chosen = sorted(events, key=lambda e: -e["steps"])[:2]  # the two longest test events
    for e in chosen:
        a, b = pd.Timestamp(e["start"]) - pd.Timedelta("6h"), pd.Timestamp(e["end"]) + pd.Timedelta("6h")
        w = df.loc[a:b]
        fig, ax = plt.subplots(3, 1, figsize=(9, 6.2), sharex=True, gridspec_kw={"height_ratios": [3, 3, 1.6]})
        for axis, col, unit in ((ax[0], "turbidity", "FNU"), (ax[1], "tds", "mg/L (from conductivity)")):
            axis.plot(w.index, w[col], lw=1, color="#1f4e79")
            axis.axvspan(pd.Timestamp(e["start"]), pd.Timestamp(e["end"]), color="#c0504d", alpha=0.18, lw=0)
            axis.set_ylabel(f"{col}\n{unit}")
        for i, (mid, p) in enumerate(preds.items()):
            s = p[(p.ts >= a) & (p.ts <= b)]
            on = s.ts[s.pred & s.scored]
            ax[2].scatter(on, np.full(len(on), i), marker="|", s=60, color="#333333")
        ax[2].axvspan(pd.Timestamp(e["start"]), pd.Timestamp(e["end"]), color="#c0504d", alpha=0.18, lw=0)
        ax[2].set_yticks(range(len(preds)), list(preds), fontsize=8)
        ax[2].set_ylim(-0.7, len(preds) - 0.3)
        ax[2].set_ylabel("alerts")
        ax[0].set_title(f"GECCO 2019 test part, real labelled event {e['event_id']} (shaded); data: real, quality stream only", fontsize=9)
        fig.autofmt_xdate()
        fig.tight_layout()
        name = f"figures/gecco_test_event_{e['event_id'].split('-')[-1]}.png"
        fig.savefig(E.OUT / name, dpi=110)
        plt.close(fig)
        out.append(name)
    return out


def f3(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def ci_txt(r: dict, k: str) -> str:
    lo, hi = r["ci95"][k]
    return f"{f3(r['event'][k] if k in r['event'] else r['false_alarms_per_day'])} [{lo:.3f}, {hi:.3f}]"


def build() -> dict:
    fz = json.loads(E.FROZEN.read_text(encoding="utf-8"))
    val_a = json.loads((E.OUT / "val_variant_a.json").read_text(encoding="utf-8"))
    log = json.loads(E.LOG.read_text(encoding="utf-8"))
    minutes = pd.read_csv(E.PRED / "test_minutes.csv", encoding="utf-8")
    minutes["ts"] = pd.to_datetime(minutes.ts)
    minutes["event"] = minutes.event.astype(str).str.lower().eq("true")
    preds = {m: load_predictions(m) for m in E.MODELS}
    test, reps = {}, {}
    for m, p in preds.items():
        test[m], reps[m] = model_result(p, minutes)
    best = fz["best_baseline"]
    paired = {"B - best baseline": bootstrap.paired_diff(reps["B"], reps[best]), "A - best baseline": bootstrap.paired_diff(reps["A"], reps[best]),
              "B - A": bootstrap.paired_diff(reps["B"], reps["A"])}
    paired = {k: {m: v[m] for m in CI_KEYS} for k, v in paired.items()}
    events = event_table(preds)
    split_info = {s: G.event_counts(s) for s in ("train", "val")}
    t_steps = preds["A"]
    split_info["test"] = {"events_5min": len(events), "event_steps": int(t_steps.quality_flag.sum()), "steps": len(t_steps),
                          "events_1min": len(G.runs(minutes.event.to_numpy())), "event_minutes": int(minutes.event.sum())}
    validation = {"A": val_a["validation"], "B": fz["B"]["validation"], **{m: fz["baselines"][m]["validation"] for m in fz["baselines"]}}
    res = {"made_by": "src/kami/gecco/report.py", "run_utc": E.now(), "data_kind": G.DATA_KIND, "scope": "quality stream only (turbidity and TDS from conductivity)",
           "dataset": "GECCO Industrial Challenge 2019 (Zenodo 10.5281/zenodo.4304080, CC-BY-4.0)", "protocol": "docs/gecco_protocol.md",
           "splits": split_info, "frozen": {"B": fz["B"]["params"] | {"model": fz["B"]["model"]}, "baselines": {m: v["params"] for m, v in fz["baselines"].items()},
                                             "best_baseline": best, "A": val_a["frozen_rule"]},
           "test_reads": [{k: r.get(k) for k in ("model", "utc", "completed_utc")} for r in log],
           "test": test, "validation": validation, "paired": paired, "events": events}
    res["figures"] = figures(preds, events)
    E.write_json(OUT / "eval.json", res)
    (OUT / "eval.md").write_text(markdown(res), encoding="utf-8", newline="\n")
    return res


def verdict_lines(r: dict) -> list[str]:
    """Plain statements generated from the numbers (no hand-typed values)."""
    t, best = r["test"], r["frozen"]["best_baseline"]
    n = r["splits"]["test"]["events_5min"]
    out = []
    a = t["A"]["event"]
    out.append(f"- **Frozen transfer (A):** the Round 2 quality module and rule, trained only on semi-synthetic events in river data, "
               f"detected {a['detected']} of {n} real test events with {t['A']['event']['false_alert_segments']} false alarm segments "
               + ("(it raised no alert at all). The frozen evidence does not transfer to this drinking-water data without refitting."
                  if t["A"]["alert_steps"] == 0 else "."))
    b = t["B"]["event"]
    d = r["paired"]["B - best baseline"]["f1_event_counted"]
    out.append(f"- **Adapted (B):** refitted on GECCO train and tuned on validation, it detected {b['detected']} of {n} test events, event-counted F1 "
               f"{f3(b['f1_event_counted'])}, {f3(t['B']['false_alarms_per_day'])} false alarms per day. Against the best baseline on validation "
               f"({best}) the paired difference in event-counted F1 has the interval [{d['ci95'][0]:.3f}, {d['ci95'][1]:.3f}]: "
               + ("B is better on this test part." if d["ci95"][0] > 0 else "B is worse on this test part." if d["ci95"][1] < 0
                  else "no difference can be shown on this test part."))
    if n < 10:
        out.append(f"- The test part has only {n} events, so every interval is wide; these are indications, not general results.")
    return out


def markdown(r: dict) -> str:
    t, v = r["test"], r["validation"]
    L = ["# Real-data test on GECCO 2019 (quality stream only)", "",
         f"Generated by `{r['made_by']}` ({r['run_utc']}) from the stored predictions; protocol `{r['protocol']}` (committed before any test label was read).",
         f"Data: {r['dataset']}, **real** drinking-water sensor data with labelled events. Scope: **{r['scope']}**. KAMI's infrastructure results stay semi-synthetic; "
         "this test says nothing about leaks or bursts. pH and SAC are not KAMI inputs, so events visible only there cannot be found by design.", "",
         "## Data", "", "| Split | GECCO file | 5-min steps | events (1 min) | events (5 min) |", "|---|---|---|---|---|"]
    files = {"train": "7 (train)", "val": "8 (valid)", "test": "6 (test), locked"}
    for s in ("train", "val", "test"):
        x = r["splits"][s]
        L.append(f"| {s} | {files[s]} | {x['steps']} | {x['events_1min']} | {x['events_5min']} |")
    L += ["", "## What the test shows", "", *verdict_lines(r), "",
          "## Test part (locked; one read per model)", "",
          "Event metrics on 5-minute steps (Round 2 definitions); 95 % bootstrap intervals in brackets (events and days resampled).", "",
          "| Model | Events detected | Recall | Event-counted F1 | Segment F1 | False alarms / day | Latency median / p90 (h) | Point F1 | GECCO score (1-min F1) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for m in E.MODELS:
        x = t[m]
        lat = x["latency_h"]
        L.append(f"| {NAMES[m]} | {x['event']['detected']} of {x['event']['events']} | {ci_txt(x, 'recall')} | {ci_txt(x, 'f1_event_counted')} | {ci_txt(x, 'f1')} | "
                 f"{ci_txt(x, 'fa_per_day')} | {f3(lat['median'])} / {f3(lat['p90'])} | {f3(x['point']['f1'])} | {f3(x['competition_f1_1min']['f1'])} |")
    L += ["", f"Best baseline (chosen on validation, before the test read): **{r['frozen']['best_baseline']}**.", "",
          "### Paired differences (same resampled events and days)", "", "| Difference | Event-counted F1 | Recall | False alarms / day |", "|---|---|---|---|"]
    for k, d in r["paired"].items():
        L.append(f"| {k} | [{d['f1_event_counted']['ci95'][0]:.3f}, {d['f1_event_counted']['ci95'][1]:.3f}] | [{d['recall']['ci95'][0]:.3f}, {d['recall']['ci95'][1]:.3f}] | "
                 f"[{d['fa_per_day']['ci95'][0]:.3f}, {d['fa_per_day']['ci95'][1]:.3f}] |")
    L += ["", "A difference is shown only if its interval excludes 0.", "", "## Validation (tuning data, for comparison)", "",
          "| Model | Events detected | Event-counted F1 | False alarms / day |", "|---|---|---|---|"]
    for m in E.MODELS:
        x = v[m]
        L.append(f"| {NAMES[m]} | {x['event']['detected']} of {x['event']['events']} | {f3(x['event']['f1_event_counted'])} | {f3(x['false_alarms_per_day'])} |")
    L += ["", "## Frozen settings", "", f"- A: {r['frozen']['A']['label']} {r['frozen']['A']['params']} (from `results/fusion/frozen_config.json`).",
          f"- B: model `{r['frozen']['B']['model']}`, rule parameters " + ", ".join(f"{k} = {x}" for k, x in r["frozen"]["B"].items() if k != "model") + ".",
          *[f"- {m}: " + ", ".join(f"{k} = {x}" for k, x in p.items()) for m, p in r["frozen"]["baselines"].items()], "",
          "## Test events", "", "Latency in hours from the event start to the first alert inside the event; '-' = missed.", "",
          "| Event | Start | End | Steps | " + " | ".join(E.MODELS) + " |", "|---|---|---|---|" + "---|" * len(E.MODELS)]
    for e in r["events"]:
        L.append(f"| {e['event_id']} | {e['start']} | {e['end']} | {e['steps']} | " + " | ".join("-" if e[m] is None else f"{e[m]:.2f}" for m in E.MODELS) + " |")
    L += ["", "## Figures", "", *[f"![{f}]({f})" for f in r["figures"]], "",
          "## Test reads", "", *[f"- {x['model']}: read {x['utc']}, completed {x['completed_utc']}" for x in r["test_reads"]], ""]
    return "\n".join(L)


if __name__ == "__main__":
    r = build()
    print("wrote results/gecco/eval.json and eval.md;", {m: r["test"][m]["event"]["detected"] for m in E.MODELS}, "events detected of", r["splits"]["test"]["events_5min"])
