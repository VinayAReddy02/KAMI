# KAMI Round 7: node numbers everywhere, live-test fixes, and a real-data test on GECCO drinking-water data

> The old file of this name (the Docker plan, merged into Round 6 Part B) was renamed to `PLAN_ROUND7_OLD_DOCKER.md` on 2026-10-12 and is history only.

Same rules as CLAUDE.md, including *Working mode*: Opus 5.5 high, single agent only (no subagents, parallel agents or multi-agent reviews), one task at a time as a chain (finish, test, record in PROGRESS.md, continue), take as much time as needed, resume from PROGRESS.md after an interruption. Do NOT re-tune, re-freeze or re-evaluate anything: `results/fusion/`, `results/round2/`, `results/citizen/eval*` and the held-out logs are final. No real Telegram message in this round (forced dry run in tests and checks).

## Decided by the user (2026-10-12)
- **Show the node number everywhere a node appears.** During the live test the dashboard only said "Bagayam", so the user could not tell it was node 4 / Ward 4. Format everywhere: **`Bagayam Booster (node-4 · Ward 4)`**; where space is tight (map label, phone width), at least **`4 · Bagayam`**. The node id, the number and the ward always come from `config/nodes.json` and `data/citizen/wards_demo_fictional.json` (one helper, no hard-coded strings).
- Further items from the live phone test are added below under N2 by the planning assistant before this round starts.
- **Real-data test on GECCO (user decision 2026-10-12, Part G).** KAMI's detection results so far come only from events our own generator inserted. Test the quality side on **real, independently labelled drinking-water events**: the GECCO Industrial Challenge 2019 dataset (https://zenodo.org/records/4304080, CC-BY-4.0; 2018 set https://zenodo.org/records/3884398 as the alternative), found in Round 6 E3 (`docs/real_data_search.md`). Downloading these public records is approved. It covers the **quality stream only** (no leak/burst labels), so the infrastructure side stays semi-synthetic; say so everywhere.
- **Order of work:** N1 -> N2 -> Part G (G0 to G6) -> N3.

## Tasks (write `scripts/check_round7.py` first and extend it as you go)

N1. Node numbers everywhere (one shared formatter in Python and one in TypeScript, both tested):
   - **Dashboard:** map marker labels and tooltips, the Overview list/status strip, the inject-controls node dropdown, Node detail title, Alerts table (node column) and its filter, Complaints page (nearest sensor point), Method page if it names nodes, any toast after inject ("Injected Burst at 4 · Bagayam"). Keep colour + icon + text, check phone width (390 px) and that no label is cut off.
   - **Telegram alert message** (`src/kami/notify/message.py`): `Node: Bagayam Booster (node-4 · Ward 4)`; keep the 600-character limit (test the longest case) and the `[KAMI DEMO - simulated data]` prefix.
   - **Citizen bot replies** (schedule answers, ward status, ticket replies, /help): name the ward with its sensor point, e.g. "Ward 4 (Bagayam, sensor point node-4)", in English and Hindi; the TemplateWriter, the grounding guard (the new number must not count as an unsupported claim) and the Hindi translation path (numbers must survive) must all keep working.
   - **API:** add `number` and `ward` fields to node objects in `/network`, `/nodes/{id}/state`, `/alerts`, `/complaints` (additive; existing fields unchanged).
   - **Docs:** README, `docs/demo_script.md` (use "4 · Bagayam" in the steps), `docs/citizen.md` sample replies, `docs/notifications.md` sample message.
   - **Screenshots:** regenerate the 16 paper screenshots with `scripts/screenshots.py` (the old ones show labels without numbers); keep the same file names.
   - Tests: Vitest for the formatter and the components that show nodes, Playwright (labels with numbers visible, dropdown option "4 · Bagayam"), pytest for the message and bot replies. Re-run axe on all pages (both themes).

N2. Fixes from the live phone test: **none needed.** The user ran the full live phone test on 2026-10-17 (English text, Hindi text, Hindi voice note, unanswerable question, notice question, photo + location ticket, burst injected at Bagayam then Ward 4 asked again) and everything worked as intended. Only the node-number issue was found, which is N1. Log N2 as "nothing to fix" and continue with Part G.

## Part G: real-data test on GECCO (quality stream)
Same evaluation discipline as Round 2: protocol written and committed before any test label is looked at, tuning on train/validation only, each model evaluated once on the locked test part, results reported whatever they are. New files only under `data/raw/gecco/`, `data/processed/gecco/`, `src/kami/data/gecco.py`, `src/kami/eval/gecco*.py`, `results/gecco/`, `docs/gecco.md`; nothing in `results/fusion/`, `results/round2/` or the frozen configuration changes.

G0. Download + inspect (no labels yet). Download the 2019 record (fall back to 2018 if the download fails or the licence is not CC-BY); write `data/raw/gecco/SOURCE.md` (URL, DOI, date, licence, citation, file hashes). Inspect columns, sampling interval, time range, missing values and which parts are train/validation/test **without computing anything from the event labels of the test part**. Write `scripts/check_round7.py` items for Part G.

