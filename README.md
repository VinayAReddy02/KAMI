# KAMI: contextual anomaly intelligence for water networks

KAMI watches four signals (flow, pressure, turbidity, TDS), scores **infrastructure** and **water-quality** behaviour as separate evidence streams, analyses temporal context (suddenness, persistence, recurrence), and fuses them into a category (Normal, Infrastructure, Quality, Combined), a priority, a confidence and a plain-language explanation. A React dashboard shows it live on a map.

There is **no physical hardware**: a virtual sensor node replays public data over MQTT (or an in-process bus). All node data are semi-synthetic, and the map is a fictional layout near Vellore. Read `results/SUMMARY.md` for results and limitations, `docs/architecture.md` for the pipeline diagram.

## Windows quick start (PowerShell)
Requirements: Python 3.12, Node.js (LTS), Git. Docker Desktop is optional (only for the docker mode).

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
Ports 8101-8105, 8190 and 8230 are used by the check scripts, 8231 by one Docker test, 8210 by the browser tests. If a port is busy, pick another and pass it on the command line.

## Modes: fallback or docker
`run_demo.py` runs in **fallback** mode unless you ask for docker (`--mode docker` or `KAMI_MODE=docker`). Code that takes no mode option (for example `scripts/check_step_1.py`) follows `KAMI_MODE`; without it, it uses docker only while the two containers are up. A running Docker Desktop alone changes nothing.

| | Fallback (default) | Docker |
|---|---|---|
| Message bus | in-process | MQTT broker (Mosquitto), port 1883 |
| Storage | SQLite (`data/processed/kami.sqlite`) | TimescaleDB (PostgreSQL 16), port 5432 |
| Processes | one: nodes, ingest worker, processor and API together | three: virtual nodes, ingest worker, API; they talk only through MQTT and TimescaleDB |
| Start | `.\.venv\Scripts\python scripts\run_demo.py --port 8200` | `.\.venv\Scripts\python scripts\run_demo.py --mode docker --port 8200` |
| Stop | Ctrl+C | Ctrl+C stops the three processes; `docker compose down` stops the containers |

Docker mode needs Docker Desktop running. `run_demo.py --mode docker` starts the two containers itself with `docker compose up -d` if they are not up (anonymous, development only), empties the database, then starts the three processes; their logs are in `data/processed/logs/`. The API process never calls the nodes directly: replay speed, pause and injected events go over MQTT control topics (`kami/control/...`) and the replay position comes back on `kami/status/replay`. The dashboard, the alert push and the citizen bot work the same in both modes.

```powershell
docker compose up -d                                   # Mosquitto + TimescaleDB (optional: run_demo starts them if needed)
.\.venv\Scripts\python scripts\run_demo.py --mode docker --port 8200
.\.venv\Scripts\python scripts\run_demo.py --check --mode docker   # smoke test of the three-process demo
.\.venv\Scripts\python scripts\docker_checks.py                    # every Docker check of Round 6 (starts and stops the containers)
docker compose down                                    # stop and remove the containers (the demo data in them is discarded)
```
The Docker path was exercised in Round 6 (Docker 29.8.2, Compose 5.5.1): the MQTT and TimescaleDB tests run and pass, and the browser tests pass against the docker-mode demo as well (`results/docker/part_b.json`). If `docker` is "not found" in a terminal that was open before Docker Desktop was installed, open a new terminal.

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
When a node opens or escalates to a High or Critical alert, KAMI writes a short message in plain words: node, category, priority, confidence (the final fused value), the reason (for example "unusual for 2 h, started suddenly", with the model score in brackets), one generic action line and the time. Example:
```
[KAMI DEMO - simulated data]
Node: Gandhi Nagar Tank (node-2 · Ward 2)
Category: Infrastructure | Priority: High
Confidence: 0.69 (final fused value, not the model score)
Flow/pressure: unusual for 2 h, started suddenly, 1st episode in 7 days (model score 0.99, suddenness 0.91)
Action: Check pressure and flow at Gandhi Nagar Tank.
Replay time: 2018-01-07 18:30
```
 By default this is a **dry run**: the message only goes to `results/notifications/dryrun_log.jsonl` and nothing is sent. To receive it in Telegram, put the bot token in the git-ignored `.env` (`TELEGRAM_BOT_TOKEN`), press Start in the bot, then:
