"""GECCO real-data test of the quality stream (Round 7, G3/G4). Protocol: docs/gecco_protocol.md.

    python -m kami.gecco.evaluate val-a            # variant A on validation (sanity only; nothing is tuned)
    python -m kami.gecco.evaluate tune             # variant B and the baselines: fit on train, tune on validation, freeze
    python -m kami.gecco.evaluate test --model A   # ONE guarded read of the test labels for that model (A, B,
                                                   # fixed_threshold, isolation_forest, ocsvm); refused a second time

Every test read goes through kami.eval.access.final_evaluation with results/gecco/test_access_log.json; the predictions
of the test rows are written together with their labels to results/gecco/predictions/<model>.csv at once, and every
reported number is computed from those files (kami.gecco.report), never by reading the test file again.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from .. import config
from ..eval.access import final_evaluation, is_logged, mark_completed
from ..eval.fast_eval import AnyEvaluator
from ..eval.fusion_tune import G9, FusionBDesign
from ..eval.hashing import sha256_file
from ..eval.metrics import domain_events, evaluate
from ..features.temporal import DEFAULT, temporal_features
from ..live.frozen import FrozenRule
from ..models.baselines import FixedThreshold, IsoForest, OCSVMDetector
from ..models.evidence import EvidenceModule
from . import data as G

ROOT = config.ROOT
OUT = ROOT / "results" / "gecco"
PRED = OUT / "predictions"
PROC = ROOT / "data" / "processed" / "gecco"
LOG = OUT / "test_access_log.json"
FROZEN = OUT / "frozen_gecco.json"
QMOD = ROOT / "data" / "processed" / "models" / "evidence_scenarios_quality.joblib"
B_MODULE = PROC / "evidence_gecco_quality.joblib"
MODELS = ("A", "B", "fixed_threshold", "isolation_forest", "ocsvm")
CAP = 0.5  # false alarms per day (Round 2)
# Round 2 grids (kami.eval.run_baselines and the F-B grid of kami.eval.fusion_tune)
K_GRID = [1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]
Q_GRID = [0.9, 0.95, 0.98, 0.99, 0.995, 0.999]
IF_GRID = [(100, 256), (300, 256), (100, 2048)]
OC_GRID = [(0.01, 0.1), (0.01, 1.0), (0.05, 0.1), (0.05, 1.0)]
B_GRID = [(rm, tp, lam, gq) for rm in (0.4, 0.7) for tp in (6, 24) for lam in (0.0, 0.3) for gq in G9]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def columns() -> list[str]:
    return list(joblib.load(QMOD)["columns"])


def scored_mask(df: pd.DataFrame, cols: list[str]) -> np.ndarray:
    return np.isfinite(df[cols].to_numpy(float)).all(axis=1)


def with_temporal(seq: pd.DataFrame, p: np.ndarray) -> pd.DataFrame:
    """A copy of a time-ordered sequence with p_quality, its temporal features, and an empty infrastructure stream."""
    out = seq.copy()
    out["p_quality"] = p
    t = temporal_features(np.asarray(p, float), DEFAULT, prefix="quality_")
    t.index = out.index
    out = pd.concat([out, t], axis=1)
    out["p_infra"] = np.where(np.isnan(p), np.nan, 0.0)  # GECCO has no infrastructure stream
    for c in ("persist_steps", "suddenness", "persist_frac", "recurrence"):
        out[f"infra_{c}"] = 0.0
    return out


def labelled(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["quality_flag"] = out["quality_flag"].astype(bool)
    return out


def score(df: pd.DataFrame, pred: np.ndarray, sc: np.ndarray) -> dict:
    """Round 2 metrics of one prediction on one labelled split (quality domain)."""
    df = labelled(df)
    pred = np.asarray(pred, bool) & sc
    full = evaluate(df, pred, "quality", scored=sc)
    fast = AnyEvaluator(df, domain_events(df, "quality"), sc, flag_col="quality_flag")(pred)
    full["objective"] = {k: fast[k] for k in ("f1_event_counted", "fa_per_day", "alert_fraction")}
    return full


def key(m: dict) -> tuple:
    """Round 2 objective: event-counted F1 with <= CAP false alarms per day, else the fewest false alarms."""
    o = m["objective"]
    if o["fa_per_day"] <= CAP:
        return (1, o["f1_event_counted"], -o["fa_per_day"])
    return (0, -o["fa_per_day"], o["f1_event_counted"])


# ---------------------------------------------------------------- variant A: the frozen rule, nothing fitted
def proba_a(seq: pd.DataFrame, cols: list[str]) -> np.ndarray:
    m = joblib.load(QMOD)["module"]
    sc = scored_mask(seq, cols)
    p = np.full(len(seq), np.nan)
    if sc.any():
        p[sc] = m.predict_proba_array(seq.loc[sc, cols].to_numpy(float))
    return p


def alert_a(seq: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """The frozen F-B rule's category on this data (p_infra = 0): an alert when it says Quality (or Combined)."""
    cat = FrozenRule().predict(with_temporal(seq, proba_a(seq, cols)))
    return np.isin(cat, (2, 3))


