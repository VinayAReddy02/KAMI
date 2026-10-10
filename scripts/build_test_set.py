"""Round 2: build a held-out scenario test set (scenarios_v2 or scenarios_v3).

    python scripts/build_test_set.py --version v2 --seed 20261010
    python scripts/build_test_set.py --version v3 --seed 20261011

Train and validation rows are identical to Round 1; only the TEST period gets new events from the given seed (same
generator, same rules, 12 events per type). The Round-1 test events are test_v1 (exposed).

This script only writes files and compares event tables / hashes. It never evaluates a model and never prints or
stores a metric computed on the test rows.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kami.data.loaders import build_scenario_background  # noqa: E402
from kami.data.splits import assign_split, check_no_straddle, load_splits  # noqa: E402
from kami.simulator.scenarios import frame_hash, generate_scenarios  # noqa: E402

PER_TYPE = 4
SEEDS = {"v2": 20261010, "v3": 20261011}  # v2: named by the user; v3: next integer (see docs/decisions.md, incident)

ap = argparse.ArgumentParser()
ap.add_argument("--version", required=True, choices=sorted(SEEDS))
ap.add_argument("--seed", type=int, required=True)
a = ap.parse_args()
if a.seed != SEEDS[a.version]:
    sys.exit(f"{a.version} must use the recorded seed {SEEDS[a.version]} (test sets are not re-rolled)")

res = ROOT / "results"
proc = ROOT / "data" / "processed"
sp = load_splits(res / "splits" / "scenarios.json")
bg, _ = build_scenario_background()
full_v1 = pd.read_parquet(proc / "scenarios_semi_synthetic.parquet")
s_v1 = assign_split(full_v1.ts, sp)


def build(seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    alt, ev = generate_scenarios(bg, sp, seed=seed, per_type=PER_TYPE)
    s_alt = assign_split(alt.ts, sp)
    keep = full_v1[(s_v1 != "test").to_numpy()]
    new_test = alt[(s_alt == "test").to_numpy()]
    out = pd.concat([keep, new_test], ignore_index=True)
    return out, ev[ev.split == "test"].reset_index(drop=True)


def key(e: pd.DataFrame) -> set:
    """(node, type, start): two seeds share one such triple by chance in roughly 1 of 100 pairs."""
    return set(zip(e.node_id, e.type, pd.to_datetime(e.start)))


def full_key(e: pd.DataFrame) -> set:
    """Whole event: node, type, start, end and every drawn parameter."""
    return set(zip(e.node_id, e.type, pd.to_datetime(e.start), pd.to_datetime(e.end), e.params))


new, ev_new = build(a.seed)
again, _ = build(a.seed)
h = frame_hash(new)
out_parquet = proc / f"scenarios_{a.version}_semi_synthetic.parquet"
info_path = res / "splits" / f"test_{a.version}_info.json"
if out_parquet.exists() and info_path.exists():
    old = json.loads(info_path.read_text(encoding="utf-8"))
    if old.get(f"hash_{a.version}") not in (None, h):
        sys.exit(f"refusing to overwrite {out_parquet.name}: the regenerated hash differs from the recorded one")
new.to_parquet(out_parquet)
ev_path = res / "splits" / f"scenario_events_{a.version}_test.csv"
ev_new.to_csv(ev_path, index=False)

ev_new = pd.read_csv(ev_path, parse_dates=["start", "end"])
ev1 = pd.read_csv(res / "splits" / "scenario_events.csv", parse_dates=["start", "end"])
ev1 = ev1[ev1.split == "test"]
tv = assign_split(new.ts, sp)
info = {
    f"seed_{a.version}": a.seed, f"hash_{a.version}": h,
    "same_seed_identical": h == frame_hash(again),
    "events_per_type": ev_new.groupby("type").size().to_dict(),
    "no_straddle": bool(check_no_straddle(new, sp)),
    "v1_same_node_type_start": len(key(ev1) & key(ev_new)),
    "v1_identical_events": len(full_key(ev1) & full_key(ev_new)),
    "train_val_identical_to_v1": bool(
        frame_hash(new[(tv != "test").to_numpy()].reset_index(drop=True))
        == frame_hash(full_v1[(s_v1 != "test").to_numpy()].reset_index(drop=True))),
    "test_events_differ_from_v1": len(full_key(ev1) & full_key(ev_new)) == 0 and len(ev_new) == len(ev1),
}
for other in sorted(SEEDS):
    p = res / "splits" / f"scenario_events_{other}_test.csv"
    if other != a.version and p.exists():
        eo = pd.read_csv(p, parse_dates=["start", "end"])
        info[f"{other}_same_node_type_start"] = len(key(eo) & key(ev_new))
        info[f"{other}_identical_events"] = len(full_key(eo) & full_key(ev_new))
info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
print(json.dumps(info, indent=2))
