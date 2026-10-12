# Search for real labelled data (report only)

**Why.** KAMI's infrastructure data are a hydraulic simulation (BattLeDIM) and its quality data are real river records
without event labels (USGS), so the combined method is evaluated on semi-synthetic scenarios. This note records a
second, time-boxed search (about 30 minutes, 2026-10-12) for public, real, labelled sensor time series of leaks,
bursts or water-quality incidents. **Nothing was downloaded or integrated.** Only record pages and metadata were read.

**What would fit.** Measured (not simulated) data from a water supply; flow, pressure, turbidity or conductivity/TDS;
a sampling step of 15 minutes or finer; event labels with start and end; an open licence.

## Candidates

| # | Dataset | Link | Licence | What it contains | Real? | Labels | Fit for KAMI |
|---|---|---|---|---|---|---|---|
| 1 | GECCO Industrial Challenge 2018, "Online Anomaly Detection for Drinking Water Quality" (TH Köln; data from Thüringer Fernwasserversorgung) | https://zenodo.org/records/3884398 (DOI 10.5281/zenodo.3884398) | CC-BY-4.0 (Zenodo metadata) | One CSV of about 11 MB with drinking-water quality measurements of a water utility at one-minute steps. According to the challenge description the variables include temperature, pH, redox potential, conductivity, turbidity, chlorine dioxide and flow rate; to be confirmed on download | Yes: measured at a utility ("this is NOT a simulated scenario" in the EPyT-Flow benchmark notes) | An event flag per row | **Best fit for the quality stream.** Real, labelled, fine-grained, open. Limits: one site, no pressure, the events are quality events only, and conductivity would stand in for TDS. It would test the quality evidence module on real events; it cannot test Combined events |
| 2 | GECCO Industrial Challenge 2019, "Online Event Detection for Drinking Water Quality Control" (same organisers and provider) | https://zenodo.org/records/4304080 (DOI 10.5281/zenodo.4304080) | CC-BY-4.0 | Follow-up with separate train, validation and test files (about 11, 4.5 and 2.6 MB) and a combined file | Yes | Event flag; ready-made splits | **Same fit as 1, with official splits**, which suits a "tune on validation, test once" protocol. Whether 2018 and 2019 overlap in time must be checked before both are used |
| 3 | GECCO Industrial Challenge 2017, "Monitoring of drinking-water quality" | https://zenodo.org/records/3884465 | CC-BY-4.0 | 9 numeric quality features at one-minute steps over about 3 months (about 9.6 MB) | Yes | Binary event flag | Older version of 1; useful only if more data are wanted |
| 4 | Halifax Water DMA data: "Data underlying the research on On-line warning system for pipe burst using Bayesian dynamic linear models" (Henriques da Silva, Schmidt, Duchesne, Fortin St-Gelais, 2022) | https://data.4tu.nl/datasets/b07b9b7a-2065-4607-9d72-8885414c2854 (DOI 10.4121/17169383) | CC0 | Hourly flow (m³/h) and pressure (psi) of a district metered area, 2015 to 2016, with temperature and a workday flag | Yes: a real utility | The record page lists no label file; burst dates may be given in the related paper (not verified) | **Best real candidate for the infrastructure stream, with two gaps:** hourly data (KAMI works on 5-minute steps, so features and models would need to be redefined), and labels that would have to be taken from the paper |
| 5 | Aghashahi, Sela and Banks: leak experiments in a laboratory testbed (Mendeley Data; Data in Brief, 2023) | https://data.mendeley.com/datasets/tbrnp6vrnj and https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10147960/ | open (see the record) | 280 signals from a 47 m PVC test rig: accelerometer, hydrophone and dynamic pressure at 8 to 51.2 kHz, four leak types and no leak, two topologies | Real measurements, but a laboratory rig | Fully labelled | **Does not fit:** short high-frequency recordings for acoustic methods, not SCADA-rate flow and pressure |
| 6 | BattLeDIM (already used) | https://zenodo.org/record/4017658 | CC-BY-4.0 | Flow and pressure of the L-Town network with leak labels | No: hydraulic simulation | Yes | Already the infrastructure source, labelled `semi_synthetic` |
| 7 | LeakDB (KIOS) | https://zenodo.org/records/13985057 | CC-BY-4.0 | 1000 leak scenarios on several networks | No: simulated | Yes | Skipped in Round 2 (13.9 GB, 30-minute steps) |
| 8 | GraphLeak | https://www.sba.org.br/open_journal_systems/index.php/cba/article/view/4655 | not checked | Simulated networks with pressure, flow and volume | No: simulated | Yes | No advantage over BattLeDIM |
| 9 | Babela et al., multisource dataset (Scientific Data, 2026), noted in `PROGRESS.md` | not found | - | - | - | - | **Still not confirmed.** Two searches with the name, the journal and the year returned no such record. It is not cited anywhere in KAMI |
| 10 | Utility data used in published studies (for example SCADA and smart-meter data of Hera S.p.A. in a University of Bologna study) | https://cris.unibo.it/bitstream/11585/1020130/1/Combining%20SCADA%20and%20smart%20meter%20data%20to%20improve%20anomaly%20detection.pdf (paper) | not public | Real anomalies including pipe breaks | Yes | In the study | Not openly released as far as could be seen; would need a request to the authors |

## Conclusions

1. **No single public dataset has real, labelled flow, pressure, turbidity and TDS together.** A real test of the
   Combined category is not possible with public data found here. This stays a limitation to state in the paper.
2. **Quality stream: the GECCO drinking-water datasets (1 and 2) are a realistic next step.** They are real,
   labelled, open (CC-BY-4.0) and small. They would replace the unlabelled river records for an evaluation of the
   quality evidence module on real events. Work needed: a loader, a mapping of conductivity to the TDS input, features
   at one-minute or resampled 5-minute steps, a chronological split, and re-training of the quality module. That is a
   new evaluation round with its own freeze; it must not touch the frozen Round 2 results.
3. **Infrastructure stream: nothing as good.** The Halifax data (4) are real but hourly and without a label file.
4. **The Babela dataset remains unconfirmed** and should not be mentioned in the paper unless a record is found.

## For the user

- Best candidate to consider: **GECCO Industrial Challenge 2019 dataset** (https://zenodo.org/records/4304080), with
  the 2018 set as an alternative. Decision needed before any download: whether a real-data check of the quality
  stream is worth a further round.
- Still worth doing: ask the project guide whether the department or a utility partner has labelled leak or quality
  records. Field data from one real network, even a short period, would be more convincing than any public set above.

## Sources read

- Zenodo record metadata for records 3884398, 4304080 and 3884465 (title, licence, files), 2026-10-12.
- https://data.4tu.nl/datasets/b07b9b7a-2065-4607-9d72-8885414c2854
- https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10147960/ and https://data.mendeley.com/datasets/tbrnp6vrnj
- https://epyt-flow.readthedocs.io/en/latest/epyt_flow.data.benchmarks.html
- https://zenodo.org/record/4017658 and https://zenodo.org/records/13985057
- https://www.sba.org.br/open_journal_systems/index.php/cba/article/view/4655
