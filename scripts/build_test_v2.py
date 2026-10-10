"""R1: build the scenarios_v2 dataset. Train and validation rows are identical to Round 1; the TEST period gets
new events from a new seed (same generator, same rules, 12 events per type). Round-1 test events become test_v1 (exposed).

This script only writes files and checks event tables / hashes; it never evaluates a model.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kami.data.loaders import build_scenario_background  # noqa: E402
from kami.data.splits import assign_split, check_no_straddle, load_splits  # noqa: E402
from kami.simulator.scenarios import frame_hash, generate_scenarios  # noqa: E402

SEED_V2 = 20261010
PER_TYPE = 4
res = ROOT / "results"
sp = load_splits(res / "splits" / "scenarios.json")
bg, _ = build_scenario_background()


def build(seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    full_v1 = pd.read_parquet(ROOT / "data" / "processed" / "scenarios_semi_synthetic.parquet")
    alt, ev = generate_scenarios(bg, sp, seed=seed, per_type=PER_TYPE)
    s_v1 = assign_split(full_v1.ts, sp)
    s_alt = assign_split(alt.ts, sp)
    keep = full_v1[(s_v1 != "test").to_numpy()]
    new_test = alt[(s_alt == "test").to_numpy()]
    out = pd.concat([keep, new_test], ignore_index=True)
    ev = ev[ev.split == "test"].reset_index(drop=True)
    return out, ev


v2, ev2 = build(SEED_V2)
v2b, _ = build(SEED_V2)
v2.to_parquet(ROOT / "data" / "processed" / "scenarios_v2_semi_synthetic.parquet")
ev2.to_csv(res / "splits" / "scenario_events_v2_test.csv", index=False)

ev1 = pd.read_csv(res / "splits" / "scenario_events.csv", parse_dates=["start", "end"])
ev1 = ev1[ev1.split == "test"]
ev2c = pd.read_csv(res / "splits" / "scenario_events_v2_test.csv", parse_dates=["start", "end"])
key = lambda e: set(zip(e.node_id, e.type, e.start))  # noqa: E731
full_v1 = pd.read_parquet(ROOT / "data" / "processed" / "scenarios_semi_synthetic.parquet")
tv, tv1 = assign_split(v2.ts, sp), assign_split(full_v1.ts, sp)
info = {
    "seed_v2": SEED_V2, "hash_v2": frame_hash(v2), "hash_v2_repeat": frame_hash(v2b),
    "same_seed_identical": frame_hash(v2) == frame_hash(v2b),
    "events_per_type": ev2c.groupby("type").size().to_dict(),
    "no_straddle": bool(check_no_straddle(v2, sp)),
    "v1_v2_test_events_overlap": len(key(ev1) & key(ev2c)),
    "train_val_identical_to_v1": bool(
        frame_hash(v2[(tv != "test").to_numpy()].reset_index(drop=True)) == frame_hash(full_v1[(tv1 != "test").to_numpy()].reset_index(drop=True))),
    "test_events_differ_from_v1": bool(
        (v2[(tv == "test").to_numpy()].reset_index(drop=True).event_id.eq(full_v1[(tv1 == "test").to_numpy()].reset_index(drop=True).event_id)).mean() < 1.0),
}
(res / "splits").mkdir(exist_ok=True)
(res / "splits" / "test_v2_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
print(json.dumps(info, indent=2))
