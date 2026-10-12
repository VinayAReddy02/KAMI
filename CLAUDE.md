# KAMI: standing rules for Claude Code

## What this project is
KAMI is a context-aware, multi-stage **anomaly intelligence system for water networks**. It watches four signals (flow, pressure, turbidity, TDS), scores infrastructure behaviour and water-quality behaviour as **separate evidence streams**, analyses **temporal context** (suddenness, persistence, recurrence), and **fuses** them into a category (Normal, Infrastructure, Quality, Combined), a priority, a confidence and a plain-language explanation. A React dashboard shows it live on a map.

- Existing detectors (fixed thresholds, Isolation Forest, One-Class SVM) are **baselines only**. They are not the contribution. The contribution is the staged contextual methodology and its fusion design, shown by ablations.
- This is a solo college project. There is **no physical hardware**: a *virtual sensor node* replays public data over MQTT, exactly as an ESP32 would.

## Read this first, every session
1. `PROGRESS.md` (where we stopped, what needs the user)
2. The plan of the current round (see *Current phase* below; `PLAN.md` holds the Round 1 steps and their exit checks)
3. `docs/decisions.md` (decisions already made; do not re-open them)
4. `docs/reference/` as needed: `project/` (abstract, first-phase report), `faculty/Faculty_feedback.txt`, `related_works/related_works.md`, `senior_project/AI_water_prj.docx`, `paper_format/` (used later, not now)

## Hard rules
1. **Stay in scope.** Only build what the current round's plan lists. No computer vision, routing or forecasting. Alert push goes out through a Telegram bot (WhatsApp was removed in Round 4). From Round 6 the same bot also has a citizen interface (Hindi/English voice and text questions with local open speech, translation and TTS models on the user's RTX 4070 laptop, schedule answers from retrieval plus a local Ollama LLM with a grounding guard, pipe-damage photo tickets without image recognition), exactly as `PLAN_ROUND6.md` describes; nothing beyond it. If you think something is missing, write it in `docs/decisions.md` under "Proposed"; do not build it.
2. **Never fake results.** No invented numbers, no hardcoded metrics, no tests that pass trivially. Every number in `results/` must come from running code on data. If something fails, say so in `PROGRESS.md`.
3. **Label synthetic data honestly.** Anything produced by the scenario generator or WNTR is `semi_synthetic` or `synthetic` in column names, file names and docs. Never present it as real field data.
4. **No leakage.** Features use past observations only. Splits are chronological. Tune on the validation split only. The test split is evaluated once per final model.
5. **Work only inside this folder.** Do not read, edit or copy anything from the senior's project (`D:\GYATT\5th sem\AI\Senior\...`). It is not needed for any step. Do not touch other folders.
6. **Git:** commit after every finished step. **Never `git push`**, never force anything, never rewrite history, no remotes.
7. **Secrets.** Never create accounts or API keys. The only secrets are the user's Telegram bot token and chat id; they live only in the git-ignored `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Round 6 needs no new key (Bhashini was dropped; the speech models run locally). Citizen voice notes and photos are personal data: only under git-ignored `data/citizen/uploads/`, never in logs, tests or commits. Never print, log, commit or copy them, never put them in tests, docs or error text, and never log a Telegram URL (it contains the token).
8. **Deleting:** avoid it. Never run recursive deletes. If you must remove a generated file inside this folder, remove that single file.
9. **Downloads:** public datasets only. Record URL, date and licence in `data/raw/<name>/SOURCE.md`. Check free disk space (keep at least 5 GB free) before large downloads. There is no download cap.

