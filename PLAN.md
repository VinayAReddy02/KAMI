# KAMI build plan

Work the steps **in order**. Each step has tasks and an **exit check**: a script `scripts/check_step_N.py` that you write as the first task of that step. It must exit 0 only when every criterion below holds, printing PASS or FAIL per criterion. It must read real artefacts, never hardcoded values. When it passes: update `PROGRESS.md`, commit (`step N: <summary>`), move on.

Dependencies: 0 -> 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7. If a step is blocked (see CLAUDE.md, three failed attempts), continue with the next step that does not depend on it; otherwise stop cleanly.

---

## Step 0: Dataset recon

**Goal:** choose and obtain public data. Nothing later is built on an unchecked dataset.

**Tasks**
1. Check each candidate: reachable URL, licence, variables, sampling interval, event labels, size.
   - Infrastructure (flow and/or pressure with labelled leaks or abnormal events): BattLeDIM (Zenodo), LeakDB, BATADAL, and the Babela et al. multisource dataset (Scientific Data, 2026; confirm it exists).
   - Water quality (turbidity and conductance as TDS proxy): USGS National Water Information System continuous records via the public web service (check current parameter codes; likely turbidity 63680 and specific conductance 00095, **verify**). Pick 3 to 5 stations with long, gap-light records.
2. Select **at least one infrastructure** and **at least one quality** dataset. Download into `data/raw/<name>/` with a `SOURCE.md` (URL, date, licence, citation, variables, units).
3. Write `docs/datasets.md`: a table of every candidate with status (selected, rejected, unreachable) and reasons.
4. **Fallbacks (only if no real dataset is obtainable):** infrastructure via a WNTR/EPANET simulation of a small network with leak scenarios; quality via a documented synthetic generator. Mark them `synthetic` everywhere and add "revisit original dataset" to *Needs user* in `PROGRESS.md`.

**Exit check (`check_step_0.py`)**
- `docs/datasets.md` lists at least one selected infrastructure and one selected quality dataset.
- Every selected dataset has its files on disk, a `SOURCE.md`, a readable timestamp column, and more than 10,000 rows.
- The script loads each selected dataset into a DataFrame and prints variables, time range and label counts.

---

## Step 1: Foundations

**Goal:** the plumbing: repo, environment, transport, storage, API skeleton, virtual sensor node.

**Tasks**
1. `git init`, `.gitignore` (data/raw, data/processed, .venv, node_modules, .env, caches), `pyproject.toml` (package `kami`, editable install), `requirements.txt`, `.venv`, `README.md` skeleton, log tool versions in `docs/decisions.md`.
2. Storage interface with two backends (TimescaleDB, SQLite). Message bus interface with two backends (MQTT, in-process). Choose the backend by checking `docker info`; allow an override with an environment variable.
3. `docker-compose.yml` for Mosquitto and TimescaleDB (anonymous local access, dev only).
4. FastAPI skeleton: `GET /health`, `GET /nodes`, `GET /readings?node=&since=`, `WS /ws`.
5. **Virtual sensor node**: `python -m kami.simulator.node --dataset <name> --nodes 8 --speed 600` replays data as JSON `{node_id, ts, flow, pressure, turbidity, tds}` on topic `kami/nodes/<id>/readings`. Eight nodes draw from the selected datasets (document how real series are assigned to nodes; mark any mixing of datasets as `semi_synthetic`).
6. Ingest worker: subscribe, validate, write to storage.

**Exit check (`check_step_1.py`)**
- Starts the stack (Docker or fallback), runs the node for 20 seconds at high speed.
- Storage contains readings from all 8 nodes (at least 100 rows each).
- `GET /readings` returns them; `GET /health` returns OK.
- `pytest tests/step1` passes (bus and storage interface tests for both backends that are available).

---

## Step 2: Data pipeline, features, scenarios

**Goal:** clean data, causal features, leak-free splits, and a labelled scenario generator for fusion testing.

