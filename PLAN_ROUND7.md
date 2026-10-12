> **SUPERSEDED (2026-10-12):** merged into Round 6 as Part B (PLAN_ROUND6.md). Kept as history only; do not follow.

# KAMI Round 7: real messaging stack (Docker)

> Moved again on 2026-10-12 by the user: originally Round 4, then Round 5, then Round 6; now Round 7 because Round 6 is the citizen interface (PLAN_ROUND6.md). Start this round only after Round 6 is done AND the user confirms Docker Desktop is installed and running.

Same rules as CLAUDE.md, including *Working mode* (Opus 5.5 high, single agent, token-efficient). Do NOT re-tune, re-freeze or re-evaluate anything: results under `results/fusion/`, `results/round2/` and the test logs are final.

## Decided by the user
- The user installs Docker Desktop themselves. Never install or uninstall Docker (the planning assistant cannot do it either: it needs administrator approval and a restart).
- No real Telegram message in this round: tests and checks use the forced dry run.
- Before anything else: `git status`; restore the three Round 1 access logs if they show line-ending-only changes (see PLAN_ROUND5.md). Write `scripts/check_round7.py` first.

## Tasks

D1. Docker check. Run `docker info`. If Docker is not running, log it in PROGRESS.md and STOP (this round needs Docker). Record Docker and compose versions in docs/decisions.md.

D2. Real stack. `docker compose up -d` (Mosquitto and TimescaleDB). Run the MQTT and TimescaleDB tests that were skipped in fallback mode; fix real bugs they expose (small edits, tests first). Run `scripts/check_step_1.py` and `python scripts/run_demo.py --check` with `KAMI_MODE=docker`.

D3. Separate processes. Make it possible to run the virtual nodes, the ingest worker and the API as separate processes talking through MQTT and TimescaleDB (the architecture in the teacher's notes). Add `python scripts/run_demo.py --mode docker` for it, keep the fallback mode unchanged, and document both in README (ports, start and stop, `docker compose down`). Leave containers stopped at the end of the round.

D4. Browser tests on the Docker stack. Run the Round 5 (and any Round 6) Playwright tests once against the docker-mode demo (D3) as well as the fallback mode. Do not regenerate the paper screenshots unless the user asks.

D5. Close out. `scripts/check_round7.py`, all earlier check scripts (including `check_round6.py`, `check_round5.py`, `check_telegram.py`, `check_round2.py --quick`), `pytest -q` (the MQTT/TimescaleDB tests must now run, not skip, while Docker is up), `npm run build`, `npm run test`. Restore the three Round 1 logs if needed. Update README (both modes, ports, start/stop, `docker compose down`), PROGRESS.md, CLAUDE.md round history (Round 7 done), docs/decisions.md and the limitations in `results/SUMMARY.md` via `scripts/make_summary.py` (Docker path now exercised). Leave containers stopped. Commit `round 7: docker stack (mqtt + timescaledb, separate processes)`. STOP.

## check_round7.py exits 0 only if
- `docker info` works, and the MQTT/TimescaleDB tests passed, not skipped
- `scripts/check_step_1.py` and `run_demo.py --check` pass with `KAMI_MODE=docker`, and the separate-process docker demo starts, ingests from all 8 nodes and stops cleanly
- the Playwright tests pass in docker mode
- the citizen interface (Round 6) still works in fallback mode: its tests and `check_round6.py --quick` pass
- fallback mode is unchanged (its checks still pass)
- all earlier checks still pass and no file under results/fusion/ or results/round2/ changed in this round