## Autonomy protocol (the user may be asleep)
- **Never wait for an answer.** If a choice is ambiguous, pick the conservative default, record it in `docs/decisions.md` (what, why, alternatives), and continue.
- **Dataset not obtainable?** Use the alternative named in `PLAN.md`, log it, and add "revisit original dataset" to the *Needs user* list in `PROGRESS.md`. The user will iterate on it later.
- **Three failed attempts at the same problem:** stop working on it, write the error and what you tried in `PROGRESS.md`, then move to the next step that does not depend on it. If nothing independent remains, stop cleanly.
- **After every task** update `PROGRESS.md`. After every step: run its check script, commit, then continue. A fresh session must be able to resume by reading `PROGRESS.md` alone.
- **Stop at the end of the current round** (see *Current phase* below). Do not start the paper. The paper is written later with the user.
- Keep conversational output short. The record lives in `PROGRESS.md`, `docs/decisions.md` and Git.

## Environment (Windows)
- OS: Windows, Python **3.12**, Git for Windows (Bash available). Use `pathlib`, UTF-8 everywhere, no symlinks, no Bash-only scripts in the repo (use Python scripts so they run in PowerShell too).
- Python env: `.venv` in the repo root. Activate with `.\.venv\Scripts\Activate.ps1` (PowerShell) or run `.venv/Scripts/python` directly.
- Check tools at the start of Step 1 and log versions: `python --version`, `node --version`, `npm --version`, `git --version`, `docker --version`, `docker info`.
- **Node missing:** install with `winget install OpenJS.NodeJS.LTS`, then open a fresh shell and re-check. **Docker is never installed automatically.**
- **Docker missing or not running:** use the fallback profile (SQLite plus an in-process message bus behind the same interfaces). Log it. The MQTT and TimescaleDB path stays implemented and tested when Docker is available. Docker Desktop is installed since 2026-10-12; fallback is still the default, docker mode is asked for with `--mode docker` or `KAMI_MODE=docker`; leave the containers stopped (`docker compose down`) at the end of a session.
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
  live/        streaming processor on the frozen Round 2 rule
  notify/      outbound alert push (dry run by default; Telegram bot from Round 4)
  citizen/     citizen interface on the same bot (Round 6): inbound polling, local speech/translation/TTS, retrieval + answer writers, tickets
