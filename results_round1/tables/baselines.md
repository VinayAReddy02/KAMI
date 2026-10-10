# Baseline results (test split, evaluated once per model)

Tuned on the validation split only. `battledim`: simulated hydraulics with leak labels; `scenarios`: semi-synthetic events on real/simulated background. Reported separately. Latency in hours (n/a = nothing detected).

| Dataset | Domain | Model | Point P | Point R | Point F1 | Event P | Event R | Event F1 | False alarms/day | Latency med (h) | Latency p90 (h) | Val event F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| battledim | infra | fixed_threshold | 0.414 | 0.688 | 0.517 | 0.408 | 1.000 | 0.580 | 1.04 | 0.00 | 6.05 | 0.520 |
| battledim | infra | isolation_forest | 0.418 | 0.167 | 0.239 | 0.409 | 1.000 | 0.581 | 1.99 | 7.71 | 23.06 | 0.560 |
| scenarios | infra | fixed_threshold | 0.795 | 0.475 | 0.595 | 0.347 | 1.000 | 0.516 | 0.66 | 1.46 | 19.67 | 0.730 |
| scenarios | infra | isolation_forest | 0.438 | 0.035 | 0.065 | 0.386 | 0.917 | 0.543 | 0.53 | 5.17 | 18.93 | 0.587 |
| scenarios | infra | isolation_forest-joint | 0.308 | 0.058 | 0.098 | 0.389 | 0.944 | 0.551 | 0.70 | 3.96 | 41.45 | 0.510 |
| scenarios | quality | fixed_threshold | 0.125 | 0.005 | 0.009 | 0.118 | 0.028 | 0.045 | 0.04 | 1.08 | 1.08 | 0.165 |
| scenarios | quality | isolation_forest | 0.171 | 0.074 | 0.103 | 0.242 | 0.694 | 0.359 | 0.35 | 0.25 | 0.77 | 0.261 |
| scenarios | quality | isolation_forest-joint | 0.159 | 0.079 | 0.105 | 0.172 | 0.667 | 0.273 | 0.80 | 0.29 | 9.87 | 0.203 |

## Per-event-type recall (test)

| Dataset | Domain | Model | combined | infra_burst | infra_leak | quality_tds_shift | quality_turbidity_surge |
|---|---|---|---|---|---|---|---|
| battledim | infra | fixed_threshold | - | 1.00 (n=1) | 1.00 (n=7) | - | - |
| battledim | infra | isolation_forest | - | 1.00 (n=1) | 1.00 (n=7) | - | - |
| scenarios | infra | fixed_threshold | 1.00 (n=12) | 1.00 (n=12) | 1.00 (n=12) | - | - |
| scenarios | infra | isolation_forest | 0.92 (n=12) | 0.83 (n=12) | 1.00 (n=12) | - | - |
| scenarios | infra | isolation_forest-joint | 1.00 (n=12) | 0.83 (n=12) | 1.00 (n=12) | - | - |
| scenarios | quality | fixed_threshold | 0.00 (n=12) | - | - | 0.00 (n=12) | 0.08 (n=12) |
| scenarios | quality | isolation_forest | 0.83 (n=12) | - | - | 0.75 (n=12) | 0.50 (n=12) |
| scenarios | quality | isolation_forest-joint | 0.92 (n=12) | - | - | 0.58 (n=12) | 0.50 (n=12) |
