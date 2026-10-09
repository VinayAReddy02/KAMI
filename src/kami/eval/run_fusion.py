"""python -m kami.eval.run_fusion -> fusion designs, ablations, confusion matrices, selection log.

Fusion designs are fitted on the validation split only (the evidence probabilities on train are in-sample).
Validation macro-F1 of the fitted designs is out-of-fold over 4 contiguous time blocks. The test split is
opened once per model and dataset through `final_evaluation`.
"""
from __future__ import annotations

import json
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from ..models.baselines import FixedThreshold, IsoForest
from ..models.evidence import N_BLOCKS, time_blocks
from ..models.fusion import CATS, FusionA, FusionB, assess, macro_f1
from .access import SplitData, final_evaluation
from .data import DATASETS, DOMAIN_SIGNALS, PROC, RES, domain_features, load_dataset, scored_mask
from .metrics import evaluate
from .run_evidence import events_for

LOG = RES / "fusion" / "test_eval_log.json"
TYPE_CAT = {"infra_leak": 1, "infra_burst": 1, "quality_turbidity_surge": 2, "quality_tds_shift": 2, "combined": 3}
SELECT_TIE = 0.005


# ------------------------------------------------------------------ data
def build_frame(name: str) -> pd.DataFrame:
    full = load_dataset(name)
    ev = pd.read_parquet(PROC / f"evidence_{name}.parquet").drop(columns=["ts", "node_id", "split"])
    df = pd.concat([full, ev], axis=1)
    if name == "battledim":
        df["p_quality"] = np.where(df.p_infra.notna(), 0.0, np.nan)
        for t in ("suddenness", "persist_steps", "persist_frac", "recurrence"):
            df[f"quality_{t}"] = 0.0
    df["y"] = df.infra_flag.astype(int) + 2 * df.quality_flag.astype(int)
    df["any_flag"] = df.infra_flag | df.quality_flag
    return df


def fusion_mask(df: pd.DataFrame, name: str) -> np.ndarray:
    m = df.p_infra.notna()
    if name != "battledim":
        m &= df.p_quality.notna()
    return m.to_numpy()


def any_events(name: str, df: pd.DataFrame) -> pd.DataFrame:
    if name == "battledim":
        return events_for(name, df, "infra")
    e = df[df.any_flag & (df.event_id != "")]
    g = e.groupby(["node_id", "event_id"]).agg(type=("event_type", "first"), start=("ts", "min"), end=("ts", "max"))
    return g.reset_index()


# ------------------------------------------------------------------ evaluation
def confusion(y, pred) -> list[list[int]]:
    m = np.zeros((4, 4), int)
    np.add.at(m, (np.asarray(y), np.asarray(pred)), 1)
    return m.tolist()


def eval_category(df: pd.DataFrame, pred: np.ndarray, mask: np.ndarray, name: str) -> dict:
    y = df.y.to_numpy()
    pred = np.where(mask, pred, 0)
    ym, pm = y[mask], pred[mask]
    out = {"macro_f1": macro_f1(ym, pm), "accuracy": float((ym == pm).mean()), "confusion": confusion(ym, pm),
           "classes_present": [CATS[c] for c in np.unique(ym)], "scored_rows": int(mask.sum())}
    out["infra_domain"] = evaluate(df, np.isin(pred, [1, 3]), "infra", events=events_for(name, df, "infra"), scored=mask)
    if name != "battledim":
        out["quality_domain"] = evaluate(df, np.isin(pred, [2, 3]), "quality", events=events_for(name, df, "quality"), scored=mask)
    ev = any_events(name, df)
    out["any_alert"] = evaluate(df, pred > 0, "any", events=ev, scored=mask)
    # category correctness per event: modal non-Normal category inside the window vs the true category
    d = df.assign(_p=pred)
    ok = tot = 0
    for _, e in ev.iterrows():
        w = d[(d.node_id == e.node_id) & (d.ts >= e.start) & (d.ts <= e.end)]
        w = w[w._p > 0]
        tot += 1
        if len(w) and w._p.mode().iloc[0] == TYPE_CAT[e.type]:
            ok += 1
    out["event_category_accuracy"] = ok / tot if tot else 0.0
    return out


