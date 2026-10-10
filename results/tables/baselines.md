# Baseline results (test split, evaluated once per model)

Tuned on the validation split only. `battledim`: simulated hydraulics with leak labels; `scenarios`: semi-synthetic events on real/simulated background. Reported separately. Latency in hours (n/a = nothing detected).

| Dataset | Domain | Model | Point P | Point R | Point F1 | Event P | Event R | Event F1 | False alarms/day | Latency med (h) | Latency p90 (h) | Val event F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| battledim | infra | fixed_threshold | 0.667 | 0.006 | 0.012 | 0.569 | 0.750 | 0.647 | 0.26 | 51.75 | 125.58 | 0.367 |
| battledim | infra | isolation_forest | 0.409 | 0.017 | 0.032 | 0.393 | 1.000 | 0.564 | 0.81 | 32.38 | 52.65 | 0.528 |
| battledim | infra | ocsvm | 0.444 | 0.005 | 0.011 | 0.406 | 1.000 | 0.578 | 0.68 | 32.38 | 66.81 | 0.517 |
| scenarios | infra | fixed_threshold | 0.999 | 0.160 | 0.276 | 0.968 | 0.806 | 0.879 | 0.01 | 6.75 | 23.52 | 0.531 |
| scenarios | infra | isolation_forest | 0.438 | 0.035 | 0.065 | 0.386 | 0.917 | 0.543 | 0.53 | 5.17 | 18.93 | 0.587 |
| scenarios | infra | isolation_forest-joint | 0.521 | 0.017 | 0.034 | 0.532 | 0.722 | 0.613 | 0.15 | 8.62 | 25.79 | 0.530 |
| scenarios | infra | ocsvm | 0.600 | 0.067 | 0.121 | 0.407 | 0.972 | 0.574 | 0.40 | 3.92 | 22.20 | 0.585 |
| scenarios | quality | fixed_threshold | 0.125 | 0.005 | 0.009 | 0.118 | 0.028 | 0.045 | 0.04 | 1.08 | 1.08 | 0.165 |
| scenarios | quality | isolation_forest | 0.197 | 0.004 | 0.009 | 0.167 | 0.028 | 0.048 | 0.03 | 1.08 | 1.08 | 0.171 |
| scenarios | quality | isolation_forest-joint | 0.180 | 0.016 | 0.029 | 0.138 | 0.222 | 0.170 | 0.24 | 5.12 | 10.38 | 0.139 |
| scenarios | quality | ocsvm | 0.141 | 0.026 | 0.043 | 0.173 | 0.528 | 0.261 | 0.36 | 0.33 | 7.57 | 0.225 |

## Per-event-type recall (test)

| Dataset | Domain | Model | combined | infra_burst | infra_leak | quality_tds_shift | quality_turbidity_surge |
|---|---|---|---|---|---|---|---|
| battledim | infra | fixed_threshold | - | 1.00 (n=1) | 0.71 (n=7) | - | - |
| battledim | infra | isolation_forest | - | 1.00 (n=1) | 1.00 (n=7) | - | - |
| battledim | infra | ocsvm | - | 1.00 (n=1) | 1.00 (n=7) | - | - |
| scenarios | infra | fixed_threshold | 0.83 (n=12) | 0.83 (n=12) | 0.75 (n=12) | - | - |
| scenarios | infra | isolation_forest | 0.92 (n=12) | 0.83 (n=12) | 1.00 (n=12) | - | - |
| scenarios | infra | isolation_forest-joint | 0.67 (n=12) | 0.75 (n=12) | 0.75 (n=12) | - | - |
| scenarios | infra | ocsvm | 0.92 (n=12) | 1.00 (n=12) | 1.00 (n=12) | - | - |
| scenarios | quality | fixed_threshold | 0.00 (n=12) | - | - | 0.00 (n=12) | 0.08 (n=12) |
| scenarios | quality | isolation_forest | 0.00 (n=12) | - | - | 0.00 (n=12) | 0.08 (n=12) |
| scenarios | quality | isolation_forest-joint | 0.50 (n=12) | - | - | 0.08 (n=12) | 0.08 (n=12) |
| scenarios | quality | ocsvm | 0.67 (n=12) | - | - | 0.50 (n=12) | 0.42 (n=12) |
