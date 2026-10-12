# KAMI Round 5: alert wording, browser tests, screenshots, accessibility, quiet-demo measurement

> Re-planned on 2026-10-12 by the user: Round 5 contains everything that does NOT need Docker. The Docker stack (D1 to D3) moved to Round 6 (`PLAN_ROUND6.md`). Do not run, install or check Docker in this round.

Same rules as CLAUDE.md, including *Working mode* (Opus 5.5 high, single agent, token-efficient). Do NOT re-tune, re-freeze or re-evaluate anything: results under `results/fusion/`, `results/round2/` and the test logs are final. Running Round 1/2 check scripts is fine; never run `kami.eval.run_final` in a mode that opens held-out data.

## Decided by the user
- (2026-10-11, confirmed 2026-10-12) One-time exception to the download rule: installing Playwright with Chromium (and axe-core for accessibility checks) for local browser testing is allowed.
- (2026-10-12) The Telegram bot works end to end: the planning assistant sent one test message and one real alert from an injected burst at node-2 (Infrastructure, High, 0.69), both delivered. `.env` now holds `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `KAMI_TELEGRAM_ENABLE=1`. Never print or copy these values.
- **No real Telegram message in this round.** Every test, check, screenshot run and the Q1 measurement must use the forced dry run (the default of `launch`/`build_live`); never call `launch(..., notifications="auto")`, `run_demo.py` without `--check`, or `send_test_alert.py`.

## Before anything else
- `git status`. If `results/baselines/test_eval_log.json`, `results/evidence/test_eval_log.json` or `results/fusion/test_eval_log.json` show as modified with only line-ending changes (content identical), run `git restore` on those three files. Known cause: `check_step_3.py` to `check_step_5.py` rewrite these Round 1 logs; restore them again after running the earlier checks in P4 and before committing (see docs/decisions.md, Round 4 correction).
- Write `scripts/check_round5.py` first and extend it as you go.

## Tasks (in this order)

M1. Telegram alert wording (decided by the user 2026-10-12 after the first real alert; do this first, it is a small change in `src/kami/notify/message.py` and its tests; no model, threshold or frozen result is touched). The first real alert read:
   `[KAMI DEMO - simulated data] / Node: Gandhi Nagar Tank (node-2) / Category: Infrastructure | Priority: High | Confidence: 0.69 / Infrastructure anomaly, priority High (confidence 0.69): infrastructure evidence 0.99, above threshold for 2.0 h, suddenness 0.88, 1 episode(s) in the last 7 days. / Replay time: 2018-01-07 16:45`
   Three changes, all using the real values and nothing invented:
   1. "Infrastructure evidence 0.99" next to "confidence 0.69" looks contradictory. Label them as different things: the evidence value becomes "model score" (or similar), confidence stays "confidence", and add a short plain note that confidence is the final fused value (docs/notifications.md explains it in one sentence).
   2. Replace the technical "above threshold for 2.0 h" and "suddenness 0.88" with plain words generated from the same numbers (for example "unusual for 2 h" and "started suddenly" / "built up gradually" using the existing suddenness value with a documented cut-off). Keep the numbers available in brackets or on the dashboard if the message still fits.
   3. Add one generic action line per category (Infrastructure: "Check pressure and flow at <node name>."; Quality: "Check turbidity and TDS at <node name>."; Combined: both). It must not name a cause (no "leak" or "contamination" claims).
   Keep the `[KAMI DEMO - simulated data]` prefix, the "Replay time" line and the 600-character limit (test the longest case). Update the unit tests, the sample message in docs/notifications.md and README. Do not send a real message in this task.

P1. Playwright. Install `@playwright/test` as a frontend dev dependency and Chromium via `npx playwright install chromium`. Write `frontend/e2e/` tests that start from a running demo: Overview loads with 8 markers and the "Demo network, fictional layout" label; injecting an infrastructure event makes an alert appear in the feed; Node detail shows the four charts and the explanation; the Alerts table filters; the theme toggle works.

P2. Screenshots for the paper. Script `scripts/screenshots.py` (or a Playwright spec) saving to `results/screens/`: Overview, Node detail during an injected event, Alerts, Method page; dark and light; desktop (1440x900) and phone (390x844). File names say what they show. No hand-edited images.

P3. Accessibility check. Run axe-core through Playwright on each page in both themes. Fix serious and critical issues that are clearly bugs (contrast, missing labels, focus); list anything not fixed in docs/decisions.md with the reason. Save the report to `results/a11y/`.

Q1. Quiet-demo measurement (live-demo behaviour, NOT an evaluation metric). Measure how often the live demo raises alerts on its own, with no injection, so the user knows what to expect during a presentation.
   - First check which data the live demo replays (`src/kami/live/`, `config`). If any of it comes from a locked held-out set (test_v2, test_v3, BattLeDIM test), do NOT run Q1: log it in PROGRESS.md and docs/decisions.md and move on.
   - Otherwise run the fallback demo in-process (`launch(..., temp_store=True)`, forced dry run, no injection) at high replay speed over a fixed, documented window (for example 14 simulated days, all 8 nodes), with a fixed seed/start so it is reproducible. Count alerts opened per node and per simulated day, by category and priority, and how many would have triggered a Telegram message under the current rule (High or Critical, cooldown, hourly cap).
   - Save `results/demo_quiet/quiet_demo.json` and a short `results/demo_quiet/quiet_demo.md` table. Wording must make clear this is replayed demo data (simulated infrastructure, real river quality), not a false-alarm rate. Add a one-line note to README under the demo section ("with no injection, expect about N alerts per simulated day, M of them High or above").

P4. Close out. `scripts/check_round5.py`, all earlier check scripts (including `check_telegram.py` and `check_round2.py --quick`), `pytest -q`, `npm run build`, `npm run test`, the Playwright tests. Then restore the three Round 1 logs if they show as modified (see above). Update README (browser tests, screenshots, accessibility report, quiet-demo note, new alert message sample), PROGRESS.md, CLAUDE.md round history (Round 5 done, Round 6 next), docs/decisions.md and, if anything in it changes, `results/SUMMARY.md` via `scripts/make_summary.py` (never by hand). Commit `round 5: alert wording, browser tests, screenshots, accessibility, quiet demo`. STOP.

## check_round5.py exits 0 only if
- (M1) the alert message tests pass: the message is under 600 characters in the longest case, keeps the `[KAMI DEMO - simulated data]` prefix, contains the plain-language reasons and the generic action line, and names no cause
- the Playwright tests pass and every expected screenshot exists and is non-empty (4 pages x 2 themes x 2 sizes = 16 files)
- the axe report exists with no unresolved serious or critical issue that is not listed in docs/decisions.md
- (Q1) `results/demo_quiet/quiet_demo.json` exists and its counts were produced by a run in this round (or a logged reason why Q1 was skipped)
- no real Telegram request was made by any check or test (the Telegram test fixture that refuses network access is active)
- all earlier checks still pass and no file under results/fusion/ or results/round2/ changed in this round (compare with git; the three Round 1 access logs are compared without time stamps, as in check_telegram)