# ---------------------------------------------------------------- variant B: refitted on GECCO
def alert_b(seq: pd.DataFrame, p: np.ndarray, params) -> np.ndarray:
    rm, tp, lam, gq = params
    cat = FusionBDesign(True).decide(with_temporal(seq, p), (rm, tp, lam, 1.0, gq))  # gamma_infra 1.0: no infrastructure stream
    return np.isin(cat, (2, 3))


def proba_b(module: EvidenceModule, seq: pd.DataFrame, cols: list[str]) -> np.ndarray:
    sc = scored_mask(seq, cols)
    p = np.full(len(seq), np.nan)
    if sc.any():
        p[sc] = module.predict_proba(seq[sc])
    return p


# ---------------------------------------------------------------- baselines
def baseline_models(train: pd.DataFrame, cols: list[str]):
    """(model id, params, fitted detector) for every grid point, fitted on GECCO train."""
    normal = train[~train.quality_flag.astype(bool)]
    for k in K_GRID:
        yield "fixed_threshold", {"k": k}, FixedThreshold(G.SIGNALS, k).fit(train)
    for n_est, ms in IF_GRID:
        m = IsoForest(cols, n_est, ms).fit(train)
        for q in Q_GRID:
            m.set_quantile(q)
            yield "isolation_forest", {"n_estimators": n_est, "max_samples": ms, "quantile": q}, m
    for nu, gm in OC_GRID:
        m = OCSVMDetector(cols, nu, gm).fit(normal)
        for q in Q_GRID:
            m.set_quantile(q)
            yield "ocsvm", {"nu": nu, "gamma_mult": gm, "quantile": q, "fit_rows": min(len(normal), m.max_fit)}, m


def build_baseline(model_id: str, params: dict, train: pd.DataFrame, cols: list[str]):
    if model_id == "fixed_threshold":
        return FixedThreshold(G.SIGNALS, params["k"]).fit(train)
    if model_id == "isolation_forest":
        return IsoForest(cols, params["n_estimators"], params["max_samples"], params["quantile"]).fit(train)
    normal = train[~train.quality_flag.astype(bool)]
    return OCSVMDetector(cols, params["nu"], params["gamma_mult"], params["quantile"]).fit(normal)


# ---------------------------------------------------------------- frame pieces
def frame() -> tuple[pd.DataFrame, list[str]]:
    cols = columns()
    return G.build_frame(), cols


def train_rows(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    tr = df[(df.split == "train").to_numpy() & scored_mask(df, cols)]
    return labelled(tr)


def compact(m: dict) -> dict:
    keep = {"point": m["point"], "event": m["event"], "false_alarms_per_day": m["false_alarms_per_day"], "latency_h": m["latency_h"],
            "scored_normal_days": m["scored_normal_days"]}
    return json.loads(json.dumps(keep, default=float))


def write_json(path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=float) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- commands
def cmd_val_a() -> dict:
    df, cols = frame()
    val = df[df.split == "val"]
    pred = alert_a(val, cols)
    m = score(val, pred, scored_mask(val, cols))
    rule = FrozenRule().describe()
    out = {"made_by": "src/kami/gecco/evaluate.py val-a", "run_utc": now(), "data_kind": G.DATA_KIND, "variant": "A",
           "note": "sanity run on validation; nothing was fitted or tuned", "frozen_rule": rule, "validation": compact(m)}
    write_json(OUT / "val_variant_a.json", out)
    return out


def cmd_tune() -> dict:
    if any(is_logged(m, G.DATASET, LOG) for m in ("B", "fixed_threshold", "isolation_forest", "ocsvm")):
        raise SystemExit("refusing to re-tune: a tuned model has already been read on the test part")
    df, cols = frame()
    tr = train_rows(df, cols)
    val = df[df.split == "val"]
    sc_v = scored_mask(val, cols)
    val_sc = labelled(val[sc_v])
    # variant B: model family chosen by validation average precision, cross-fitted calibration for tuning
    module = EvidenceModule(cols, "quality_flag").fit(tr, val_sc)
    p_cv = np.full(len(val), np.nan)
    p_cv[sc_v] = module.crossfit_val_proba(val_sc)
    best = None
    for params in B_GRID:
        m = score(val, alert_b(val, p_cv, params), sc_v)
        k = key(m) + (params[3], params[0])  # exact ties: higher gamma_q, then higher r_min (protocol section 6)
        if best is None or k > best[0]:
            best = (k, params, m)
    _, b_params, b_val = best
    PROC.mkdir(parents=True, exist_ok=True)
    joblib.dump({"module": module, "columns": cols, "params": b_params}, B_MODULE)
    # baselines: same objective, ties keep the first grid point
    base = {}
    for mid, params, det in baseline_models(tr, cols):
        m = score(val, det.predict(val), sc_v)
        if mid not in base or key(m) > key(base[mid]["val"]):
            base[mid] = {"params": params, "val": m}
    best_base = max(base, key=lambda mid: key(base[mid]["val"]))
    code = [ROOT / "src" / "kami" / "gecco" / f for f in ("__init__.py", "data.py", "evaluate.py")]  # the code that makes predictions
    frozen = {
        "made_by": "src/kami/gecco/evaluate.py tune", "created_utc": now(), "data_kind": G.DATA_KIND,
        "protocol": "docs/gecco_protocol.md",
        "B": {"model": module.model_name, "selection_average_precision_val": module.selection,
              "params": dict(zip(("r_min", "tau_p", "lambda", "gamma_q"), b_params)), "validation": compact(b_val),
              "grid_size": len(B_GRID)},
        "baselines": {mid: {"params": v["params"], "validation": compact(v["val"])} for mid, v in base.items()},
        "best_baseline": best_base,
        "sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): sha256_file(p) for p in
                   [B_MODULE, QMOD, ROOT / "results" / "fusion" / "frozen_config.json", *code,
                    *(G.RAW / f for f in G.FILES.values())]},
    }
    write_json(FROZEN, frozen)
    return frozen


