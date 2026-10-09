# PROGRESS

Update this file after every task. A new session must be able to resume from here alone.

**Last updated:** 2026-10-10
**Current step:** 7
**Mode:** unattended allowed; never wait for answers (see CLAUDE.md)

## Steps
| Step | Name | Status | Check script | Commit |
|---|---|---|---|---|
| 0 | Dataset recon | passed | scripts/check_step_0.py | step 0 |
| 1 | Foundations | passed | scripts/check_step_1.py | step 1 |
| 2 | Data pipeline, features, scenarios | passed | scripts/check_step_2.py | step 2 |
| 3 | Baselines and harness | passed | scripts/check_step_3.py | step 3 |
| 4 | Evidence modules and temporal analysis | passed | scripts/check_step_4.py | step 4 |
| 5 | Fusion and ablations | passed | scripts/check_step_5.py | step 5 |
| 6 | Live pipeline and dashboard | passed | scripts/check_step_6.py | step 6 |
| 7 | Hardening and documentation | not started | scripts/check_step_7.py | |

Status values: not started, in progress, passed, blocked.

## Needs user (read this first in the morning)
- Revisit original dataset: no real labelled infrastructure data is used; BattLeDIM is simulated (semi_synthetic). Babela et al. 2026 dataset not confirmed.
- Fusion result is mixed: better point-level macro-F1 than voting/baselines but far more false alarms than threshold voting (see results/SUMMARY.md). Worth discussing how to reframe the contribution.
- Quality data are USGS river stations (real, unlabelled), a stand-in for a drinking-water network.

## Environment findings
- Python 3.12.6, Node v24.14.1, npm 11.11.0, git 2.54.0. **Docker not installed** -> mode = fallback (SQLite + in-process bus). MQTT/Timescale code is implemented but its tests are skipped here (reason shown in pytest output); never run against real brokers.
- In fallback mode the API, worker and nodes must share one process (check script and run_demo do this).
- Disk: ~58 GB free on D:.

## Log
(newest first; one line per task: date, what, result)
- 2026-10-10 Step 6: streaming processor, injector, API (/network, /nodes/{id}/state, /alerts, /demo/*), React dashboard (Overview, Node detail, Alerts, Method, controls, light/dark), check_step_6 PASS (combined event detected in ~3 s wall). Screenshots to results/screens skipped: Playwright not installed and browser downloads are not allowed; dashboard was checked by hand in the in-app browser.
- 2026-10-10 Step 5: F-A and F-B fusion, 8-row ablations x 2 data kinds, confusion matrices, F-B selected; fusion does NOT beat plain threshold voting on event F1 (documented in decisions.md and results/SUMMARY.md). check_step_5 PASS
- 2026-10-10 Step 4: calibrated evidence modules (battledim infra, scenarios infra/quality), temporal features + hand-computed tests, check_step_4 PASS
- 2026-10-10 Step 3: harness (metrics, guarded test access), fixed-threshold + Isolation Forest baselines, results/tables/baselines.md, check_step_3 PASS (~1 min)
- 2026-10-10 Step 2: loaders, causal features, splits, scenario generator (180 events, 12 per type per split), check_step_2 PASS. Run `python scripts/build_datasets.py` to regenerate data/processed + results/splits.
- 2026-10-10 Step 1: store/bus/worker/API/node fleet, check_step_1 PASS (8 nodes x 268 rows in 20 s), tests 5 passed 2 skipped (no Docker)
- 2026-10-10 Step 0: BattLeDIM + USGS downloaded, loaders, docs/datasets.md, check_step_0 PASS
