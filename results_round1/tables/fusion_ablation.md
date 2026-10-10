# Fusion and ablation results (test split, each model evaluated once)

Selected design: **F-B**. Selection rule: validation macro-F1 (out-of-fold, scenarios): F-A 0.5404, F-B 0.6453; ties within 0.005 go to F-B (fewer parameters, directly inspectable masses).

Two data kinds, reported separately. `scenarios` = semi-synthetic events on real/simulated background (4 categories). `battledim` = simulated hydraulics with leak labels, infrastructure evidence only (categories Normal vs Infrastructure; no quality stream). Fusion designs are fitted on validation only; validation macro-F1 for F-A/F-B variants is out-of-fold. Event metrics treat any alert as a detection of any event; `cat. acc.` is the share of events whose modal alert category equals the true category.

## scenarios

| Model | Val macro-F1 | Test macro-F1 | Test accuracy | Event P | Event R | Event F1 | False alarms/day | Latency med (h) | Cat. acc. | Infra event F1 | Quality event F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F-A | 0.540 | 0.570 | 0.667 | 0.205 | 1.000 | 0.341 | 1.77 | 0.00 | 0.783 | 0.271 | 0.367 |
| F-B (selected) | 0.645 | 0.571 | 0.745 | 0.220 | 0.983 | 0.359 | 2.19 | 0.08 | 0.650 | 0.277 | 0.506 |
| F-A (no temporal) | 0.540 | 0.508 | 0.627 | 0.192 | 1.000 | 0.322 | 1.83 | 0.00 | 0.700 | 0.224 | 0.279 |
| F-B (no temporal) | 0.641 | 0.566 | 0.745 | 0.222 | 0.983 | 0.362 | 2.19 | 0.08 | 0.650 | 0.274 | 0.520 |
| threshold voting (no fusion) | 0.432 | 0.433 | 0.759 | 0.800 | 0.883 | 0.840 | 0.16 | 2.50 | 0.700 | 0.910 | 0.716 |
| single joint model (no separated evidence) | 0.464 | 0.321 | 0.495 | 0.289 | 0.950 | 0.443 | 1.13 | 0.00 | 0.433 | 0.335 | 0.336 |
| baseline: fixed_threshold | 0.306 | 0.364 | 0.782 | 0.435 | 0.700 | 0.536 | 0.66 | 2.21 | 0.417 | 0.575 | 0.045 |
| baseline: isolation_forest | 0.239 | 0.247 | 0.687 | 0.443 | 0.833 | 0.578 | 0.84 | 0.58 | 0.417 | 0.581 | 0.359 |

## battledim

| Model | Val macro-F1 | Test macro-F1 | Test accuracy | Event P | Event R | Event F1 | False alarms/day | Latency med (h) | Cat. acc. | Infra event F1 | Quality event F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F-A | 0.518 | 0.424 | 0.553 | 0.331 | 1.000 | 0.498 | 1.28 | 18.04 | 1.000 | 0.498 | n/a |
| F-B (selected) | 0.496 | 0.365 | 0.432 | 0.812 | 1.000 | 0.897 | 0.04 | 0.00 | 1.000 | 0.897 | n/a |
| F-A (no temporal) | 0.346 | 0.377 | 0.605 | 0.000 | 0.000 | 0.000 | 0.00 | n/a | 0.000 | 0.000 | n/a |
| F-B (no temporal) | 0.321 | 0.587 | 0.590 | 0.385 | 1.000 | 0.556 | 1.15 | 0.42 | 1.000 | 0.556 | n/a |
| threshold voting (no fusion) | 0.336 | 0.283 | 0.395 | 0.889 | 1.000 | 0.941 | 0.01 | 0.00 | 1.000 | 0.941 | n/a |
| single joint model (no separated evidence) | 0.462 | 0.320 | 0.393 | 0.553 | 1.000 | 0.712 | 0.25 | 0.00 | 1.000 | 0.712 | n/a |
| baseline: fixed_threshold | 0.508 | 0.491 | 0.493 | 0.408 | 1.000 | 0.580 | 1.04 | 0.00 | 1.000 | 0.580 | n/a |
| baseline: isolation_forest | 0.472 | 0.474 | 0.579 | 0.409 | 1.000 | 0.581 | 1.99 | 7.71 | 1.000 | 0.581 | n/a |