def fit_oof(factory, val: pd.DataFrame, y: np.ndarray) -> tuple[np.ndarray, object]:
    """Out-of-fold predictions over contiguous time blocks, plus the final model fitted on all of val."""
    blocks = time_blocks(val.ts, N_BLOCKS)
    oof = np.zeros(len(val), int)
    for b in range(N_BLOCKS):
        te, tr = blocks == b, blocks != b
        m = factory().fit(val[tr], y[tr])
        oof[te] = m.predict(val[te])
    return oof, factory().fit(val, y)


# ------------------------------------------------------------------ baselines and joint model as category predictors
def baseline_predictors(name: str, full: pd.DataFrame, train: pd.DataFrame) -> dict:
    """Refit the tuned baselines of Step 3 (same parameters and seeds) and wrap them as category predictors."""
    domains = DATASETS[name][2]
    masks = {d: scored_mask(full, d) for d in domains}
    preds = {}
    for model in ("fixed_threshold", "isolation_forest"):
        dets = {}
        for d in domains:
            params = json.loads((RES / "baselines" / f"{name}__{d}__{model}.json").read_text(encoding="utf-8"))["params"]
            tr = train[masks[d].loc[train.index]]
            if model == "fixed_threshold":
                dets[d] = FixedThreshold(DOMAIN_SIGNALS[d], params["k"]).fit(tr)
            else:
                if len(tr) > 150_000:
                    tr = tr.sample(150_000, random_state=0).sort_index()
                dets[d] = IsoForest(domain_features(d, full.columns), params["n_estimators"], params["max_samples"],
                                    params["quantile"]).fit(tr)

        def predict(df, dets=dets):
            a_i = dets["infra"].predict(df)
            a_q = dets["quality"].predict(df) if "quality" in dets else np.zeros(len(df), bool)
            return a_i.astype(int) + 2 * a_q.astype(int)
        preds[model] = predict
    return preds


def joint_predictor(name: str, full: pd.DataFrame, train: pd.DataFrame):
    d = "infra" if name == "battledim" else "joint"
    cols = domain_features(d, full.columns)
    m_tr = scored_mask(full, d).loc[train.index].to_numpy()
    tr = train[m_tr]
    if len(tr) > 250_000:
        tr = tr.sample(250_000, random_state=0).sort_index()
    clf = HistGradientBoostingClassifier(max_depth=6, max_iter=150, random_state=0, class_weight="balanced")
    clf.fit(tr[cols].to_numpy(float), tr.y.to_numpy())

    def predict(df):
        X = df[cols].to_numpy(float)
        out = np.zeros(len(df), int)
        ok = np.isfinite(X).all(axis=1)
        if ok.any():
            out[ok] = clf.predict(X[ok])
        return out
    return predict


