# KAMI Round 2: fix the evaluation flaws

Round 1 (Steps 0-7) is finished and committed. Round 2 fixes four flaws found in review. Same rules as CLAUDE.md apply (no faking, no leakage, label synthetic data, never git push, never wait for answers, log decisions in docs/decisions.md, update PROGRESS.md after each task, commit after each task group). Do NOT change the scenario generator rules, the evidence modules or the dashboard unless a task below says so.

## The flaws
1. Fusion (F-B) has event F1 0.359 and 2.19 false alarms/day on scenarios, versus threshold voting 0.840 and 0.16/day.
2. The selection objective (validation macro-F1) ignores false alarms.
3. The test split was seen: F-B's decision rule was changed after viewing validation and test output.
4. Temporal features barely help and no confidence intervals exist (60 test events).

## Decisions already made by the user (do not re-open)
- Fresh test data: regenerate scenario test events with a NEW seed; the old test events become `test_v1` and are labelled "exposed". Freeze the method on validation only, then evaluate once on `test_v2`.
- Selection objective: maximise validation event F1 subject to false alarms <= 0.5 per day. Macro-F1 is a secondary number.
- If fusion still loses to threshold voting, report it honestly and reframe the value (explainability, priority, correct Infrastructure/Quality/Combined categories). Do not tune until it wins.
- Add a One-Class SVM baseline (subsample for speed). Add LeakDB as extra infrastructure validation only if time allows (time-box 45 minutes; simulated, label it so).

## Tasks (in order; write scripts/check_round2.py as the first task and extend it as you go)

R0. Freeze round 1. `git tag round1`. Copy results/ to results_round1/ (copy, never delete). Mark in docs/decisions.md: test_v1 is exposed for F-B; BattLeDIM test split is exposed for F-B and cannot be refreshed.

R1. New test set. Add a `test_v2` scenario set: same generator, same rules, same event-type counts (12 per type), a new seed (use 20261010, record it), injected into the same test-period backgrounds. Guard access exactly like test_v1 (only `final_evaluation`, with a counter). Keep test_v2 locked until R6. Check: same seed gives an identical hash; no event overlaps a split boundary; v1 and v2 events differ.

R2. New selection objective. For F-A and F-B (and their no-temporal variants), tune the decision threshold(s) and any free fusion parameters on VALIDATION ONLY, out-of-fold over the existing time blocks, to maximise event F1 subject to false alarms/day <= 0.5. If no setting satisfies the cap, take the lowest false-alarm setting and say so. Select the design with the best constrained validation event F1; ties within 0.005 go to the more interpretable design. Log all validation numbers. Then write results/fusion/frozen_config.json (design, all parameters, git commit hash, sha256 of the file list used) BEFORE any test_v2 access. R6 must load this file and refuse to run if it has changed.

R3. Temporal ablation with uncertainty. On VALIDATION only: repeat the with/without-temporal comparison across 5 different scenario-generation seeds (new seeds for the validation period, separate from training) and report mean and spread of event F1, false alarms/day and category accuracy. State plainly whether temporal features help, hurt, or make no detectable difference.

R4. One-Class SVM baseline. Per domain, RBF kernel, fit on a fixed-seed subsample of at most 20,000 normal training rows, tune nu and gamma on validation. Add it to baselines and ablation tables. Time-box; if it cannot finish in 20 minutes per domain, reduce the subsample and log it.

R5. (Optional, time-box 45 min) LeakDB. If reachable, download to data/raw/leakdb with SOURCE.md, load a subset of scenarios, and report the infrastructure evidence module and threshold voting on it as extra validation. Mark it `simulated`. If anything fails after 3 attempts, log it and skip.

R6. Final evaluation, once. Load frozen_config.json, evaluate every model in the ablation table on test_v2 exactly once (log a counter and hash). Also report BattLeDIM test with the flag "previously exposed for F-B". Add bootstrap 95% confidence intervals (1000 resamples, fixed seed): resample events for recall/precision/F1, resample whole days for false alarms/day. Report test_v1 numbers in a separate table labelled "exposed, for reference only".

R7. Honest reporting. Regenerate results/SUMMARY.md by script. It must include: the new tables with CIs, the temporal-ablation verdict, the OCSVM rows, a plain statement of whether fusion beats threshold voting at the 0.5/day cap, and, because category separation is the real strength, a table of category accuracy and per-category recall for fusion vs voting vs baselines. If fusion loses on event F1, say so in the first paragraph. Update the limitations list and docs/decisions.md. Update README only where it is now wrong.

R8. Close out. Run scripts/check_round2.py, every scripts/check_step_N.py, pytest -q and npm run build. Fix regressions. Commit as `round 2: <summary>`. Update PROGRESS.md (Round 2 status, anything needing the user). Then STOP. Do not write the paper.

## Check script (scripts/check_round2.py), exits 0 only if
- frozen_config.json exists and its recorded commit predates the first test_v2 access in the log
- test_v2 log shows exactly one evaluation per model
- results contain CIs for every headline metric and the OCSVM rows
- the SUMMARY states the fusion-vs-voting outcome and reads from files
- all earlier check scripts and pytest still pass

## If stuck
Three failed attempts at one task: log it in PROGRESS.md, skip to the next independent task. R5 is skippable. R2, R6 and R7 are not.
