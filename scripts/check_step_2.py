"""Exit 0 only if Step 2 criteria hold. Reads the built artefacts and re-checks them."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kami.data.loaders import build_scenario_background  # noqa: E402
from kami.data.splits import assign_split, check_no_straddle, load_splits  # noqa: E402
from kami.features.causal import compute_features  # noqa: E402
from kami.simulator.scenarios import EVENT_TYPES, frame_hash, generate_scenarios  # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok &= bool(cond)


res = ROOT / "results"
proc = ROOT / "data" / "processed"
dq = json.loads((res / "data_quality.json").read_text(encoding="utf-8"))
bd = pd.read_parquet(proc / "battledim_network_semi_synthetic.parquet")
sc = pd.read_parquet(proc / "scenarios_semi_synthetic.parquet")
sp_bd = load_splits(res / "splits" / "battledim.json")
sp_sc = load_splits(res / "splits" / "scenarios.json")
ev_bd = pd.read_csv(res / "splits" / "battledim_events.csv", parse_dates=["start", "end"])
ev_sc = pd.read_csv(res / "splits" / "scenario_events.csv", parse_dates=["start", "end"])

# 1. no look-ahead: perturb the future of a real node series and compare features
n = sc[sc.node_id == "scn-node-1"].sort_values("ts").iloc[:20000].reset_index(drop=True)
base = compute_features(n)
for cut in (5000, 12000):
    p = n.copy()
    p.loc[cut + 1:, ["flow", "pressure", "turbidity", "tds"]] *= -3.0
    g = compute_features(p)
    same = np.allclose(base.iloc[: cut + 1].to_numpy(), g.iloc[: cut + 1].to_numpy(), equal_nan=True, rtol=0, atol=0)
    check(f"features unchanged when future perturbed (cut {cut})", same)

# 2. splits chronological, disjoint, no event across a boundary
for name, df, sp, spans in (("battledim", bd, sp_bd, ev_bd[["event_id", "start", "end"]]), ("scenarios", sc, sp_sc, None)):
    s = assign_split(df.ts, sp)
    check(f"{name}: splits ordered", sp["start"] < sp["train_end"] < sp["val_end"] < sp["end"])
    check(f"{name}: split ranges disjoint and chronological",
          df.ts[s == "train"].max() < df.ts[s == "val"].min() and df.ts[s == "val"].max() < df.ts[s == "test"].min())
    check(f"{name}: no event crosses a boundary", check_no_straddle(df, sp, spans))

# 3. same seed -> identical output (two fresh runs + the stored hash)
bg, _ = build_scenario_background()
a, _ = generate_scenarios(bg, sp_sc, seed=dq["scenario_seed"], per_type=dq["scenario_events_per_type_per_split_per_node"])
b, _ = generate_scenarios(bg, sp_sc, seed=dq["scenario_seed"], per_type=dq["scenario_events_per_type_per_split_per_node"])
check("scenario output identical across two runs", frame_hash(a) == frame_hash(b))
check("scenario hash equals the stored hash", frame_hash(a) == frame_hash(sc) == dq["scenario_hash"])

# 4. >= 5 events of every type in each split
counts = ev_sc.groupby(["split", "type"]).size().unstack(fill_value=0)
print(counts.to_string())
check("at least 5 events of every scenario type in train, val and test",
      all(counts.reindex(columns=EVENT_TYPES, fill_value=0).loc[s].min() >= 5 for s in ("train", "val", "test")))
check("all scenario rows labelled semi_synthetic", bool(sc.semi_synthetic.all()) and bool(bd.semi_synthetic.all()))

r = subprocess.run([sys.executable, "-m", "pytest", "tests/step2", "-q"], cwd=ROOT)
check("pytest tests/step2", r.returncode == 0)
sys.exit(0 if ok else 1)