**Tasks**
1. Loaders to a common schema: `ts, node_id, flow, pressure, turbidity, tds` plus label columns (`event_id, event_type, infra_flag, quality_flag, source, semi_synthetic`). Handle missing, duplicate and invalid values; log counts.
2. Causal features per signal (past-only windows): rolling mean and std, rate of change, slope, deviation from rolling baseline. Window sizes configurable and recorded.
3. Chronological split into train, validation and test **per dataset**, with no event straddling a boundary. Save split definitions.
4. **Scenario generator** (`kami.simulator.scenarios`): injects events into real background series. Types: `infra_leak` (gradual pressure decline with rising flow), `infra_burst` (sudden version), `quality_turbidity_surge`, `quality_tds_shift`, `combined`. Parameters drawn from a seeded distribution. Emits per-timestep labels. Document every rule and its physical rationale in `docs/scenarios.md`. Everything it produces is `semi_synthetic`.

**Exit check (`check_step_2.py`)**
- Property test: perturbing future data does not change any feature at time t (no look-ahead).
- Splits are chronological, disjoint, and no event crosses a boundary.
- Same seed gives byte-identical scenario output (hash compared across two runs).
- At least 5 events of every scenario type in each of train, validation and test.
- `pytest tests/step2` passes.

---

## Step 3: Baselines and evaluation harness

**Goal:** reproducible comparison numbers before any proposed method exists.

**Tasks**
1. **Fixed thresholds:** independent per-sensor thresholds from training statistics; the multiplier is chosen on validation.
2. **Isolation Forest:** per domain and joint; hyperparameters chosen on validation.
3. **Harness** (`kami.eval`): point-level and event-level precision, recall and F1; false alarms per day; detection latency (median, p90); per-event-type recall; separate reports for real-event data and semi-synthetic scenarios.
4. One command: `python -m kami.eval.run_baselines` writes `results/baselines/*.json` and `results/tables/baselines.md`.
5. Unit-test the harness on toy cases with known answers (perfect detector gives F1 = 1; never alerting gives recall 0; a late alert has the right latency).

**Exit check (`check_step_3.py`)**
- The command finishes in under 15 minutes and writes both outputs.
- All metrics are in [0, 1] (latency aside) and no value is NaN.
- Test-split data is accessed only by the final-evaluation function (asserted in a test).
- `pytest tests/step3` passes.

---

## Step 4: Evidence modules and temporal analysis

**Goal:** calibrated per-domain evidence and causal temporal features.

**Tasks**
1. **Infrastructure evidence** from flow, pressure and their features, outputting a **calibrated probability** `p_infra`. **Quality evidence** from turbidity, TDS and features, outputting `p_quality`. Choose model types on validation, document why, and avoid relying on test data. Calibrate (isotonic or Platt) on validation. Report Brier score and a reliability curve.
2. **Temporal features** per evidence stream, computed causally: *suddenness* (normalised maximum rate of change), *persistence* (duration and consecutive windows above threshold), *recurrence* (number of separate episodes in a trailing window).
3. Compare each evidence module with its baselines on its own domain.

**Exit check (`check_step_4.py`)**
- `results/evidence/*.json` exist with calibration metrics.
- On the validation split, each module's event-level F1 is at least that of the best baseline for its domain, **or** `docs/decisions.md` contains a written explanation with numbers.
- Temporal features have unit tests with hand-computed expected values.
- `pytest tests/step4` passes.

---

## Step 5: Fusion and ablations (the main contribution)

**Goal:** the staged contextual fusion and evidence that each part helps.

**Tasks**
1. Implement **at least two fusion designs**, for example:
   - **F-A:** calibrated log-odds combination of `p_infra` and `p_quality` with temporal features as modifiers.
   - **F-B:** evidence-theory (Dempster-Shafer) combination with reliability discounting driven by temporal context.
   You may add others.
