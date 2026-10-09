# Decisions log

Decided decisions are not to be re-opened. Add new ones at the bottom with: what, why, alternatives. Items under "Proposed" are ideas for the user; do not build them.

## Decided by the user (2026-10-10)
1. **Direction:** Track A only: sensor anomaly intelligence (flow, pressure, turbidity, TDS). The senior's chatbot (Water Access Navigator) is a reference for related work only and is not rebuilt. Not a single line of his code is reused.
2. **Team:** solo project. The second name on the report is a teammate on paper only.
3. **No hardware.** All data is public datasets, with a virtual sensor node replaying it over MQTT.
4. **Datasets:** alternatives are allowed when an original is unobtainable; log each substitution and add "revisit original dataset" to *Needs user* in PROGRESS.md.
5. **Fusion design:** Claude Code chooses by validation performance (see PLAN.md Step 5).
6. **Frontend:** React + TypeScript, dark operations-console theme with a light toggle.
7. **Map:** fictional network of about 8 nodes on real map tiles near Vellore, labelled as demo coordinates.
8. **Permissions:** allow-list in `.claude/settings.json` plus auto-approved file edits. Pushing and recursive deletes are denied.
9. **Docker:** unsure if installed. Check at Step 1; fall back to SQLite and an in-process bus if absent.
10. **Missing Node.js:** install via `winget install OpenJS.NodeJS.LTS`. Docker is never installed automatically.
11. **Downloads:** no cap (keep at least 5 GB disk free).
12. **Stop point:** after Step 7. The paper (ACM template, structure following the NeuroChat sample) is written with the user afterwards.

## Context
- The faculty feedback asks for originality and for avoiding already-implemented benchmark techniques. Baselines are used only for comparison; the contribution is the staged contextual fusion and its ablations.
- The first-phase report says combined fusion should be tested on synchronised data. With no hardware, fusion is tested on **semi-synthetic scenarios** (events injected into real background series). This must be stated everywhere results are shown.

## Proposed (not approved; do not build)
- (none yet)

## Log of decisions made during the build
(append here)

### Step 0 (2026-10-10)
- **Infrastructure data = BattLeDIM (simulated L-Town, 5-min).** Why: reachable, CC-BY, exact leak labels. Alternatives: LeakDB, BATADAL (reachable, not needed); Babela (not confirmed). Labelled `semi_synthetic` everywhere because README states it is generated from a hydraulic model.
- **Quality data = USGS NWIS stations 01654000, 01646305, 01654500, 2021-2022, 15-min.** Why: real, public domain, long, gap-light. They are streams, not distribution networks, and unlabelled; caveat stated in docs.
- **BattLeDIM leaks overlap continuously** (2019: an active leak in every row), so Step 2 must label event windows from each leak's start time (and peak/end), not "any leak flow > 0". Proposal for Step 2: label an event while that leak's flow exceeds a small detectable fraction of its peak.
- Only 2 flow-sensor-years of 3 sensors exist, so flow is sparse vs 33 pressure sensors; node assignment (Step 1) must document this.
- Git repo and `.venv` created in Step 0 (needed to run the check script); pandas installed there.

### Step 1 (2026-10-10)
- Tool versions: Python 3.12.6, Node 24.14.1, npm 11.11.0, git 2.54.0, Docker absent -> fallback profile (SQLite + in-process bus). Why in-process bus forces a single-process stack; alternatives (a local TCP broker) rejected as out of scope.
- Node assignment: pressure = 8 evenly spaced BattLeDIM 2018 sensors; flow = 3 BattLeDIM flow sensors reused (i mod 3); turbidity/TDS = USGS station (i mod 3) with per-node time offset, TDS = 0.64 x conductance. Node series are `semi_synthetic`.
- Readings keep BattLeDIM 2018 timestamps (replayed), 5-min step; speed 600 = 0.5 s per step.

### Step 2 (2026-10-10)
- **Two evaluation datasets, reported separately:** (a) `battledim_network`: real leak labels on simulated data, infra signals only (flow = PUMP_1, pressure = mean of 33 sensors), 33 events; (b) `scenarios`: semi-synthetic, 3 nodes, 180 events, all 4 signals. There is no labelled real quality data, so quality is only evaluated on scenarios (real USGS background, injected events).
- **BattLeDIM label rule** (see docs/scenarios.md): window from 50%-of-peak to +7 days; "onset of a new leak" framing because every 2019 row has an active leak. Alternatives (label full leak duration, per-sensor labels) rejected: they would label ~all of 2019 or need the pipe-to-sensor topology.
- Missing data: USGS values forward-filled <= 20 steps, then NaN; `valid` = all four signals present; events are only injected where valid; negative turbidity set to NaN (4426 rows at 01654500).
- Splits 60/20/20 by time per dataset; boundaries moved after any event they cut. Features use 12/72/288-step windows (1 h, 6 h, 24 h).
- Known limitation: scenario backgrounds carry BattLeDIM's own unlabelled leaks and drift, so the test period (late 2019) has a shifted background. Reported as-is.

### Step 3 (2026-10-10)
- Baselines: fixed thresholds (mean +/- k std from train, k tuned on val from a grid) and Isolation Forest (on raw signals + domain causal features; n_estimators/max_samples/score-quantile tuned on val). One-Class SVM from CLAUDE.md not implemented (PLAN Step 3 lists only the two; OCSVM on ~400k rows is slow). Add later if wanted.
- Metric conventions in `kami/eval/metrics.py` docstring: alerts merged across <= 12 steps; an alert is true if it overlaps an event window (+1 h grace); false alarms/day over scored normal days of that domain; latency only over detected events. Rows that are invalid, ambiguous or lack features are not scored.
- Domain evaluation: infra detectors vs `infra_flag`, quality detectors vs `quality_flag`; the joint IF is scored against each. Combined events count in both domains.
- BattLeDIM test split has only 8 events (1 burst, 7 leaks); fixed thresholds detect all of them partly because the late-2019 background drifts and keeps alerting (event precision ~0.41). Read these numbers with care.
- Test access is guarded by `final_evaluation`; the baseline run regenerates `results/baselines/test_eval_log.json` on each full run (7 models).

### Step 4 (2026-10-10)
- Evidence modules are **supervised** (use the domain flags on train), selected on val among logistic regression and gradient boosting by average precision (scenarios: HGB depth 3 for both domains; battledim infra: logistic regression C=0.1), isotonic calibration on val, with val numbers cross-fitted over 4 time blocks. The baselines are unsupervised, so the val-F1 comparison favours the modules by construction; it shows what labelled training buys, not that the method is better than unsupervised detection. Say so in the paper.
- Val event F1 (module vs best baseline): battledim infra 0.857 vs 0.560; scenarios infra 0.893 vs 0.730; scenarios quality 0.771 vs 0.261 (all modules >= baseline, no explanation needed).
- BattLeDIM infra calibration is poor (Brier val 0.28, test 0.33; only 17 train events and a drifting background). Reported as is.
- Temporal feature defaults (theta 0.5, k 3 steps, windows 2 h/6 h, gap 2 h, recurrence window 7 days) are fixed a priori, not tuned. Missing evidence counts as no evidence.
- Evidence probabilities are stored only for val (cross-fitted) and test rows (`data/processed/evidence_*.parquet`); train rows are NaN because they are in-sample for the base model. Fusion (Step 5) is therefore tuned on val only.
