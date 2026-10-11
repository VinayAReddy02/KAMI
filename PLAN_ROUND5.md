# KAMI Round 5: real messaging stack (Docker) and browser checks (Playwright)

> Renumbered on 2026-10-12: this was planned as Round 4. Round 4 is now the WhatsApp -> Telegram replacement (PLAN_ROUND4.md). Start this round only after Round 4 is done, the user has tested the Telegram bot, and the user confirms Docker Desktop is installed and running.

Same rules as CLAUDE.md, including *Working mode* (Opus 5.5 high, single agent, token-efficient). Do NOT re-tune, re-freeze or re-evaluate anything: results under `results/fusion/`, `results/round2/` and the test logs are final. Running Round 1/2 check scripts is fine; never run `kami.eval.run_final` in a mode that opens held-out data.

## Decided by the user (2026-10-11, confirmed 2026-10-12)
- The user installs Docker Desktop themselves before this round. Never install or uninstall Docker.
- One-time exception to the download rule: installing Playwright with Chromium (and axe-core for accessibility checks) for local browser testing is allowed.

## Tasks (write `scripts/check_round5.py` first and extend it as you go)

D1. Docker check. Run `docker info`. If Docker is not running, log it in PROGRESS.md, skip D2 to D3 and continue with P1. Record Docker and compose versions in docs/decisions.md.

D2. Real stack. `docker compose up -d` (Mosquitto and TimescaleDB). Run the MQTT and TimescaleDB tests that were skipped in fallback mode; fix real bugs they expose (small edits, tests first). Run `scripts/check_step_1.py` and `python scripts/run_demo.py --check` with `KAMI_MODE=docker`.

D3. Separate processes. Make it possible to run the virtual nodes, the ingest worker and the API as separate processes talking through MQTT and TimescaleDB (the architecture in the teacher's notes). Add `python scripts/run_demo.py --mode docker` for it, keep the fallback mode unchanged, and document both in README (ports, start and stop, `docker compose down`). Leave containers stopped at the end.

P1. Playwright. Install `@playwright/test` as a frontend dev dependency and Chromium via `npx playwright install chromium`. Write `frontend/e2e/` tests that start from a running demo: Overview loads with 8 markers and the "Demo network, fictional layout" label; injecting an infrastructure event makes an alert appear in the feed; Node detail shows the four charts and the explanation; the Alerts table filters; the theme toggle works.

P2. Screenshots for the paper. Script `scripts/screenshots.py` (or a Playwright spec) saving to `results/screens/`: Overview, Node detail during an injected event, Alerts, Method page; dark and light; desktop (1440x900) and phone (390x844). File names say what they show. No hand-edited images.

P3. Accessibility check. Run axe-core through Playwright on each page in both themes. Fix serious and critical issues that are clearly bugs (contrast, missing labels, focus); list anything not fixed in docs/decisions.md with the reason. Save the report to `results/a11y/`.

P4. Close out. `scripts/check_round5.py`, all earlier check scripts (including check_telegram and check_round2 --quick), `pytest -q`, `npm run build`, `npm run test`, the Playwright tests. Update README, PROGRESS.md, docs/decisions.md and the limitations in `results/SUMMARY.md` via `scripts/make_summary.py` (Docker path now exercised, if D2 passed). Commit `round 5: docker stack and browser checks`. STOP.

## check_round5.py exits 0 only if
- (if Docker ran) the MQTT/TimescaleDB tests passed, not skipped, and the docker-mode smoke check passed
- the Playwright tests pass and every expected screenshot exists and is non-empty
- the axe report exists with no unresolved critical issue that is not listed in docs/decisions.md
- all earlier checks still pass and no file under results/fusion/ or results/round2/ changed in this round (compare with git)
