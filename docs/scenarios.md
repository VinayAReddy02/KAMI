# Scenario generator and event labels

Everything here is `semi_synthetic`. Code: `src/kami/simulator/scenarios.py`; build: `python scripts/build_datasets.py` (seed 42, 4 events per type per split per node).

## Backgrounds
- **scn-node-1..3**: pressure = mean of every third BattLeDIM pressure sensor, flow = one BattLeDIM flow sensor (PUMP_1, p227, p235), turbidity and TDS (0.64 x conductance) = real USGS stations 01654000, 01646305, 01654500 (2021-2022) shifted back 3 years onto 2018-2019. Time grid 5 min; USGS 15-min values are held for at most 20 steps (~90 min), longer gaps stay NaN and the row has `valid = False`.
- Limitation: BattLeDIM background contains its own simulated leaks (always at least one active). They are unlabelled in scenarios and make the background drift (mean pressure falls ~1 m by late 2019). Nodes pair simulated infrastructure data with real river quality data, so the nodes are not field measurements from one place.

## Amplitudes
Infrastructure amplitudes are multiples of the day-to-day noise sigma (robust std of x_t - x_{t-24h}, divided by sqrt(2)), measured on the **train** split only.

| Type | Rule | Physical rationale |
|---|---|---|
| `infra_leak` | pressure falls by `dp` = U(3,8) sigma_p and flow rises by `df` = U(3,8) sigma_f, linear ramp over U(6,36) h, held for U(2,5) days, 1 h recovery (repair) | A growing leak adds outflow, so the pump delivers more and head loss lowers pressure. Incipient leaks grow slowly. |
| `infra_burst` | same effect, amplitude U(5,12) sigma, ramp of 1-3 steps (5-15 min), duration U(0.5,2) days | A burst opens suddenly and is larger. |
| `quality_turbidity_surge` | turbidity multiplied by exp(delta * g), delta U(1.0,2.5) (x2.7 to x12), rise over 15-60 min then exponential decay with tau U(2,8) h (label while g >= 0.05) | Sediment resuspension or ingress gives a sharp rise and slow wash-out; turbidity is multiplicative and heavy-tailed so the effect is in log space. |
| `quality_tds_shift` | TDS multiplied by 1 + rho * g, rho U(0.2,0.6), ramp U(0.5,3) h, held U(0.25,2) days, 1 h recovery | Salt or industrial intrusion or a source switch moves conductance in a persistent step. |
| `combined` | an `infra_leak` or `infra_burst` plus a turbidity surge (always) and a TDS shift (50%); quality onset is U(-1,+3) h from the infra onset | A main break disturbs sediment and can mix in other water, so both evidence streams move together. |

Labels per step: `infra_flag`, `quality_flag` (True while that component acts), `event_id`, `event_type` (`normal` otherwise). Events are placed at random without overlap (12 h gap), at least 2 days from split edges, only where the background is valid for 6 h before and after.

## BattLeDIM event labels (real labels, simulated data)
`battledim_network` = one network-level series: flow = PUMP_1, pressure = mean of the 33 sensors. Each leak gets a window starting at the first time its leak flow reaches 50% of its own peak and lasting until it is fixed or 7 days. Leaks with fewer than 1 labelled day are dropped. Abrupt leaks map to `infra_burst`, incipient ones to `infra_leak`. Concurrent older leaks are background (the label means *onset of a new leak*); the 24 h after a window ends is `ambiguous` and excluded from scoring.