2. Outputs: `category` in {Normal, Infrastructure, Quality, Combined}; `priority` in {Low, Medium, High, Critical} with a documented, testable escalation rule (persistence and intensity raise priority); `confidence` in [0,1]; `explanation` (template text naming the contributing evidence and temporal flags with their actual values).
3. **Selection:** choose the design with the best validation macro-F1 over categories; ties go to the more interpretable design. Log the numbers in `docs/decisions.md`. Evaluate each design on the test split **once**. Report both designs.
4. **Ablations:** fusion without temporal features; a single joint model without separated evidence; simple threshold voting; each baseline. Evaluate on real-event data and semi-synthetic scenarios separately.
5. Write `results/tables/fusion_ablation.md`, confusion matrices, and a short `docs/fusion.md` explaining the designs.

**Exit check (`check_step_5.py`)**
- The ablation table has at least 5 rows and exists for both data kinds.
- Confusion matrices are saved; the selection is logged with validation numbers.
- Test evaluation ran exactly once per design (the log records a hash or counter).
- Unit test: explanation strings are non-empty and quote the real evidence values.
- `pytest tests/step5` passes.
- **Honesty note:** if fusion does not beat the baselines or ablations, do not hide it. Record it plainly in `docs/decisions.md` and `results/SUMMARY.md`.

---

## Step 6: Live pipeline and dashboard

**Goal:** a working live system: replayed data to alerts on a map.

**Tasks**
1. **Streaming processor:** consumes readings, computes causal features (must match the batch implementation; test equivalence), evidence, temporal features and fusion, and stores a node **assessment** per update. Add `GET /nodes/{id}/state`, `GET /alerts`, WebSocket pushes, and `POST /demo/inject {type, node}` which injects a scenario into the replay.
2. **Frontend** (`frontend/`, React + TypeScript + Vite, react-leaflet, dark operations-console with a light toggle):
   - **Overview:** map of 8 demo nodes near **Vellore, Tamil Nadu**, using fictional coordinates in a config file, with a visible "Demo network, fictional layout" label; a status strip (counts per category); a live alert feed.
   - **Node detail:** time-series charts for the 4 signals with anomaly shading, evidence bars for `p_infra` and `p_quality`, category, priority, confidence, and the explanation text.
   - **Alerts:** filterable table (category, priority, node, time).
   - **Replay controls:** speed, pause, and "inject event" buttons for each scenario type (for demos).
   - **About / Method:** short pipeline explanation.
   - Live updates over WebSocket with reconnect; loading, empty and error states; status shown with colour, icon and text.
3. Vitest tests for the status badge and the alert list.

**Exit check (`check_step_6.py`)**
- `npm run build` and `npm run test` pass.
- The script starts the stack, worker and nodes, injects a `combined` event on one node, and within 60 seconds of wall time the API reports that node as `Combined` with priority at least Medium **and** a WebSocket client receives the update.
- Streaming and batch features agree on a fixed sample (test).
- If Playwright with Chromium is available, save screenshots of Overview and Node detail to `results/screens/`; otherwise skip and log it.

---

## Step 7: Hardening and documentation (no paper)

**Tasks**
1. `scripts/run_demo.py` starts everything with one command and `--check` runs a smoke test.
2. `README.md`: Windows quick start, ports, fallback mode, how to reproduce every result.
3. `docs/architecture.md` with a Mermaid diagram of the final pipeline.
4. `results/SUMMARY.md`: every table, both data kinds, plus a plain list of limitations (no real field data, semi-synthetic fusion testing, low-cost-sensor caveats, rule-based priority).
5. Fresh-environment check: create a new venv, install from `requirements.txt`, run `pytest -q`.

**Exit check (`check_step_7.py`)**
- `python scripts/run_demo.py --check` passes.
- `pytest -q` passes with no skipped-by-accident tests; `npm run build` passes.
- `results/SUMMARY.md` exists and every table in it is generated by a script in the repo.

**Then stop.** The paper is written with the user afterwards.
