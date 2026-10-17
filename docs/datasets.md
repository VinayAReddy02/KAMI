# Datasets

Checked 2026-10-10. Status: selected, rejected, unreachable, not-confirmed.

| Name | Domain | Status | Notes |
|---|---|---|---|
| BattLeDIM 2020 (Zenodo 4017659) | infrastructure | **selected (infrastructure)** | CC-BY-4.0. 33 pressure + 3 flow sensors, 5-min, 2018-2019, exact leak start/end per pipe. Output of a hydraulic simulation of the L-Town model, so treated as `semi_synthetic` (simulated), not field data. |
| USGS NWIS continuous, turbidity 63680 + specific conductance 00095 | quality | **selected (quality)** | Public domain. Stations 01654000, 01646305, 01654500 (Fairfax Co., VA), 2021-2022, 15-min, ~67-69k rows each. Real measurements, no event labels. Conductance used as TDS proxy. Streams, not a drinking-water network. |
| GECCO Industrial Challenge 2019 (Zenodo 4304080) | quality | **selected (Round 7, real-data test only)** | CC-BY-4.0. Real drinking-water data of a German waterworks, 1-min, Jul to Nov 2017, turbidity (FNU), conductivity (S/m), pH, SAC; provider-labelled events. Used only for the separate real-data test of the quality stream (`docs/gecco.md`); never mixed into the semi-synthetic results. Labelled `real`. |
| LeakDB (KIOS, GitHub) | infrastructure | rejected (not needed) | Reachable (HTTP 200). Also simulated; BattLeDIM already covers the need. Can be revisited. |
| BATADAL | infrastructure/cyber | rejected | Reachable. Focus is cyber-attacks on a simulated network; weaker fit. |
| Babela et al. multisource dataset (Sci. Data 2026) | infrastructure | not-confirmed | Existence and URL could not be confirmed from a quick search; not used. Revisit. |

Both selected infrastructure data are simulated (BattLeDIM) and quality data are real but unlabelled, so
**no real labelled infrastructure data** is used. Added to *Needs user* in PROGRESS.md.