G1. Protocol, committed before any test label is used: `docs/gecco_protocol.md`:
   - **Signal mapping** (document each): turbidity <- the turbidity column; TDS <- conductivity x 0.64 (the same factor as for USGS, docs/datasets.md); flow if present is NOT used by the quality module (record it). Units and any scaling stated.
   - **Resampling** from 1-minute to KAMI's 5-minute steps (median of the 5 values; a 5-minute step is an event if any of its minutes is labelled) and the effect on event counts.
   - **Splits:** use the dataset's own train / validation / test if the 2019 record provides them; otherwise a chronological 60/20/20 split. The test part is **locked** (registered like test_v3: one guarded read per final model, logged).
   - **Two variants, both pre-registered:**
     - **A: frozen transfer.** The frozen Round 2 quality evidence model, calibrator and thresholds, unchanged, applied to GECCO features. Because GECCO has no infrastructure stream, report the **quality-evidence decision** (the frozen quality threshold plus the frozen temporal rule) rather than the full fusion category, and explain why (the frozen fusion treats a missing stream as "Not assessed"). No refitting of anything.
     - **B: adapted.** Same feature code and model family; quality evidence model, calibration and threshold re-fitted on GECCO train, tuned on GECCO validation with the Round 2 objective (event F1 with at most 0.5 false alarms per day); frozen to `results/gecco/frozen_gecco.json` before the test read.
   - **Baselines on the same test part:** fixed thresholds and Isolation Forest, tuned on GECCO validation the same way; One-Class SVM if it runs in reasonable time.
   - **Metrics:** point and event level precision, recall, F1, false alarms per day, detection latency (median, p90), with bootstrap confidence intervals and paired differences B vs best baseline, as in Round 2. Also GECCO's own competition metric if it is defined in the record, labelled as such (context only; published leaderboard numbers are quoted only with their source).
   Commit `round 7 G1: gecco protocol (before test labels)`.

G2. Loader + features: `src/kami/data/gecco.py` (UTF-8, chronological, causal features via the existing feature code, label column kept separate), unit tests on a small synthetic frame, `data_kind = "real"` everywhere.

G3. Variant A run on validation (sanity only, nothing tuned), then the single guarded test run. Save predictions and metrics.

G4. Variant B: fit/tune on train+validation only, freeze, then the single guarded test run. Baselines tuned on validation, single test run each.

G5. Report `results/gecco/eval.md` + JSON (generated by script): both variants, baselines, CIs, event list with detected/missed and latency, a plot of one or two real events (script-generated, `results/gecco/figures/`). Plain statement of what transfers and what does not. Add a short "Real-data test (GECCO, quality stream)" section to `results/SUMMARY.md` through `scripts/make_summary.py`, clearly separated from the semi-synthetic results.

G6. Docs: `docs/gecco.md` (what was done and why), `docs/datasets.md` entry, `docs/decisions.md` (Round 7, Part G), README (how to reproduce), `docs/teacher_scope.md` row for real data updated, `docs/real_data_search.md` marked "used in Round 7". Commit `round 7 G: real-data test on GECCO (quality stream)`.

N3. Close out. `scripts/check_round7.py`, all earlier check scripts (`check_round6.py` with Docker only if Docker Desktop is running, otherwise `--part a` and `--part c` plus a note), `check_round5.py`, `check_telegram.py`, `check_round2.py --quick`, every `check_step_N.py`, `pytest -q`, `npm run build`, `npm run test`, the Playwright tests. Restore the three Round 1 access logs if they show as modified (line endings / time stamps only). Update PROGRESS.md, CLAUDE.md round history (Round 7 done), docs/decisions.md. Commit `round 7: node numbers everywhere + live-test fixes` (Part G has its own commits). Then push to GitHub as CLAUDE.md rule 6 says (clean tree and secrets check first, `git push origin master`, record the hash in PROGRESS.md). STOP.

## check_round7.py exits 0 only if
- every place listed in N1 shows the node number (Playwright + unit tests), the formatter is the only source of the label, and the Telegram message stays under 600 characters
- the citizen bot replies name the ward with its node number in English and Hindi, and the grounding guard and the citizen tests still pass
- the 16 screenshots were regenerated in this round and show numbered labels; axe shows no new serious or critical issue
- (Part G) `data/raw/gecco/SOURCE.md` exists with licence and hashes; `docs/gecco_protocol.md` was committed **before** the first guarded test read (compare the commit time with the test-access log); the test part was read once per final model (log); `results/gecco/eval.md` and its JSON exist, were produced by code, and contain variants A and B and the baselines with confidence intervals; data are labelled `real`
- no file under results/fusion/, results/round2/ or results/citizen/eval* changed (compare with git)
- all earlier checks still pass
