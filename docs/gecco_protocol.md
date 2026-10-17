# GECCO real-data test: pre-registered protocol (Round 7, Part G1)

Written and committed **before any label of the test part is read** (2026-10-18). Nothing in this file may be changed
after the first guarded test read; later observations go into `docs/gecco.md` and `docs/decisions.md`. Data: GECCO
Industrial Challenge 2019, real drinking-water sensor data with event labels (`data/raw/gecco/SOURCE.md`, CC-BY-4.0).
Everything here is labelled `data_kind = "real"`. **Only KAMI's quality stream is tested**: the dataset has no
flow/pressure leak or burst labels, so every infrastructure result of KAMI stays semi-synthetic.

What was looked at before this protocol (G0): column names, units, time ranges, missing values and zero readings of
all three files; label statistics of the **train file only** (13 event runs, 0.16 % of minutes). Nothing was computed
from the labels of the validation or test file except that the `Event` column exists.

## 1. Data, splits and the locked test part
| KAMI split | GECCO file | Time span | Use |
|---|---|---|---|
| train | `7_gecco2019_train_water_quality.csv` | 2017-07-01 00:00 to 2017-09-30 23:59 | fit models (variant B, baselines) |
| validation | `8_gecco2019_valid_water_qulity.csv` | 2017-10-01 00:00 to 2017-11-08 00:29 | model choice, calibration, all tuning |
| **test (locked)** | `6_gecco2019_test_water_quality.csv` | 2017-11-08 00:30 to 2017-11-29 23:59 | read once per final model |

The split uses the dataset's own files in their time order (train < validation < test), so it is chronological. (The
challenge rules and the Zenodo text name the last two files the other way round; the time order decides here.)

**Locking.** The loader reads the test file's sensor values (needed for causal features) but **not its `Event` column**.
The test labels are loaded only inside `kami.eval.access.final_evaluation(model_id, "gecco_test", log_path=results/gecco/test_access_log.json)`,
which refuses a second read of the same model and records the time of each read. Each final model's test predictions
(with the labels) are written to `results/gecco/predictions/<model>.csv` at once and the read is marked completed;
every reported number is then computed from those files without opening the test file again.
Final models: **A**, **B**, **fixed_threshold**, **isolation_forest**, **ocsvm** (five reads, no more). If a run
fails after a read, the failure is reported; that model is not read again.

## 2. Signal mapping (quality stream only)
| KAMI input | GECCO column | Conversion |
|---|---|---|
| `turbidity` (FNU) | `Turb` (FNU) | none (same unit as the USGS data used so far) |
| `tds` (mg/L) | `Cond` (S/m) | `Cond × 10 000` gives µS/cm; `× 0.64` gives TDS, the same factor as for USGS (`docs/datasets.md`) |
| not used | `pH`, `SAC`, `Tp`, `PFM` | KAMI's quality stream has two inputs only. GECCO's events are defined on pH, conductivity, turbidity and SAC, so an event that shows only in pH or SAC is out of reach by design; this is reported, not fixed |
| `flow`, `pressure` | none | not present; no infrastructure evidence is computed |

Rows in which `Tp`, `pH`, `Cond`, `Turb` and `SAC` are all exactly 0 are sensor-panel dropouts: their values are set
to missing. No other cleaning, clipping or outlier removal (drift and outliers are part of the real data).

