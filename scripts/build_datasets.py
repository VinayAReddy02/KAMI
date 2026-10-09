"""Build processed datasets, splits and data-quality logs (deterministic)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kami.data.loaders import build_battledim_network, build_scenario_background  # noqa: E402
from kami.data.splits import check_no_straddle, make_splits, save_splits  # noqa: E402
from kami.simulator.scenarios import frame_hash, generate_scenarios  # noqa: E402

SEED = 42
PER_TYPE = 4
out = ROOT / "data" / "processed"
res = ROOT / "results"
out.mkdir(parents=True, exist_ok=True)
(res / "splits").mkdir(parents=True, exist_ok=True)

bd, ev, bd_log = build_battledim_network()
spans = ev[["event_id", "start", "end"]]
sp_bd = make_splits(bd, spans=spans)
assert check_no_straddle(bd, sp_bd, spans)
bd.to_parquet(out / "battledim_network_semi_synthetic.parquet")
ev.to_csv(res / "splits" / "battledim_events.csv", index=False)
save_splits(sp_bd, res / "splits" / "battledim.json")

bg, bg_log = build_scenario_background()
sp_sc = make_splits(bg)
save_splits(sp_sc, res / "splits" / "scenarios.json")
sc, sc_ev = generate_scenarios(bg, sp_sc, seed=SEED, per_type=PER_TYPE)
assert check_no_straddle(sc, sp_sc)
sc.to_parquet(out / "scenarios_semi_synthetic.parquet")
sc_ev.to_csv(res / "splits" / "scenario_events.csv", index=False)
(res / "data_quality.json").write_text(json.dumps({
    "battledim_network": bd_log, "scenario_background": bg_log, "scenario_seed": SEED,
    "scenario_events_per_type_per_split_per_node": PER_TYPE, "scenario_hash": frame_hash(sc)}, indent=2, default=str),
    encoding="utf-8")
print("battledim rows", len(bd), "events", len(ev), "splits", {k: str(v) for k, v in sp_bd.items()})
print("scenario rows", len(sc), "events", len(sc_ev), "hash", frame_hash(sc))
print(sc_ev.groupby(["split", "type"]).size().unstack())