```powershell
.\.venv\Scripts\python scripts\telegram_find_chat.py   # one-time: saves your chat id in .env (prints only your first name)
.\.venv\Scripts\python scripts\send_test_alert.py      # one labelled test message (dry run unless KAMI_TELEGRAM_ENABLE=1)
.\.venv\Scripts\python scripts\run_demo.py             # prints "Alerts: Telegram on" or "Alerts: dry run (<reason>)"
.\.venv\Scripts\python scripts\check_telegram.py       # Round 4 checks; cannot reach Telegram (add --quick to skip the earlier checks)
```
Limits: one message per node per 10 minutes, 30 per hour. Outbound only; `GET /notifications/status` and the dashboard footer show the mode and counts. Setup, message format and failure handling: `docs/notifications.md`. The token and the chat id live only in `.env` and are never logged.

## Citizen interface on the Telegram bot (optional, off by default)
A resident can ask the same bot, typed or as a voice note, in Hindi or English: when the tanker comes to a ward ("When will the water tanker reach Ward 4?" / "वार्ड 4 में टैंकर कब आएगा?"), what the notices say (supply hours, charges, how to report a pipe), or what the sensors show in a ward; and can report a damaged pipe with a photo and a location, which becomes a ticket on the dashboard (Complaints page and a marker on the map). Speech recognition, translation, the language model and the voice all run on the laptop.

**Demo data, fictional.** The wards, the tanker schedule, the notices and the helpline number are invented (`data/citizen/*demo_fictional*`). The software does not look at what a photo shows. No reply names a cause.

```powershell
.\.venv\Scripts\python -m pip install -r requirements-citizen.txt --extra-index-url https://download.pytorch.org/whl/cu126   # speech packages (large)
ollama pull llama3.2:3b                                         # local LLM (optional; without it the bot uses fixed sentences)
.\.venv\Scripts\python scripts\run_demo.py --port 8200                 # dashboard + alerts + citizen bot (if enabled in .env)
.\.venv\Scripts\python scripts\run_citizen_bot.py                      # the bot alone
.\.venv\Scripts\python scripts\check_round6.py --quick                 # Round 6 checks; cannot reach Telegram or Ollama
```
To switch it on set `KAMI_CITIZEN_ENABLE=1` in `.env` (the token and chat id are the ones of the alert push). Only the chat in `TELEGRAM_CHAT_ID` and those in `CITIZEN_ALLOWED_CHAT_IDS` are answered; limits: 10 requests per minute per chat, voice notes up to 60 s, photos up to 10 MB. Commands: `/help`, `/language hi|en|auto`.

How an answer is made: rules read the ward and the day from the question; the time always comes from the schedule data (a ward whose sensor point has an open High or Critical alert gets "possibly delayed"); a local LLM (`llama3.2:3b`) may phrase the answer, and a guard replaces it with a fixed sentence if any time, date, ward, tanker id or number is not in the retrieved records. Models: `faster-whisper:large-v3-turbo`, `nllb-200-distilled-600M`, `piper (hi: priyamvada, en: lessac)`.

Measured on 40 authored test questions (run once): fixed sentences answered 98% correctly; with the local LLM 23 of 36 LLM answers broke a grounding rule and were replaced, 98% correct after the guard; spoken questions (synthetic speech): word error rate 1.4% English and 23.5% Hindi, 82% correct end to end, about 1.2 s from question to voice answer. These are authored questions on a fictional schedule with synthetic speech, not a field test. Details: `docs/citizen.md`, `results/citizen/eval.md`.

## What to expect with no injected event
With no injection, expect about 0.0 alerts per simulated day, 0 of them High or above: in a replay of 14 simulated days on all 8 nodes the demo opened 0 alert episodes (the same measurement with one injected event did raise alerts). So during a presentation the map stays quiet until you inject an event. This describes the replayed demo data (simulated infrastructure, real river quality, inside the training period). It is not a false-alarm rate; details in `results/demo_quiet/quiet_demo.md`, regenerate with `.\.venv\Scripts\python scripts\quiet_demo.py`.

