# KAMI: contextual anomaly intelligence for water networks

KAMI watches four signals (flow, pressure, turbidity, TDS), scores **infrastructure** and **water-quality** behaviour as separate evidence streams, analyses temporal context (suddenness, persistence, recurrence), and fuses them into a category (Normal, Infrastructure, Quality, Combined), a priority, a confidence and a plain-language explanation. A React dashboard shows it live on a map.

There is **no physical hardware**: a virtual sensor node replays public data over MQTT (or an in-process bus). All node data are semi-synthetic, and the map is a fictional layout near Vellore. Read `results/SUMMARY.md` for results and limitations, `docs/architecture.md` for the pipeline diagram.

## Windows quick start (PowerShell)
Requirements: Python 3.12, Node.js (LTS), Git. Docker is optional.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -e .
cd frontend; npm install; npm run build; cd ..
.\.venv\Scripts\python scripts\run_demo.py
```
Open http://127.0.0.1:8000 . Use the replay controls (speed, pause) and "Inject event" to create a leak, burst, turbidity surge, TDS shift or combined event on any node. `python scripts/run_demo.py --check` runs a 10-second smoke test.

For frontend development run `npm run dev` in `frontend/` (port 5173, proxies to the API on 8000).

## Ports
| Service | Default | Override |
|---|---|---|
| API and built dashboard | 8000 | `--port`, `KAMI_API_PORT` |
| Frontend dev server | 5173 | `vite.config.ts` |
| MQTT | 1883 | `KAMI_MQTT_PORT` |
| Postgres/TimescaleDB | 5432 | `KAMI_PG_PORT` |
Port 8101-8103 and 8190 are used by the check scripts. If a port is busy, pick another and pass it on the command line.

## Modes: Docker or fallback
- `KAMI_MODE=docker` (automatic when `docker info` works): `docker compose up -d` starts Mosquitto and TimescaleDB (anonymous, dev only). The MQTT and TimescaleDB backends are implemented and have tests that run only when the services are reachable; **they were not exercised in the build environment (no Docker)**.
- `KAMI_MODE=fallback` (automatic otherwise): in-process bus and SQLite (`data/processed/kami.sqlite`). The nodes, ingest worker, processor and API then run in one process, which is what `scripts/run_demo.py` does.

## Reproduce every result
Data download notes are in `data/raw/*/SOURCE.md` (BattLeDIM from Zenodo, USGS NWIS via the public web service). Then:

```powershell
.\.venv\Scripts\python scripts\build_datasets.py          # processed data, splits, labelled scenarios (seed 42)
.\.venv\Scripts\python -m kami.eval.run_baselines         # results/baselines, results/tables/baselines.md
.\.venv\Scripts\python -m kami.eval.run_evidence          # results/evidence, reliability figures
.\.venv\Scripts\python -m kami.eval.run_fusion            # fusion, ablations, confusion matrices, selection
.\.venv\Scripts\python scripts\make_summary.py            # results/SUMMARY.md
```
or `python scripts/reproduce_all.py` for all of the above. `scripts/check_step_N.py` (N = 0..7) verifies each step against the real artefacts; `pytest -q` runs all unit tests; `npm run test` and `npm run build` cover the frontend.

Seeds are fixed. Re-running reproduces the numbers (the scenario hash is stored in `results/data_quality.json`).

### Round 2: frozen method, fresh test sets
Round 1 results are kept in `results_round1/` (git tag `round1`). Round 2 re-tunes the decision rules on validation only (event F1, each detected event counted once, with at most 0.5 false alarms per day), freezes the configuration, and evaluates it once on fresh scenario test sets with bootstrap confidence intervals. See `PLAN_ROUND2.md`, `docs/decisions.md` (Round 2) and `results/SUMMARY.md`.

```powershell
.\.venv\Scripts\python scripts\build_test_set.py --version v2 --seed 20261010   # held-out test events (secondary set)
.\.venv\Scripts\python scripts\build_test_set.py --version v3 --seed 20261011   # held-out test events (headline set)
.\.venv\Scripts\python -m kami.eval.run_round2_select        # validation-only tuning and selection
.\.venv\Scripts\python -m kami.eval.run_temporal_ablation    # with/without temporal features, 5 seeds, validation
.\.venv\Scripts\python -c "from kami.eval.freeze import build; build()"   # results/fusion/frozen_config.json
.\.venv\Scripts\python -m kami.eval.run_final --dry-run      # whole pipeline on validation rows; reads no held-out file
.\.venv\Scripts\python -m kami.eval.run_final --rehearse     # real code path on the two exposed test sets, throw-away logs
.\.venv\Scripts\python -m kami.eval.run_final                # one-time final evaluation (logged)
.\.venv\Scripts\python scripts\make_summary.py
.\.venv\Scripts\python scripts\check_round2.py              # add --quick to skip the Round 1 checks
```
Test-set roles: `test_v3` is the headline set (frozen first, each model evaluated once; its file was loaded once by a dry run before the freeze, with no model or metric using its test rows). `test_v2` is secondary: the baselines were scored on it once before the freeze by mistake (`results/round2/incident_test_v2/`). `test_v1` (Round 1) and the BattLeDIM test split are exposed and shown for reference only.

The final evaluation is deliberately not repeatable: each model's access to a held-out test set is logged in `results/round2/*_eval_log.json`, the runner refuses to start if any frozen file changed, and a second run reuses the stored predictions in `results/round2/predictions/` and opens nothing again (every number can be recomputed from them). The validation-side commands above are reproducible.

## Alert push through a Telegram bot (optional, dry run by default)
When a node opens or escalates to a High or Critical alert, KAMI writes a short message (`[KAMI DEMO - simulated data]`, node, category, priority, confidence, explanation, time). By default this is a **dry run**: the message only goes to `results/notifications/dryrun_log.jsonl` and nothing is sent. To receive it in Telegram, put the bot token in the git-ignored `.env` (`TELEGRAM_BOT_TOKEN`), press Start in the bot, then:
```powershell
.\.venv\Scripts\python scripts\telegram_find_chat.py   # one-time: saves your chat id in .env (prints only your first name)
.\.venv\Scripts\python scripts\send_test_alert.py      # one labelled test message (dry run unless KAMI_TELEGRAM_ENABLE=1)
.\.venv\Scripts\python scripts\run_demo.py             # prints "Alerts: Telegram on" or "Alerts: dry run (<reason>)"
.\.venv\Scripts\python scripts\check_telegram.py       # Round 4 checks; cannot reach Telegram (add --quick to skip the earlier checks)
```
Limits: one message per node per 10 minutes, 30 per hour. Outbound only; `GET /notifications/status` and the dashboard footer show the mode and counts. Setup, message format and failure handling: `docs/notifications.md`. The token and the chat id live only in `.env` and are never logged.

## Repository layout
```
src/kami/    data, features, simulator, models, eval, ingest, store, live, api, notify
frontend/    React + TypeScript + Vite dashboard
scripts/     check_step_N.py, check_round2.py, build_datasets.py, build_test_set.py, make_summary.py, run_demo.py, reproduce_all.py, check_telegram.py, send_test_alert.py, telegram_find_chat.py
tests/       step1 .. step6, round2, live, telegram
config/      nodes.json (fictional demo coordinates)
docs/        decisions.md, datasets.md, scenarios.md, fusion.md, architecture.md, notifications.md, reference/
results/     metrics, tables, figures, round2/, SUMMARY.md   (results_round1/ = Round 1 snapshot)
PROGRESS.md  PLAN.md  PLAN_ROUND2.md  PLAN_ROUND4.md  PLAN_ROUND5.md  CLAUDE.md  .env.example   (the Round 3 plan is superseded and kept as history)
```

## Honest scope notes
- Infrastructure data are a hydraulic simulation (BattLeDIM), quality data are real river records (USGS) without event labels, so fusion is tested on semi-synthetic scenarios.
- Round 2 result (fresh test set, frozen method): the selected fusion design does not beat simple threshold voting on event F1 by a detectable margin (0.708 vs 0.667 with overlapping uncertainty), with the same false alarms per day. It is detectably better at naming the right category (Infrastructure, Quality or Combined). See `results/SUMMARY.md` and `docs/decisions.md` (Round 2).
- The event metrics do not penalise how long an alert lasts, detection at the tuned thresholds is slow (median about 3.4 h), and the BattLeDIM scores are uninformative because every tuned rule alerts almost all the time there. The live demo runs the frozen Round 2 rule (since Round 3); with it the demo's injected combined event shows as Infrastructure, not Combined, and a node with a missing quality stream is shown as "Not assessed".