## 3. Resampling to KAMI's 5-minute steps
The 1-minute rows are grouped into clock-aligned 5-minute steps (00:00, 00:05, ...; the step's time stamp is its start).
A step's value is the **median** of its non-missing minutes (missing if all five are missing). A step is an event step
if **any** of its minutes has `Event = True`. An **event** is a maximal run of consecutive event steps; each gets an
`event_id`, type `real_quality_event`. The number of events at 1 minute and at 5 minutes is reported per split (merging
can join two labelled runs that are less than 5 minutes apart).

## 4. Features and scored rows
Causal features with the existing code (`kami.features.causal.compute_features`, signals `turbidity`, `tds`, windows
1 h, 6 h, 24 h), computed once on the whole chronological series train → validation → test (one node, `gecco`). Every
feature at step t uses steps ≤ t only; no label is used. A row is **scored** if all 36 quality columns of the frozen
quality module are finite (the first 24 h and gaps are not scored). The temporal features (suddenness, persistence,
recurrence) use `kami.features.temporal` with the frozen defaults and are computed over the sequence that starts at
the first validation step (so validation and test have the same history rule).

## 5. Variant A: frozen transfer (nothing fitted, nothing tuned)
- `p_quality` = the frozen Round 1/2 quality evidence module `data/processed/models/evidence_scenarios_quality.joblib`
  (trained on semi-synthetic events in USGS river data), its model and final calibrator unchanged.
- Decision = the frozen F-B rule's quality part: alert when `r_q × p_quality ≥ γ_q`, with
  `r_q = reliability(quality_persist_steps, quality_recurrence, r_min, τ_p, λ)` and `(r_min, τ_p, λ, γ_q)` read from
  `results/fusion/frozen_config.json` (F-B: 0.4, 6, 0.3 and γ_q = 0.8).
- Why not the full fusion category: GECCO has no infrastructure stream. With p_infra = 0 the F-B category is
  "Quality" exactly when this rule fires, so the quality decision **is** the frozen rule's output for this data; the
  live system would show a missing infrastructure stream as "Not assessed", which is not a detection outcome.
- Validation run: sanity only (reported, changes nothing).

## 6. Variant B: adapted (same feature code and model family, refitted on GECCO)
- `kami.models.evidence.EvidenceModule` with the same 36 quality columns and the same candidate models (two logistic
  regressions, two gradient-boosting depths): fitted on GECCO train (scored rows), the model chosen by validation
  average precision, isotonic calibration on validation.
- Tuning on validation only: the calibrated probabilities on validation are cross-fitted over 4 time blocks
  (`crossfit_val_proba`, as in Round 1/2); temporal features on them; grid of the F-B quality rule
  `r_min ∈ {0.4, 0.7}`, `τ_p ∈ {6, 24}`, `λ ∈ {0, 0.3}`, `γ_q ∈ {0.1, ..., 0.9, 0.95, 0.98}` (the Round 2 grid).
- Objective (Round 2): maximise event-counted F1 subject to **≤ 0.5 false alarms per day**; if no setting meets the
  cap, the fewest false alarms wins; exact ties go to the stricter setting (higher γ_q, then higher r_min).
- Frozen before the test read: `results/gecco/frozen_gecco.json` with the chosen model, parameters, the SHA-256 of the
  fitted module file, of the code in `src/kami/gecco/` and of the three data files. The test run refuses to start if any
  hash differs. On test the module uses its final calibrator (fitted on all validation rows); temporal history as in §4.

## 7. Baselines (same scored rows, same objective)
Fitted on GECCO train, tuned on validation with the same objective and cap, grids as in Round 2
(`kami.eval.run_baselines`): fixed thresholds on turbidity and TDS (`k ∈ {1.5, 2, 2.5, 3, 4, 5, 6, 8, 10}`),
Isolation Forest on the 36 quality columns (`(n_estimators, max_samples) ∈ {(100,256), (300,256), (100,2048)}`,
quantile ∈ {0.9, 0.95, 0.98, 0.99, 0.995, 0.999}), One-Class SVM on the same columns (`(ν, γ-multiplier) ∈ {(0.01,0.1),
(0.01,1), (0.05,0.1), (0.05,1)}`, same quantiles, fitted on at most 20 000 normal train rows).
The **best baseline** for the paired comparison is the one with the best validation objective, chosen before the test read.

## 8. Metrics (all on the locked test part, scored rows)
- Point level: precision, recall, F1 per 5-minute step.
- Event level (`kami.eval.metrics`, Round 2 definitions): recall (detected events / events), segment precision, event-
  counted precision and F1 (each detected event once), false alarms per day (alert segments not overlapping an event
  extended by 1 h, per day of scored normal rows), detection latency median and p90 (hours from event start).
- 95 % bootstrap intervals (1000 resamples, seed 12345; events and days resampled, `kami.eval.bootstrap`) for recall,
  both precisions, both F1 and false alarms per day; paired differences **B − best baseline**, **A − best baseline** and
  **B − A** on the same resampled events and days. A difference counts as shown only if its interval excludes 0.
- Context only: GECCO's own competition score, point-wise F1 on the 1-minute test rows (`f1score.R`). Each minute gets
  the decision of the latest 5-minute step that **ended** at or before that minute (causal, up to 5 minutes late).
  Published leaderboard numbers are not quoted (no verified source in hand).
- An event list for the test part: start, end, length, detected or missed and latency per model.
- If the test part contains very few events, the intervals will be wide; the numbers are reported as they are.

## 9. What does not change
`results/fusion/`, `results/round2/`, `results/citizen/eval*`, the frozen configuration and every frozen input file.
The GECCO code lives in `src/kami/gecco/` (the folders `src/kami/data/` and `src/kami/eval/` are frozen inputs of the
Round 2 freeze, so no file is added there). Results: `results/gecco/`. Processed data: `data/processed/gecco/` (git-ignored).