# ------------------------------------------------------------------ main per dataset
def run_dataset(name: str) -> dict:
    full = build_frame(name)
    data = SplitData(full)
    train, val = data.train(), data.val()
    quality = name != "battledim"
    streams = ("infra", "quality") if quality else ("infra",)
    mv = fusion_mask(val, name)
    vm = val[mv]
    yv = vm.y.to_numpy()

    def masked(f):
        def predict(df):
            out = np.zeros(len(df), int)
            ok = fusion_mask(df, name)
            if ok.any():
                out[ok] = f.predict(df[ok])
            return out
        return predict

    designs = {
        "F-A": lambda: FusionA(True, streams),
        "F-B": lambda: FusionB(True, quality),
        "F-A (no temporal)": lambda: FusionA(False, streams),
        "F-B (no temporal)": lambda: FusionB(False, quality),
    }
    models: dict[str, dict] = {}
    for mid, fac in designs.items():
        oof, final = fit_oof(fac, vm, yv)
        pv = np.zeros(len(val), int)
        pv[mv] = oof
        models[mid] = {"predict": masked(final), "val_pred": pv, "obj": final,
                       "params": getattr(final, "params", None)}
    # simple threshold voting on the evidence probabilities with the Step-4 operating points
    tau = {d: json.loads((RES / "evidence" / f"{name}__{d}.json").read_text(encoding="utf-8"))["tau"]
           for d in (("infra", "quality") if quality else ("infra",))}

    def vote(df):
        a_i = df.p_infra.fillna(0).to_numpy() >= tau["infra"]
        a_q = (df.p_quality.fillna(0).to_numpy() >= tau["quality"]) if quality else np.zeros(len(df), bool)
        return a_i.astype(int) + 2 * a_q.astype(int)
    models["threshold voting (no fusion)"] = {"predict": vote}
    models["single joint model (no separated evidence)"] = {"predict": joint_predictor(name, full, train)}
    for k, fn in baseline_predictors(name, full, train).items():
        models[f"baseline: {k}"] = {"predict": fn}

    rows = []
    for mid, m in models.items():
        vp = m.get("val_pred")
        if vp is None:
            vp = np.where(mv, m["predict"](val), 0)
        val_res = eval_category(val, vp, mv, name)
        with final_evaluation(f"{mid}", name, LOG):
            test = data.test()
        mt = fusion_mask(test, name)
        tp = np.where(mt, m["predict"](test), 0)
        test_res = eval_category(test, tp, mt, name)
        rows.append({"dataset": name, "model": mid, "val": val_res, "test": test_res, "params": m.get("params")})
        print(f"  {name:10s} {mid:45s} val macroF1 {val_res['macro_f1']:.3f} test macroF1 {test_res['macro_f1']:.3f} "
              f"event F1(any) {test_res['any_alert']['event']['f1']:.3f}", flush=True)
    result = {"dataset": name, "rows": rows}
    result["_models"] = models
    result["_test"] = None
    return result