## Browser tests, screenshots and accessibility check
One-time setup: `cd frontend; npm install; npx playwright install chromium; cd ..`
```powershell
cd frontend; npm run build; npx playwright test; cd ..      # 30 browser tests against a demo server that is locked to dry run
.\.venv\Scripts\python scripts\screenshots.py --a11y       # rewrites results/screens/ (16 PNG) and results/a11y/
.\.venv\Scripts\python scripts\check_round5.py             # Round 5 checks (add --quick to skip the earlier checks)
```
- **Browser tests** (`frontend/e2e/`): Overview with 8 markers and the demo label, an injected event appears in the feed, node detail with four charts and the explanation, alert filters, theme toggle. They start `scripts/e2e_server.py` on port 8210 (fallback mode, temporary store); that process cannot reach Telegram.
- **Screenshots for the paper** (`results/screens/`): Overview, Node detail during an injected event, Alerts and Method; dark and light; desktop 1440x900 and phone 390x844. Made by the Playwright spec, listed in `manifest.json`, never edited by hand.
- **Accessibility** (`results/a11y/axe_report.md`): axe-core on every page in both themes; no finding left after three fixes (see `docs/decisions.md`, Round 5). An automated scan covers only part of accessibility.

## Project documents
- `docs/teacher_scope.md`: the faculty feedback item by item: what was asked, what was built, what changed and why, what was not done.
- `docs/demo_script.md`: a 5 to 7 minute live demo with the exact commands and clicks, and a fallback plan if the network fails.
- `docs/real_data_search.md`: a report-only search for public, real, labelled leak or water-quality data (nothing downloaded).

## Repository layout
```
src/kami/    data, features, simulator, models, eval, ingest, store, live, api, notify, citizen
frontend/    React + TypeScript + Vite dashboard; e2e/ = Playwright browser tests
scripts/     check_step_N.py, check_round2.py, build_datasets.py, build_test_set.py, make_summary.py, run_demo.py, reproduce_all.py, check_telegram.py, check_round5.py, send_test_alert.py, telegram_find_chat.py, e2e_server.py, screenshots.py, quiet_demo.py, check_round6.py, run_citizen_bot.py, build_citizen_data.py, citizen_model_select.py, citizen_eval.py, docker_checks.py
tests/       step1 .. step6, round2, live, telegram, citizen, docker
config/      nodes.json (fictional demo coordinates)
docs/        decisions.md, datasets.md, scenarios.md, fusion.md, architecture.md, notifications.md, citizen.md, teacher_scope.md, demo_script.md, real_data_search.md, reference/
results/     metrics, tables, figures, round2/, SUMMARY.md   (results_round1/ = Round 1 snapshot)
PROGRESS.md  PLAN.md  PLAN_ROUND2.md  PLAN_ROUND4.md  PLAN_ROUND5.md  PLAN_ROUND6.md  PLAN_ROUND7.md  PLAN_ROUND7_OLD_DOCKER.md  CLAUDE.md  .env.example   (the Round 3 plan is superseded and kept as history)
```

## Honest scope notes
- Infrastructure data are a hydraulic simulation (BattLeDIM), quality data are real river records (USGS) without event labels, so fusion is tested on semi-synthetic scenarios.
- Round 2 result (fresh test set, frozen method): the selected fusion design does not beat simple threshold voting on event F1 by a detectable margin (0.708 vs 0.667 with overlapping uncertainty), with the same false alarms per day. It is detectably better at naming the right category (Infrastructure, Quality or Combined). See `results/SUMMARY.md` and `docs/decisions.md` (Round 2).
- The event metrics do not penalise how long an alert lasts, detection at the tuned thresholds is slow (median about 3.4 h), and the BattLeDIM scores are uninformative because every tuned rule alerts almost all the time there. The live demo runs the frozen Round 2 rule (since Round 3); with it the demo's injected combined event shows as Infrastructure, not Combined, and a node with a missing quality stream is shown as "Not assessed".