def verify_frozen() -> dict:
    fz = json.loads(FROZEN.read_text(encoding="utf-8"))
    bad = [p for p, h in fz["sha256"].items() if not (ROOT / p).is_file() or sha256_file(ROOT / p) != h]
    if bad:
        raise SystemExit(f"frozen_gecco.json does not match the files on disk: {bad}")
    return fz


def cmd_test(model: str) -> dict:
    if model not in MODELS:
        raise SystemExit(f"model must be one of {MODELS}")
    fz = verify_frozen() if model != "A" else None
    df, cols = frame()
    if model == "A":
        joblib.load(QMOD)  # nothing to freeze: the module and the rule are the Round 2 files
    PRED.mkdir(parents=True, exist_ok=True)
    with final_evaluation(model, G.DATASET, log_path=LOG):
        full = G.attach_test_labels(df)
        seq = full[full.split.isin(["val", "test"])]  # temporal history starts at the first validation step
        if model == "A":
            pred = alert_a(seq, cols)
        elif model == "B":
            b = joblib.load(B_MODULE)
            pred = alert_b(seq, proba_b(b["module"], seq, cols), tuple(b["params"]))
        else:
            det = build_baseline(model, fz["baselines"][model]["params"], train_rows(full, cols), cols)
            pred = det.predict(seq)
        test = (seq.split == "test").to_numpy()
        rows = seq[test]
        out = pd.DataFrame({"ts": rows.ts.dt.strftime("%Y-%m-%dT%H:%M:%S"), "quality_flag": rows.quality_flag.astype(bool).to_numpy(),
                            "event_id": rows.event_id.to_numpy(), "scored": scored_mask(rows, cols), "pred": np.asarray(pred, bool)[test]})
        out.to_csv(PRED / f"{model}.csv", index=False, encoding="utf-8")
        mins = PRED / "test_minutes.csv"
        if not mins.is_file():  # the 1-minute labels, for GECCO's own point-wise score (context only)
            m = G.read_minutes("test", labels=True)
            pd.DataFrame({"ts": m.ts.dt.strftime("%Y-%m-%dT%H:%M:%S"), "event": m.event}).to_csv(mins, index=False, encoding="utf-8")
    mark_completed(model, G.DATASET, LOG, predictions=f"results/gecco/predictions/{model}.csv")
    return {"model": model, "rows": int(test.sum()), "alerts": int(out.pred.sum())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["val-a", "tune", "test"])
    ap.add_argument("--model", choices=MODELS)
    a = ap.parse_args()
    if a.command == "val-a":
        r = cmd_val_a()
        v = r["validation"]
        print(f"A on validation (sanity): event recall {v['event']['recall']:.3f}, event-counted F1 {v['event']['f1_event_counted']:.3f}, "
              f"false alarms/day {v['false_alarms_per_day']:.3f}, events {v['event']['events']}")
    elif a.command == "tune":
        fz = cmd_tune()
        print(f"B frozen: {fz['B']['model']} {fz['B']['params']}; best baseline on validation: {fz['best_baseline']}; wrote {FROZEN.name}")
    else:
        if not a.model:
            raise SystemExit("--model is required for test")
        print(cmd_test(a.model))


if __name__ == "__main__":
    main()