frontend/      React app
scripts/       check_step_N.py, run_demo.py
tests/         step-wise tests
data/raw/      downloads (git-ignored) + SOURCE.md per dataset
data/processed/ (git-ignored)
results/       metrics JSON, tables (.md), figures, screenshots
docs/          reference/, decisions.md, datasets.md, scenarios.md, architecture.md
PROGRESS.md  CLAUDE.md  README.md  PLAN.md  PLAN_ROUND2.md  PLAN_WHATSAPP.md (superseded)  PLAN_ROUND4.md  PLAN_ROUND5.md  PLAN_ROUND6.md  PLAN_ROUND7.md (merged into 6)
```

## Quality bar
- Fixed random seeds. Re-running a command reproduces the same numbers.
- Every step ships a `scripts/check_step_N.py` that exits 0 **only** if that step's exit criteria hold, by reading real artefacts. Write it as the first task of the step.
- Report metrics at both point level and event level: precision, recall, F1, false alarms per day, detection latency (median and p90), per-event-type recall. Real-data results and semi-synthetic results are always reported **separately**.
- Streaming (live) feature code must match batch feature code. Test it.

## Dashboard design brief
Dark **operations-console** look, light theme available via a toggle, map-centred. Status colours must work for colour-blind users: use colour **plus** icon **plus** text for every status. Include loading, empty and error states, keyboard focus styles and a responsive layout. If a `frontend-design` skill is available, use it. No default template look.

## Definition of done (Round 1, achieved 2026-10-10)
Steps 0 to 7 pass their check scripts, `pytest -q` passes, `npm run build` passes, `results/SUMMARY.md` consolidates every table, and `PROGRESS.md` is current.

## Working mode (user decision, 2026-10-11; applies to every session from now on)
- **Model:** the user runs Claude Code on **Opus 5.5 at high effort**. Use that effort on correctness and judgement, not on volume of output.
- **Single-agent execution.** Do all work yourself in the main session. Do **not** spawn subagents, parallel agents, background workflows or multi-reviewer runs (such as the six-reviewer code review used in Round 2) unless the user explicitly asks for it in that session. If you think a second opinion is needed, do a focused self-review and note it in `PROGRESS.md`.
- **Use tokens reasonably:**
  - Read only what the task needs: search with grep and read line ranges instead of whole large files; do not re-read a file you just wrote.
  - Never dump large data, tables or logs into the conversation. Write them to files and print short summaries (counts, head/tail, the failing line).
  - Run the narrowest test first (`pytest path::test_name`), and the full suite once at the end of a task group.
  - Do not re-run long pipelines (dataset builds, tuning, final evaluation) unless their inputs changed. Reuse stored artefacts.
  - Prefer small edits over rewriting whole files. Keep `PROGRESS.md` notes to one or two lines per task.
- **Take your time, work as a chain (user instruction 2026-10-12).** There is no time pressure. Do one task at a time: finish it, test it, record it in `PROGRESS.md` (one or two lines plus *Current step*), then continue with the next task in the same session without waiting. Commit at the end of each step or part. After an interruption (for example a usage limit) resume from `PROGRESS.md` at the first unfinished task; never redo finished work.
- **Correctness still wins.** Saving tokens never justifies skipping a hard rule: no leakage, locked held-out sets, honest reporting, tests before commits.

## Current phase and round history
- **Round 1** (Steps 0 to 7, `PLAN.md`): done 2026-10-10.
- **Round 2** (evaluation fixes, `PLAN_ROUND2.md`): done 2026-10-10. The frozen configuration (`results/fusion/frozen_config.json`) and the held-out results are final: never re-tune, re-freeze or re-run the final evaluation.
- **Round 3** (WhatsApp alert push, `PLAN_WHATSAPP.md`, now superseded): done 2026-10-11. The user's real test failed: the Twilio trial only sends fixed templates (error 21654), so alerts could not carry their details. The W-1 work (live demo on the frozen rule) stays.
- **Round 4** (WhatsApp replaced by a Telegram bot, `PLAN_ROUND4.md`): done 2026-10-12. All WhatsApp/Twilio code is removed; the alert push is a Telegram bot, dry run by default. No real Telegram request was made in that round; the user tests the bot with the planning assistant.
- **Bot test (2026-10-12, user with the planning assistant):** passed. `.env` holds the token, chat id and `KAMI_TELEGRAM_ENABLE=1`; one test message and one real alert (injected burst, node-2, Infrastructure High) were delivered.
- **Round 5** (no Docker: alert wording M1, Playwright tests P1, paper screenshots P2, accessibility P3, quiet-demo measurement Q1, close-out P4; `PLAN_ROUND5.md`): done 2026-10-12. No real Telegram message was sent in that round.
- **Round 6** (`PLAN_ROUND6.md`, decided by the user 2026-10-12): done 2026-10-12, three commits. Part A: citizen interface on the Telegram bot (Hindi/English voice and text with local open speech models, tanker-schedule and notice answers from retrieval plus a local Ollama LLM behind a grounding guard, pipe-damage photo tickets linked to the nearest node, evaluation in `results/citizen/`); off by default (`KAMI_CITIZEN_ENABLE`). Part C: `docs/teacher_scope.md`, `docs/demo_script.md`, `docs/real_data_search.md`. Part B: Docker stack exercised (Mosquitto + TimescaleDB; `run_demo.py --mode docker` runs nodes, ingest worker and API as three processes; record in `results/docker/part_b.json`); fallback stays the default mode. No real Telegram message was sent in that round.
- **Round 7:** none (merged into Round 6 Part B on 2026-10-12; `PLAN_ROUND7.md` kept as history).
- **Current: nothing is in progress.** Next: the live phone test of the citizen bot with the user (steps in `PROGRESS.md`, *Needs user*), then the paper. Any further round is planned with the user first; do not start one alone.