def fmt(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def main():
    t0 = time.time()
    if LOG.exists():
        LOG.unlink()
    out = RES / "fusion"
    (RES / "confusion").mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    all_rows, results = [], {}
    for name in ("scenarios", "battledim"):
        r = run_dataset(name)
        results[name] = r
        all_rows += r["rows"]

    # ---- selection on the scenarios (the only data with both evidence streams), validation macro-F1 (out-of-fold)
    sc = {r["model"]: r["val"]["macro_f1"] for r in results["scenarios"]["rows"]}
    fa, fb = sc["F-A"], sc["F-B"]
    selected = "F-A" if fa > fb + SELECT_TIE else "F-B"
    reason = (f"validation macro-F1 (out-of-fold, scenarios): F-A {fa:.4f}, F-B {fb:.4f}; "
              f"ties within {SELECT_TIE} go to F-B (fewer parameters, directly inspectable masses)")
    sel_obj = results["scenarios"]["_models"][selected]["obj"]
    joblib.dump({"design": selected, "model": sel_obj}, PROC / "models" / "fusion_selected.joblib")

    # ---- sample assessments from the selected design on scenario test events (output format check)
    full = build_frame("scenarios")
    with final_evaluation(f"sample-assessments-{selected}", "scenarios", LOG):
        test = SplitData(full).test()
    test = test[fusion_mask(test, "scenarios")]
    proba = sel_obj.predict_proba(test)
    cats = sel_obj.predict(test)
    samples = []
    for cat_idx, cat in enumerate(CATS[1:], start=1):
        sub = np.where((cats == cat_idx) & (test.y.to_numpy() == cat_idx))[0]
        for i in sub[:: max(1, len(sub) // 2)][:2]:
            row = test.iloc[i].to_dict()
            samples.append({"node_id": row["node_id"], "ts": str(row["ts"]), "truth": CATS[int(row["y"])],
                            **assess(row, proba[i], cats[i])})
    (out / "sample_assessments.json").write_text(json.dumps(samples, indent=2), encoding="utf-8")

    # ---- write results
    clean = [{k: v for k, v in r.items()} for r in all_rows]
    (out / "fusion_results.json").write_text(json.dumps(
        {"selected": selected, "selection_reason": reason, "rows": clean}, indent=2, default=str), encoding="utf-8")
    (out / "selection.json").write_text(json.dumps({"selected": selected, "reason": reason,
                                                     "val_macro_f1": sc}, indent=2), encoding="utf-8")
    write_tables(all_rows, selected, reason)
    print(f"selected {selected}: {reason}\ndone in {time.time() - t0:.0f}s")


def write_tables(rows, selected, reason):
    lines = ["# Fusion and ablation results (test split, each model evaluated once)", "",
             f"Selected design: **{selected}**. Selection rule: {reason}.", "",
             "Two data kinds, reported separately. `scenarios` = semi-synthetic events on real/simulated background "
             "(4 categories). `battledim` = simulated hydraulics with leak labels, infrastructure evidence only "
             "(categories Normal vs Infrastructure; no quality stream). Fusion designs are fitted on validation only; "
             "validation macro-F1 for F-A/F-B variants is out-of-fold. Event metrics treat any alert as a detection of any event; "
             "`cat. acc.` is the share of events whose modal alert category equals the true category.", ""]
    for name in ("scenarios", "battledim"):
        lines += [f"## {name}", "",
                  "| Model | Val macro-F1 | Test macro-F1 | Test accuracy | Event P | Event R | Event F1 | False alarms/day | Latency med (h) | Cat. acc. | Infra event F1 | Quality event F1 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in [r for r in rows if r["dataset"] == name]:
            t, v = r["test"], r["val"]
            a = t["any_alert"]
            q = t.get("quality_domain")
            mark = " (selected)" if r["model"] == selected else ""
            lines.append(f"| {r['model']}{mark} | {fmt(v['macro_f1'])} | {fmt(t['macro_f1'])} | {fmt(t['accuracy'])} | "
                         f"{fmt(a['event']['precision'])} | {fmt(a['event']['recall'])} | {fmt(a['event']['f1'])} | "
                         f"{fmt(a['false_alarms_per_day'], 2)} | {fmt(a['latency_h']['median'], 2)} | {fmt(t['event_category_accuracy'])} | "
                         f"{fmt(t['infra_domain']['event']['f1'])} | {fmt(q['event']['f1']) if q else 'n/a'} |")
        lines.append("")
    (RES / "tables").mkdir(parents=True, exist_ok=True)
    (RES / "tables" / "fusion_ablation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    cm = ["# Confusion matrices (test split, row = truth, column = prediction)", "",
          "Categories: " + ", ".join(CATS), ""]
    for r in rows:
        safe = r["model"].replace(" ", "_").replace(":", "").replace("(", "").replace(")", "")
        (RES / "confusion").mkdir(parents=True, exist_ok=True)
        (RES / "confusion" / f"{r['dataset']}__{safe}.json").write_text(
            json.dumps({"labels": CATS, "val": r["val"]["confusion"], "test": r["test"]["confusion"]}, indent=2), encoding="utf-8")
        cm += [f"## {r['dataset']} / {r['model']}", "", "| truth \\ pred | " + " | ".join(CATS) + " |",
               "|---|" + "---|" * 4]
        for i, row in enumerate(r["test"]["confusion"]):
            cm.append(f"| {CATS[i]} | " + " | ".join(str(x) for x in row) + " |")
        cm.append("")
    (RES / "tables" / "confusion_matrices.md").write_text("\n".join(cm) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
