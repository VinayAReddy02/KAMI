"""python -m kami.eval.run_evidence -> results/evidence/*.json, figures, data/processed/evidence_*.parquet"""
from __future__ import annotations

import json
import time

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import average_precision_score, brier_score_loss  # noqa: E402

from ..features.temporal import DEFAULT, temporal_features  # noqa: E402
from ..models.evidence import EvidenceModule, reliability  # noqa: E402
from .access import SplitData, final_evaluation  # noqa: E402
from .data import PROC, RES, domain_features, load_dataset, scored_mask  # noqa: E402
from .metrics import domain_events, evaluate  # noqa: E402

LOG = RES / "evidence" / "test_eval_log.json"
TAU_GRID = np.round(np.arange(0.05, 0.96, 0.05), 2)
COMBOS = [("battledim", "infra"), ("scenarios", "infra"), ("scenarios", "quality")]


def events_for(name: str, df: pd.DataFrame, domain: str):
    if name != "battledim":
        return domain_events(df, domain)
    e = pd.read_csv(RES / "splits" / "battledim_events.csv", parse_dates=["start", "end"])
    e = e.assign(node_id="battledim-network").rename(columns={"event_type": "type"})
    e = e[["node_id", "event_id", "type", "start", "end"]]
    return e[(e.start >= df.ts.min()) & (e.end <= df.ts.max())]


def best_baseline_val(name: str, domain: str) -> dict:
    best = {"model": None, "val_event_f1": 0.0}
    for f in (RES / "baselines").glob(f"{name}__{domain}__*.json"):
        r = json.loads(f.read_text(encoding="utf-8"))
        v = r["val"]["event"]["f1"]
        if v > best["val_event_f1"] or best["model"] is None:
            best = {"model": r["model"], "val_event_f1": v}
    return best


def split_metrics(df, p, y, tau, mask, name, domain):
    pred = (p >= tau) & mask
    m = evaluate(df, pred, domain, events=events_for(name, df, domain), scored=mask)
    pm = p[mask]
    ym = y[mask]
    m["brier"] = float(brier_score_loss(ym, pm))
    m["average_precision"] = float(average_precision_score(ym, pm)) if ym.any() else None
    return m


def run_combo(name: str, domain: str, full: pd.DataFrame, data: SplitData, mask_all: pd.Series, store: dict) -> dict:
    label = f"{domain}_flag"
    cols = domain_features(domain, full.columns)
    train, val = data.train(), data.val()
    tr = train[mask_all.loc[train.index]]
    va = val[mask_all.loc[val.index]]
    mod = EvidenceModule(cols, label).fit(tr, va)

    p_val_s = pd.Series(np.nan, index=val.index)
    p_val_s.loc[va.index] = mod.crossfit_val_proba(va)
    p_val = p_val_s.to_numpy()
    mval = mask_all.loc[val.index].to_numpy()
    yv = val[label].to_numpy(bool)
    best = None
    for tau in TAU_GRID:
        pv = np.nan_to_num(p_val, nan=0.0)
        r = split_metrics(val, pv, yv, tau, mval, name, domain)
        key = (r["event"]["f1"], -r["false_alarms_per_day"])
        if best is None or key > best[0]:
            best = (key, float(tau), r)
    tau, val_res = best[1], best[2]
    base = best_baseline_val(name, domain)

    with final_evaluation(f"evidence-{domain}", name, LOG):
        test = data.test()
    mt = mask_all.loc[test.index].to_numpy()
    p_test = np.zeros(len(test))
    p_test[mt] = mod.predict_proba(test[mt])
    test_res = split_metrics(test, p_test, test[label].to_numpy(bool), tau, mt, name, domain)

    rel_val = reliability(yv[mval], p_val[mval])
    rel_test = reliability(test[label].to_numpy(bool)[mt], p_test[mt])
    fig, ax = plt.subplots(figsize=(4.2, 4))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    ax.plot([r["mean_pred"] for r in rel_val], [r["frac_pos"] for r in rel_val], "o-", label="validation (cross-fitted)")
    ax.plot([r["mean_pred"] for r in rel_test], [r["frac_pos"] for r in rel_test], "s-", label="test")
    ax.set_xlabel("predicted probability")
    ax.set_ylabel("observed frequency")
    ax.set_title(f"{name} p_{domain} reliability")
    ax.legend(fontsize=7)
    fig.tight_layout()
    (RES / "figures").mkdir(parents=True, exist_ok=True)
    fig.savefig(RES / "figures" / f"reliability_{name}_{domain}.png", dpi=130)
    plt.close(fig)

    (PROC / "models").mkdir(parents=True, exist_ok=True)
    joblib.dump({"module": mod, "tau": tau, "columns": cols}, PROC / "models" / f"evidence_{name}_{domain}.joblib")

    p_all = pd.Series(np.nan, index=full.index)
    p_all.loc[val.index] = p_val
    pt = pd.Series(np.nan, index=test.index)
    pt[mt] = p_test[mt]
    p_all.loc[test.index] = pt
    store.setdefault("p", {})[f"p_{domain}"] = p_all

    out = {
        "dataset": name, "domain": domain, "data_kind": "battledim_simulated_labels" if name == "battledim" else "semi_synthetic_scenarios",
        "model_selected": mod.model_name, "validation_average_precision_by_candidate": mod.selection,
        "calibration": "isotonic fitted on validation; validation numbers are cross-fitted over 4 time blocks",
        "tau": tau, "n_features": len(cols), "val": val_res, "test": test_res,
        "reliability_val": rel_val, "reliability_test": rel_test, "best_baseline_val": base,
        "val_event_f1_ge_best_baseline": bool(val_res["event"]["f1"] >= base["val_event_f1"] - 1e-12),
    }
    p = RES / "evidence"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{name}__{domain}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"{name}/{domain}: {mod.model_name} tau={tau} val event F1={val_res['event']['f1']:.3f} "
          f"(best baseline {base['model']} {base['val_event_f1']:.3f}) Brier val={val_res['brier']:.4f} test={test_res['brier']:.4f}", flush=True)
    return out


def main():
    t0 = time.time()
    if LOG.exists():
        LOG.unlink()
    for name in ("battledim", "scenarios"):
        full = load_dataset(name)
        data = SplitData(full)
        store: dict = {}
        for ds, domain in COMBOS:
            if ds != name:
                continue
            run_combo(name, domain, full, data, scored_mask(full, domain), store)
        ev = full[["ts", "node_id", "split"]].copy()
        for col, s in store["p"].items():
            ev[col] = s
        parts = []
        for node, g in ev.groupby("node_id", sort=False):
            g = g.sort_values("ts")
            for col in store["p"]:
                t = temporal_features(g[col].to_numpy(), DEFAULT, prefix=col.replace("p_", "") + "_")
                t.index = g.index
                g = pd.concat([g, t], axis=1)
            parts.append(g)
        pd.concat(parts).sort_index().to_parquet(PROC / f"evidence_{name}.parquet")
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
