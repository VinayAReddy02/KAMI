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

## Repository layout
```
src/kami/    data, features, simulator, models, eval, ingest, store, live, api
frontend/    React + TypeScript + Vite dashboard
scripts/     check_step_N.py, build_datasets.py, make_summary.py, run_demo.py, reproduce_all.py
tests/       step1 .. step6
config/      nodes.json (fictional demo coordinates)
docs/        decisions.md, datasets.md, scenarios.md, fusion.md, architecture.md, reference/
results/     metrics, tables, figures, SUMMARY.md
PROGRESS.md  PLAN.md  CLAUDE.md
```

## Honest scope notes
- Infrastructure data are a hydraulic simulation (BattLeDIM), quality data are real river records (USGS) without event labels, so fusion is tested on semi-synthetic scenarios.
- The selected fusion design gives better point-level category scores than simple threshold voting but more false alarms. See `docs/decisions.md` (Step 5) and `results/SUMMARY.md`.
