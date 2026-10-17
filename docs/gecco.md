# Real-data test on GECCO drinking-water data (Round 7, Part G)

## Why
Until Round 7 every detection number of KAMI came from events that KAMI's own scenario generator had inserted
(semi-synthetic). The user asked for a test on **real, independently labelled** events. The best public candidate
(`docs/real_data_search.md`) was the GECCO Industrial Challenge 2019 dataset: real one-minute sensor data from the outflow
of a German waterworks (Thüringer Fernwasserversorgung) with events labelled by the provider, CC-BY-4.0
(`data/raw/gecco/SOURCE.md`). It has water-quality signals only, so **only KAMI's quality stream was tested**; the
infrastructure (leak and burst) side stays semi-synthetic.

## How
- The protocol `docs/gecco_protocol.md` was committed before any test label was read (commit `3a2b05d`); the test
  labels are readable only inside the guarded access, and each of the five final models was read once
  (`results/gecco/test_access_log.json`).
- Splits by time, using the dataset's own files: train Jul to Sep 2017 (13 events), validation
  1 Oct to 8 Nov (12 events), test 8 to 29 Nov (12 events), all at 5-minute steps.
- Inputs: turbidity (FNU, unchanged) and TDS = conductivity (S/m) x 10 000 x 0.64. pH, SAC, temperature and flow-meter
  frequency are not KAMI inputs.
- **A, frozen transfer:** the Round 2 quality module and the frozen F-B rule, unchanged (trained on semi-synthetic events
  in US river data).
- **B, adapted:** the same causal features and model family, refitted on GECCO train; model chosen and calibrated on
  validation (logreg_C1), rule tuned on validation with the Round 2 objective (r_min 0.4, tau_p 6,
  lambda 0.0, gamma_q 0.4); frozen with file hashes before its test read.
- Baselines (fixed thresholds, Isolation Forest, One-Class SVM) tuned on validation the same way; the best on
  validation was **fixed_threshold**.
- Code: `src/kami/gecco/` (data, evaluate, report), tests `tests/gecco/`. Report: `results/gecco/eval.md`.

## Results on the locked test part (12 real events)
| Model | Events detected | Event-counted F1 [95% CI] | False alarms / day [95% CI] | Alert time (normal steps) | Point F1 | GECCO 1-min F1 |
|---|---|---|---|---|---|---|
| A | 0 of 12 | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.0% | 0.000 | 0.000 |
| B | 4 of 12 | 0.444 [0.133, 0.737] | 0.092 [0.000, 0.277] | 0.1% | 0.290 | 0.180 |
| fixed_threshold | 11 of 12 | 0.917 [0.800, 1.000] | 0.046 [0.000, 0.139] | 3.4% | 0.219 | 0.161 |
| isolation_forest | 11 of 12 | 0.733 [0.588, 0.889] | 0.321 [0.137, 0.597] | 6.0% | 0.156 | 0.116 |
| ocsvm | 9 of 12 | 0.857 [0.667, 1.000] | 0.000 [0.000, 0.000] | 4.9% | 0.159 | 0.110 |

Paired differences in event-counted F1: B - fixed_threshold [-0.783, -0.218], A - fixed_threshold [-1.000, -0.800], B - A [0.133, 0.737].

## What transfers and what does not
- **The frozen quality evidence does not transfer.** Variant A raised no alert on validation or test: the module learned
  the levels and swings of river turbidity and conductivity (scenario turbidity median 2.5 FNU, 90th percentile 16 FNU,
  with events of the generator's size), while this drinking water sits near 0.13 FNU; its evidence never reached the frozen threshold. A module trained on semi-synthetic
  river events is not a ready detector for another water body.
- **Refitting the same pipeline works partly, but simple baselines do better on events here.** B found 4 of 12
  events with few false alarms and almost no alert time, but its event-counted F1 is below the fixed-threshold baseline's,
  and the paired interval excludes 0. B is better than A (interval excludes 0).
- **The baselines' event scores are helped by long alerts.** The fixed-threshold and Isolation Forest baselines stayed in
  alert for 3.4% and 6.0% of the normal test time (the TDS level of the test weeks,
  mean 128 mg/L, lies about 3 training standard deviations below the training mean of 135 mg/L), and a long alert that overlaps an event counts as a detection. On the metrics that count every
  alerted step (point F1 and GECCO's own 1-minute F1), B scores highest of the five models.
- **What this says about KAMI:** the staged design (calibrated evidence, temporal context, frozen rule) can be refitted
  to a new site in minutes, but on this real data it did not beat simple detectors at finding events; the advantage seen
  on semi-synthetic data is not confirmed on real quality events. The infrastructure side remains untested on real data.

## Limits
12 test events (wide intervals); one site; GECCO's events include changes in pH and SAC, which KAMI does not measure;
labels are the provider's; the TDS conversion is a convention; the event metrics do not penalise alert duration.

## Reproduce
```powershell
.\.venv\Scripts\python -m kami.gecco.evaluate val-a        # variant A on validation (sanity)
.\.venv\Scripts\python -m kami.gecco.evaluate tune         # B and baselines on validation, writes results/gecco/frozen_gecco.json
.\.venv\Scripts\python -m kami.gecco.evaluate test --model A   # one guarded test read per model (refused a second time)
.\.venv\Scripts\python -m kami.gecco.report                # results/gecco/eval.md, eval.json, figures
```
The test reads are already logged in this repository, so `test` refuses to run again; the report can be rebuilt any time.
