# KAMI: standing rules for Claude Code

## What this project is
KAMI is a context-aware, multi-stage **anomaly intelligence system for water networks**. It watches four signals (flow, pressure, turbidity, TDS), scores infrastructure behaviour and water-quality behaviour as **separate evidence streams**, analyses **temporal context** (suddenness, persistence, recurrence), and **fuses** them into a category (Normal, Infrastructure, Quality, Combined), a priority, a confidence and a plain-language explanation. A React dashboard shows it live on a map.

- Existing detectors (fixed thresholds, Isolation Forest, One-Class SVM) are **baselines only**. They are not the contribution. The contribution is the staged contextual methodology and its fusion design, shown by ablations.
- This is a solo college project. There is **no physical hardware**: a *virtual sensor node* replays public data over MQTT, exactly as an ESP32 would.

## Read this first, every session
1. `PROGRESS.md` (where we stopped, what needs the user)
2. `PLAN.md` (the steps and their exit checks)
3. `docs/decisions.md` (decisions already made; do not re-open them)
4. `docs/reference/` as needed: `project/` (abstract, first-phase report), `faculty/Faculty_feedback.txt`, `related_works/related_works.md`, `senior_project/AI_water_prj.docx`, `paper_format/` (used later, not now)

## Hard rules
1. **Stay in scope.** Only build what `PLAN.md` lists. No chatbot, RAG, voice, computer vision, routing, forecasting or WhatsApp. If you think something is missing, write it in `docs/decisions.md` under "Proposed"; do not build it.
2. **Never fake results.** No invented numbers, no hardcoded metrics, no tests that pass trivially. Every number in `results/` must come from running code on data. If something fails, say so in `PROGRESS.md`.
3. **Label synthetic data honestly.** Anything produced by the scenario generator or WNTR is `semi_synthetic` or `synthetic` in column names, file names and docs. Never present it as real field data.
4. **No leakage.** Features use past observations only. Splits are chronological. Tune on the validation split only. The test split is evaluated once per final model.
5. **Work only inside this folder.** Do not read, edit or copy anything from the senior's project (`D:\GYATT\5th sem\AI\Senior\...`). It is not needed for any step. Do not touch other folders.
6. **Git:** commit after every finished step. **Never `git push`**, never force anything, never rewrite history, no remotes.
7. **No secrets.** None are needed for this project. Do not create accounts or API keys.
8. **Deleting:** avoid it. Never run recursive deletes. If you must remove a generated file inside this folder, remove that single file.
9. **Downloads:** public datasets only. Record URL, date and licence in `data/raw/<name>/SOURCE.md`. Check free disk space (keep at least 5 GB free) before large downloads. There is no download cap.

## Autonomy protocol (the user may be asleep)
- **Never wait for an answer.** If a choice is ambiguous, pick the conservative default, record it in `docs/decisions.md` (what, why, alternatives), and continue.
- **Dataset not obtainable?** Use the alternative named in `PLAN.md`, log it, and add "revisit original dataset" to the *Needs user* list in `PROGRESS.md`. The user will iterate on it later.
- **Three failed attempts at the same problem:** stop working on it, write the error and what you tried in `PROGRESS.md`, then move to the next step that does not depend on it. If nothing independent remains, stop cleanly.
- **After every task** update `PROGRESS.md`. After every step: run its check script, commit, then continue. A fresh session must be able to resume by reading `PROGRESS.md` alone.
- **Stop after Step 7.** Do not start the paper. The paper is written later with the user.
- Keep conversational output short. The record lives in `PROGRESS.md`, `docs/decisions.md` and Git.

## Environment (Windows)
- OS: Windows, Python **3.12**, Git for Windows (Bash available). Use `pathlib`, UTF-8 everywhere, no symlinks, no Bash-only scripts in the repo (use Python scripts so they run in PowerShell too).
- Python env: `.venv` in the repo root. Activate with `.\.venv\Scripts\Activate.ps1` (PowerShell) or run `.venv/Scripts/python` directly.
- Check tools at the start of Step 1 and log versions: `python --version`, `node --version`, `npm --version`, `git --version`, `docker --version`, `docker info`.
- **Node missing:** install with `winget install OpenJS.NodeJS.LTS`, then open a fresh shell and re-check. **Docker is never installed automatically.**
- **Docker missing or not running:** use the fallback profile (SQLite plus an in-process message bus behind the same interfaces). Log it. The MQTT and TimescaleDB path stays implemented and tested when Docker is available.
- Default ports: MQTT 1883, Postgres/Timescale 5432, API 8000, frontend 5173. If a port is busy, choose another and record it in the README.

## Tech stack (fixed unless a decision is logged)
| Layer | Choice |
|---|---|
| Language | Python 3.12 package under `src/kami/` |
| ML | scikit-learn, numpy, pandas, scipy; `wntr` only as a fallback data source |
| Transport | MQTT (Mosquitto, paho-mqtt) with an in-process fallback bus |
| Storage | PostgreSQL + TimescaleDB via Docker, SQLite fallback; one storage interface |
| API | FastAPI + uvicorn, WebSocket for live updates |
| Frontend | React + TypeScript + Vite, Leaflet (react-leaflet), a lightweight chart library |
| Tests | pytest (Python), Vitest (frontend) |

## Repository layout
```
src/kami/
  data/        loaders, schema, splits
  features/    causal feature functions
  simulator/   virtual sensor node, scenario generator
  models/      baselines, evidence, temporal, fusion
  eval/        metrics, harness, ablations
  ingest/      bus + worker (MQTT or in-process)
  store/       storage interface + backends
  api/         FastAPI app
frontend/      React app
scripts/       check_step_N.py, run_demo.py
tests/         step-wise tests
data/raw/      downloads (git-ignored) + SOURCE.md per dataset
data/processed/ (git-ignored)
results/       metrics JSON, tables (.md), figures, screenshots
docs/          reference/, decisions.md, datasets.md, scenarios.md, architecture.md
PROGRESS.md  PLAN.md  CLAUDE.md  README.md
```

## Quality bar
- Fixed random seeds. Re-running a command reproduces the same numbers.
- Every step ships a `scripts/check_step_N.py` that exits 0 **only** if that step's exit criteria hold, by reading real artefacts. Write it as the first task of the step.
- Report metrics at both point level and event level: precision, recall, F1, false alarms per day, detection latency (median and p90), per-event-type recall. Real-data results and semi-synthetic results are always reported **separately**.
- Streaming (live) feature code must match batch feature code. Test it.

## Dashboard design brief
Dark **operations-console** look, light theme available via a toggle, map-centred. Status colours must work for colour-blind users: use colour **plus** icon **plus** text for every status. Include loading, empty and error states, keyboard focus styles and a responsive layout. If a `frontend-design` skill is available, use it. No default template look.

## Definition of done (this overnight run)
Steps 0 to 7 pass their check scripts, `pytest -q` passes, `npm run build` passes, `results/SUMMARY.md` consolidates every table, and `PROGRESS.md` is current.

## Round 2 (added after the review)
Round 1 is finished. When PROGRESS.md says Round 2 is pending, read PLAN_ROUND2.md and work through it in order, with all the rules above. "Stop after Step 7" now means: stop after Round 2 (task R8). The paper is still written later with the user.
