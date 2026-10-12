"""Quiet-demo measurement: how often does the live demo raise alerts on its own, with no injected event?

    python scripts/quiet_demo.py            # 14 simulated days, all 8 nodes -> results/demo_quiet/quiet_demo.json and .md

This describes the behaviour of the DEMO on its replayed data (simulated hydraulics from BattLeDIM, real river records
from USGS). It is NOT an evaluation metric and NOT a false-alarm rate: the replayed period has no event labels here,
it lies inside the period the evidence models were trained on, and the BattLeDIM year contains simulated leaks.

The run uses the same in-process pipeline as the fallback demo (virtual nodes -> bus -> ingest worker -> store ->
streaming processor -> alert push in forced dry run), without the web server and as fast as it can be processed.
Nothing is injected in the quiet window. A short positive control with ONE injected event runs first, to show that the
counting does see alerts. The process cannot reach Telegram (kami.notify.lock). It refuses to run if any replayed row
would come from a held-out period.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "results" / "demo_quiet"
STEPS_PER_DAY = 288
PRIORITIES = ["Low", "Medium", "High", "Critical"]
CATEGORIES = ["Infrastructure", "Quality", "Combined"]
CONTROL_STEPS, CONTROL_NODE = STEPS_PER_DAY, "node-2"  # positive control: one simulated day with one injected event
SPEEDS = {"demo default (x600)": 600.0, "real time (x1)": 1.0}  # the cooldown and the hourly cap use wall-clock time


def source_ranges(frames: dict, start: int, steps: int) -> dict:
    """Where each node's replayed rows come from in the raw two-year series (see simulator.node.build_node_frames)."""
    idx = next(iter(frames.values()))["ts"]
    n = len(idx)
    out = {}
    for i, nid in enumerate(frames):
        shift, q_shift = (i // 3) * 12 * STEPS_PER_DAY, (i * 4000) % n
        rng = {}
        for name, s in (("flow_pressure", shift), ("turbidity_tds", q_shift)):
            a, b = (start + s) % n, (start + s + steps - 1) % n
            rng[name] = {"from": str(idx.iloc[a]), "to": str(idx.iloc[b]), "wraps": b < a}
        out[nid] = rng
    return out


def run_window(frames: dict, start: int, steps: int, inject: tuple | None = None) -> dict:
    """Replay `steps` steps of all nodes from `start` through the in-process pipeline and record every alert event."""
    from kami.live.system import build_live
    from kami.runtime import Stack
    from kami.store import SqliteStore

    store = SqliteStore(Path(tempfile.mkdtemp(prefix="kami_quiet_")) / "kami.sqlite")
    store.init()
    stack = Stack.create(mode="fallback", store=store)
    live = build_live(stack, speed=0, start=start, max_steps=steps)  # alert push: forced dry run (the default); speed 0 = no waiting
    mgr = stack.extras["notifications"]
    assert mgr.status()["mode"] == "dry_run"
    if inject:
        live.injector.inject(*inject)
    events: list[dict] = []
    per_node = {nid: Counter() for nid in frames}

    def record(kind: str, data: dict) -> None:
        if kind == "alert":
            events.append(dict(data))
            return
        c = per_node[data["node_id"]]
        c["steps"] += 1
        for k in ("p_infra", "p_quality"):
            c[f"max_{k}"] = max(c[f"max_{k}"], data[k])
            c[f"steps_{k}_high"] += data[k] >= 0.5
        if data["category"] != "Normal":
            c["steps_in_alert"] += 1
        elif data["status"] == "warming_up":
            c["steps_warming_up"] += 1
        elif data["explanation"].startswith("Not assessed"):
            c["steps_not_assessed"] += 1

    live.processor.listeners.append(record)
    t_wall = time.time()
    live.fleet.start()
    live.fleet.join()
    wall = time.time() - t_wall
    mgr.wait_idle(30)
    push = mgr.status()
    mgr.stop()
    assert live.fleet.published == steps * len(frames) == sum(c["steps"] for c in per_node.values()), "readings were lost"
    return {"live": live, "events": events, "per_node": per_node, "push": push, "wall": wall,
            "episodes": live.processor.list_alerts(limit=100000)[::-1]}  # final state of every alert episode, oldest first


def replay_rule(events: list[dict], t0, speed: float) -> dict:
    """The current trigger rule (same code as the live system) applied to the recorded alert events, with the wall
    clock that a replay at `speed` would have. Says how many Telegram messages that run would have sent."""
    import pandas as pd

    from kami.notify.rules import TriggerRule

    rule, sent, held = TriggerRule(), 0, Counter()
    for e in events:
        now = (pd.Timestamp(e["end_ts"] or e["last_ts"]) - t0).total_seconds() / speed
        d = rule.evaluate(e, now)
        if d.send:
            rule.commit(e, now)
            sent += 1
        elif d.suppressed:
            held[d.reason] += 1
    return {"messages": sent, "held_back": dict(held)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()
    from kami.notify.lock import lock_to_dry_run, refused

    notify_dir = lock_to_dry_run()
    import pandas as pd

    from kami.live.system import load_nodes_config
    from kami.simulator.node import build_node_frames, find_clean_start

    steps = args.days * STEPS_PER_DAY
    frames = build_node_frames(8)
    start = find_clean_start(frames)  # the fixed start every demo run uses
    splits = json.loads((ROOT / "results" / "splits" / "battledim.json").read_text(encoding="utf-8"))
    sources = source_ranges(frames, start, steps)
    latest = max(pd.Timestamp(r[k]["to"]) for r in sources.values() for k in r)
    if any(r[k]["wraps"] for r in sources.values() for k in r) or latest >= pd.Timestamp(splits["train_end"]):
        print(f"NOT RUN: the window would replay rows up to {latest}, outside the training period (ends {splits['train_end']}).")
        return 2

    control = run_window(frames, start, CONTROL_STEPS, inject=("infra_burst", CONTROL_NODE, start + 24))
    control_eps = [e for e in control["episodes"] if e["node_id"] == CONTROL_NODE]
    if not control_eps:
        print("NOT VALID: the positive control (one injected event) produced no alert, so a count of zero would mean nothing.")
        return 3
    q = run_window(frames, start, steps)
    live, events, per_node, push, wall = q["live"], q["events"], q["per_node"], q["push"], q["wall"]
    names = {n["id"]: n["name"] for n in load_nodes_config()["nodes"]}
    assert live.injector.status() == [] and not refused

    t0 = pd.Timestamp(frames["node-1"]["ts"].iloc[start])
    opened = {}
    for e in events:
        opened.setdefault(e["id"], e)  # the first event of an episode is its opening
    rank = PRIORITIES.index
    rows = []
    for ep in q["episodes"]:
        o = opened[ep["id"]]
        end = pd.Timestamp(ep["end_ts"] or ep["last_ts"])
        rows.append({"id": ep["id"], "node_id": ep["node_id"], "day": int((pd.Timestamp(ep["start_ts"]) - t0).total_seconds() // 86400) + 1,
                     "start_ts": ep["start_ts"], "end_ts": ep["end_ts"], "still_open_at_end": ep["status"] == "active",
                     "hours": round((end - pd.Timestamp(ep["start_ts"])).total_seconds() / 3600, 2),
                     "category_at_open": o["category"], "priority_at_open": o["priority"],
                     "category_last": ep["category"], "highest_priority": ep["max_priority"]})
    high = [r for r in rows if rank(r["highest_priority"]) >= rank("High")]
    total_steps = steps * len(frames)
    result = {
        "what": "Quiet-demo measurement: alerts the live demo raises on its own, with no injected event. Behaviour of the demo on "
                "replayed data, NOT an evaluation metric and NOT a false-alarm rate.",
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "made_by": "scripts/quiet_demo.py",
        "setup": {"simulated_days": args.days, "nodes": len(frames), "steps_per_node": steps, "step_minutes": 5, "start_step": start,
                  "replay_from": str(t0), "replay_to": str(frames["node-1"]["ts"].iloc[start + steps - 1]), "injections": 0,
                  "method": live.processor.fusion.describe()["label"], "alert_push": "forced dry run", "wall_seconds": round(wall, 1),
                  "pipeline": "in-process fallback demo (bus, ingest worker, SQLite store, streaming processor) without the web server, "
                              "processed without waiting"},
        "data": {"infrastructure": "BattLeDIM hydraulic simulation (semi_synthetic); the year contains simulated leaks, which are not marked here",
                 "quality": "USGS river turbidity and conductance (real, no event labels)",
                 "period": f"every replayed row lies before {splits['train_end']}, inside the period the evidence models were trained on; "
                           "no held-out test set is read",
                 "latest_source_row": str(latest), "source_rows_per_node": sources},
        "alerts": {
            "episodes_opened": len(rows),
            "per_simulated_day_mean": round(len(rows) / args.days, 2),
            "high_or_critical_episodes": len(high),
            "high_or_critical_per_simulated_day_mean": round(len(high) / args.days, 2),
            "by_category_at_open": {c: sum(r["category_at_open"] == c for r in rows) for c in CATEGORIES},
            "by_highest_priority": {p: sum(r["highest_priority"] == p for r in rows) for p in PRIORITIES},
            "per_day": {str(d): sum(r["day"] == d for r in rows) for d in range(1, args.days + 1)},
            "per_day_high_or_critical": {str(d): sum(r["day"] == d for r in high) for d in range(1, args.days + 1)},
            "median_hours": round(float(pd.Series([r["hours"] for r in rows]).median()), 2) if rows else None,
            "still_open_at_end": sum(r["still_open_at_end"] for r in rows),
            "share_of_node_steps_in_alert": round(sum(c["steps_in_alert"] for c in per_node.values()) / total_steps, 4),
            "share_of_node_steps_not_assessed": round(sum(c["steps_not_assessed"] for c in per_node.values()) / total_steps, 4),
        },
        "per_node": {nid: {"name": names[nid], "episodes_opened": sum(r["node_id"] == nid for r in rows),
                           "high_or_critical": sum(r["node_id"] == nid for r in high),
                           "share_of_steps_in_alert": round(per_node[nid]["steps_in_alert"] / steps, 4),
                           "share_of_steps_not_assessed": round(per_node[nid]["steps_not_assessed"] / steps, 4),
                           "highest_infrastructure_model_score": round(float(per_node[nid]["max_p_infra"]), 3),
                           "highest_quality_model_score": round(float(per_node[nid]["max_p_quality"]), 3),
                           "steps_infrastructure_score_0.5_or_more": int(per_node[nid]["steps_p_infra_high"]),
                           "steps_quality_score_0.5_or_more": int(per_node[nid]["steps_p_quality_high"])} for nid in frames},
        "positive_control": {
            "what": f"the same code on {CONTROL_STEPS // STEPS_PER_DAY} simulated day with ONE injected infra_burst at {CONTROL_NODE}, "
                    "to show that this measurement does count alerts; its numbers are not part of the quiet result",
            "episodes_at_injected_node": len(control_eps), "episodes_at_other_nodes": len(control["episodes"]) - len(control_eps),
            "category": control_eps[0]["category"], "highest_priority": control_eps[0]["max_priority"],
            "dry_run_messages": control["push"]["sent"]},
        "telegram_messages_under_the_current_rule": {
            "rule": "episode opens at High or Critical, or escalates to a higher priority at High or Critical; one message per node per "
                    "10 minutes and 30 per hour, both in wall-clock time, so the number depends on the replay speed",
            "triggers_before_limits": replay_rule(events, t0, 1e-9)["messages"],  # an extremely slow replay: no limit ever applies
            **{name: replay_rule(events, t0, s) for name, s in SPEEDS.items()},
            "this_run_dry_run_log": {"messages": push["sent"], "held_back": push["suppressed_by"],
                                     "note": f"the whole window was processed in {wall:.0f} s of wall-clock time"},
        },
        "episodes": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "quiet_demo.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    (OUT / "quiet_demo.md").write_text(to_markdown(result), encoding="utf-8", newline="\n")
    a = result["alerts"]
    print(f"{a['episodes_opened']} alert episodes in {args.days} simulated days ({a['per_simulated_day_mean']} per day), "
          f"{a['high_or_critical_episodes']} reached High or Critical; processed in {wall:.0f} s; positive control: "
          f"{len(control_eps)} episode(s) at {CONTROL_NODE}; dry-run folder {notify_dir}")
    return 0


def to_markdown(r: dict) -> str:
    s, a, t, c = r["setup"], r["alerts"], r["telegram_messages_under_the_current_rule"], r["positive_control"]
    lines = [
        "# Quiet demo: alerts with no injected event",
        "",
        f"Generated by `scripts/quiet_demo.py` on {r['run_utc']} (commit `{r['git_commit']}`). Numbers come from `quiet_demo.json`.",
        "",
        "**What this is.** The live demo replayed for "
        f"{s['simulated_days']} simulated days on all {s['nodes']} nodes ({s['replay_from']} to {s['replay_to']}), with nothing injected, "
        f"running the rule \"{s['method']}\". It tells you what to expect on screen during a presentation.",
        "",
        "**What this is not.** It is not an evaluation metric and not a false-alarm rate. The data are replayed demo data: simulated "
        "infrastructure signals (BattLeDIM, which contains simulated leaks that are not marked here) and real river quality records (USGS, no "
        "event labels). The replayed period lies inside the period the models were trained on. The evaluation results are in `results/SUMMARY.md`.",
        "",
        "| | Count |",
        "|---|---|",
        f"| Alert episodes opened | {a['episodes_opened']} |",
        f"| Per simulated day (mean) | {a['per_simulated_day_mean']} |",
        f"| Episodes that reached High or Critical | {a['high_or_critical_episodes']} |",
        f"| High or Critical per simulated day (mean) | {a['high_or_critical_per_simulated_day_mean']} |",
        f"| Median length of an episode | {'n/a' if a['median_hours'] is None else str(a['median_hours']) + ' h'} |",
        f"| Still open at the end of the window | {a['still_open_at_end']} |",
        f"| Share of node-steps in alert | {a['share_of_node_steps_in_alert']:.1%} |",
        f"| Share of node-steps not assessed (a signal missing) | {a['share_of_node_steps_not_assessed']:.1%} |",
        "",
        "| Category when the episode opened | " + " | ".join(a["by_category_at_open"]) + " |",
        "|---|" + "---|" * len(a["by_category_at_open"]),
        "| Episodes | " + " | ".join(str(v) for v in a["by_category_at_open"].values()) + " |",
        "",
        "| Highest priority reached | " + " | ".join(a["by_highest_priority"]) + " |",
        "|---|" + "---|" * len(a["by_highest_priority"]),
        "| Episodes | " + " | ".join(str(v) for v in a["by_highest_priority"].values()) + " |",
        "",
        "| Node | Episodes | High or Critical | Steps in alert | Steps not assessed | Highest infrastructure score | Highest quality score |",
        "|---|---|---|---|---|---|---|",
        *[f"| {v['name']} ({k}) | {v['episodes_opened']} | {v['high_or_critical']} | {v['share_of_steps_in_alert']:.1%} | {v['share_of_steps_not_assessed']:.1%} "
          f"| {v['highest_infrastructure_model_score']:.2f} ({v['steps_infrastructure_score_0.5_or_more']} steps at 0.5 or more) "
          f"| {v['highest_quality_model_score']:.2f} ({v['steps_quality_score_0.5_or_more']} steps at 0.5 or more) |"
          for k, v in r["per_node"].items()],
        "",
        f"Each node has {s['steps_per_node']} steps. The model scores show how close the quiet replay came to an alert: the frozen rule needs a "
        "score that stays high for some time (discounted infrastructure evidence of at least 0.98, quality at least 0.8), not a single high value.",
        "",
        "| Simulated day | " + " | ".join(a["per_day"]) + " |",
        "|---|" + "---|" * len(a["per_day"]),
        "| Episodes opened | " + " | ".join(str(v) for v in a["per_day"].values()) + " |",
        "| of them High or Critical | " + " | ".join(str(v) for v in a["per_day_high_or_critical"].values()) + " |",
        "",
        "## Positive control",
        "",
        f"{c['what'][0].upper() + c['what'][1:]}. Result: {c['episodes_at_injected_node']} episode(s) at the injected node "
        f"({c['category']}, highest priority {c['highest_priority']}), {c['episodes_at_other_nodes']} at other nodes, "
        f"{c['dry_run_messages']} message(s) in the dry-run log.",
        "",
        "## Telegram messages these alerts would cause",
        "",
        f"Rule: {t['rule']}.",
        "",
        "| Replay speed | Messages | Held back |",
        "|---|---|---|",
        f"| no limits (every trigger) | {t['triggers_before_limits']} | |",
        *[f"| {name} | {t[name]['messages']} | {', '.join(f'{k} {v}' for k, v in t[name]['held_back'].items()) or 'none'} |" for name in SPEEDS],
        "",
        f"In the quiet run itself the dry-run log received {t['this_run_dry_run_log']['messages']} message(s) "
        f"({t['this_run_dry_run_log']['note']}). No real message was sent.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
