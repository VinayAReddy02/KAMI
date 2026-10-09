"""python -m kami.eval.run_baselines  ->  results/baselines/*.json and results/tables/baselines.md

Tuning (threshold multiplier, forest hyperparameters, score quantile) uses the validation split only.
The test split is opened once per model and dataset through `final_evaluation`.
"""
from __future__ import annotations

import json
import time

import numpy as np

from ..models.baselines import FixedThreshold, IsoForest
from .access import SplitData, final_evaluation
from .data import DATASETS, DOMAIN_SIGNALS, RES, domain_features, load_dataset, scored_mask
from .metrics import domain_events, evaluate

K_GRID = [1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]
Q_GRID = [0.9, 0.95, 0.98, 0.99, 0.995, 0.999]
IF_GRID = [(100, 256), (300, 256), (100, 2048)]
LOG = RES / "baselines" / "test_eval_log.json"


def _key(m: dict):
    """Selection key on validation: event F1, then fewer false alarms per day."""
    return (m["event"]["f1"], -m["false_alarms_per_day"])


def _eval(df, pred, domain, mask, events=None):
    return evaluate(df, pred & mask, domain, events=events, scored=mask)


def run_dataset(name: str) -> list[dict]:
    full = load_dataset(name)
    data = SplitData(full)
    domains = DATASETS[name][2]
    rows = []
    # per-domain masks computed once over the full frame (index aligned)
    masks = {d: scored_mask(full, d) for d in DOMAIN_SIGNALS}
    ev_override = None
    if name == "battledim":
        import pandas as pd

        e = pd.read_csv(RES / "splits" / "battledim_events.csv", parse_dates=["start", "end"])
        ev_override = e.assign(node_id="battledim-network").rename(columns={"event_type": "type"})[
            ["node_id", "event_id", "type", "start", "end"]]

    def events_for(df, domain):
        if ev_override is not None:
            lo, hi = df.ts.min(), df.ts.max()
            return ev_override[(ev_override.start >= lo) & (ev_override.end <= hi)]
        return domain_events(df, domain)

    train, val = data.train(), data.val()
    models = []  # (model_id, domains it is scored against, fitted-model factory result)

    # ---- fixed thresholds (one model per domain) ----
    for d in domains:
        sig = DOMAIN_SIGNALS[d]
        tr = train[masks[d].loc[train.index]]
        best = None
        for k in K_GRID:
            m = FixedThreshold(sig, k).fit(tr)
            r = _eval(val, m.predict(val), d, masks[d].loc[val.index].to_numpy(), events_for(val, d))
            if best is None or _key(r) > _key(best[1]):
                best = (m, r, {"k": k})
        models.append((f"fixed_threshold-{d}", [d], best[0], best[2], {d: best[1]}))

    # ---- isolation forest: per domain and joint ----
    configs = [(f"isolation_forest-{d}", d, [d]) for d in domains]
    if len(domains) > 1:
        configs.append(("isolation_forest-joint", "joint", list(domains)))
    for mid, fd, scored_against in configs:
        cols = domain_features(fd, full.columns)
        mask_tr = masks[fd].loc[train.index].to_numpy()
        tr = train[mask_tr]
        if len(tr) > 150_000:
            tr = tr.sample(150_000, random_state=0).sort_index()
        best = None
        for n_est, ms in IF_GRID:
            m = IsoForest(cols, n_est, ms).fit(tr)
            for q in Q_GRID:
                m.set_quantile(q)
                pred = m.predict(val)
                rs = {dd: _eval(val, pred, dd, masks[fd].loc[val.index].to_numpy(), events_for(val, dd))
                      for dd in scored_against}
                agg = {"event": {"f1": float(np.mean([r["event"]["f1"] for r in rs.values()]))},
                       "false_alarms_per_day": float(np.mean([r["false_alarms_per_day"] for r in rs.values()]))}
                if best is None or _key(agg) > _key(best[1]):
                    best = ((n_est, ms, q), agg, rs)
        (n_est, ms, q), _, rs = best
        m = IsoForest(cols, n_est, ms, q).fit(tr)
        models.append((mid, scored_against, m, {"n_estimators": n_est, "max_samples": ms, "quantile": q}, rs))

    # ---- final evaluation: test split opened once per model and dataset ----
    for mid, scored_against, m, params, val_res in models:
        with final_evaluation(mid, name, LOG):
            test = data.test()
        fd = "joint" if mid.endswith("joint") else scored_against[0]
        pred = m.predict(test)
        for dd in scored_against:
            mask = masks[fd].loc[test.index].to_numpy()
            tr_ = _eval(test, pred, dd, mask, events_for(test, dd))
            vr = val_res[dd]
            rows.append({"dataset": name, "domain": dd, "model": mid.split("-")[0] + ("-joint" if mid.endswith("joint") else ""),
                         "params": params, "val": vr, "test": tr_,
                         "data_kind": "battledim_simulated_labels" if name == "battledim" else "semi_synthetic_scenarios"})
    return rows


def fmt(x, nd=3):
    return "n/a" if x is None else f"{x:.{nd}f}"


def write_outputs(rows: list[dict]) -> None:
    out = RES / "baselines"
    out.mkdir(parents=True, exist_ok=True)
    for r in rows:
        p = out / f"{r['dataset']}__{r['domain']}__{r['model']}.json"
        p.write_text(json.dumps(r, indent=2), encoding="utf-8")
    lines = ["# Baseline results (test split, evaluated once per model)", "",
             "Tuned on the validation split only. `battledim`: simulated hydraulics with leak labels; "
             "`scenarios`: semi-synthetic events on real/simulated background. Reported separately. "
             "Latency in hours (n/a = nothing detected).", "",
             "| Dataset | Domain | Model | Point P | Point R | Point F1 | Event P | Event R | Event F1 | False alarms/day | Latency med (h) | Latency p90 (h) | Val event F1 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["dataset"], r["domain"], r["model"])):
        t, v = r["test"], r["val"]
        lines.append(f"| {r['dataset']} | {r['domain']} | {r['model']} | {fmt(t['point']['precision'])} | {fmt(t['point']['recall'])} | "
                     f"{fmt(t['point']['f1'])} | {fmt(t['event']['precision'])} | {fmt(t['event']['recall'])} | {fmt(t['event']['f1'])} | "
                     f"{fmt(t['false_alarms_per_day'], 2)} | {fmt(t['latency_h']['median'], 2)} | {fmt(t['latency_h']['p90'], 2)} | "
                     f"{fmt(v['event']['f1'])} |")
    types = sorted({k for r in rows for k in r["test"]["per_type_recall"]})
    lines += ["", "## Per-event-type recall (test)", "", "| Dataset | Domain | Model | " + " | ".join(types) + " |",
              "|---|---|---|" + "---|" * len(types)]
    for r in sorted(rows, key=lambda r: (r["dataset"], r["domain"], r["model"])):
        pt = r["test"]["per_type_recall"]
        lines.append(f"| {r['dataset']} | {r['domain']} | {r['model']} | " +
                     " | ".join(f"{pt[t]['recall']:.2f} (n={pt[t]['events']})" if t in pt else "-" for t in types) + " |")
    (RES / "tables").mkdir(parents=True, exist_ok=True)
    (RES / "tables" / "baselines.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    t0 = time.time()
    if LOG.exists():
        LOG.unlink()  # this run's own log: regenerated on every full run
    rows = []
    for name in DATASETS:
        rows += run_dataset(name)
        print(f"{name} done at {time.time() - t0:.0f}s", flush=True)
    write_outputs(rows)
    print(f"wrote {len(rows)} result files in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
