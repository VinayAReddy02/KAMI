# GECCO Industrial Challenge 2019: drinking-water quality (real, labelled)
- Record: https://zenodo.org/records/4304080 , DOI 10.5281/zenodo.4304080 (published 2019-02-01)
- Title: "GECCO Industrial Challenge 2019 Dataset: A water quality dataset for the 'Internet of Things: Online Event Detection for Drinking Water Quality Control' competition at the Genetic and Evolutionary Computation Conference 2019, Prague, Czech Republic."
- Creators: Steffen Moritz, Frederik Rehbach, Thomas Bartz-Beielstein (TH Köln). Data provider: Thüringer Fernwasserversorgung (stations near the outflow of a waterworks, Germany).
- Licence: CC-BY-4.0 (Zenodo metadata `license.id = cc-by-4.0`). Cite: Moritz S., Rehbach F., Bartz-Beielstein T. (2019). GECCO Industrial Challenge 2019 Dataset. Zenodo. https://doi.org/10.5281/zenodo.4304080
- Downloaded: 2026-10-17 (UTC) from the Zenodo API (`/api/records/4304080/files/<name>/content`) for Round 7 Part G (download approved by the user in PLAN_ROUND7.md). All MD5 sums matched the Zenodo record.
- Data kind: **real** sensor measurements with event labels set by the provider/organisers (`Event`, boolean, one row per minute). Not produced by KAMI's scenario generator.

## Files (SHA-256)
| File | Bytes | SHA-256 | Content |
|---|---|---|---|
| 1_gecco2019_water_quality.csv | 10787236 | 05bbe6dea804b6fc6b2bf8ecc35f37c404ff3ae3503c47cf69301edf61c8b4b9 | original training file (identical to 7) |
| 2_CallForParticipation_GECCO_Industrial_Challenge_2019.pdf | 249186 | b4c2ed665a2cfe2ba2b8b0849f283faeda3170521fb0f288483394b6011db7ef | call for participation |
| 3_Rules_GECCO_Industrial_Challenge_2019.pdf | 904710 | 8f725f89137db6350eaaa360340cb9c4a61bf69ffec354ea3be338ddbdb52e49 | rules, column units, F1 metric |
| 4_ResourcePackage_GECCO_Industrial_Challenge_2019.zip | 3042029 | 01e9f2a60594a816b6f78f1c5078dd755edcc9ee73052bdb5b8db294b15dbf78 | R framework incl. `f1score.R` |
| 5_gecco2019_all_water_quality.csv | 17905404 | f6d77b94d474cc398c5d3f5d5b0814d02a8ea35dd17fd8cb34508cdf310ca378 | train + valid + test merged |
| 6_gecco2019_test_water_quality.csv | 2621311 | ad509d0c1c656d3e48dc4e52011da5232d292997e6f7ce08eedd5f6194e3369f | 2017-11-08 00:30 to 2017-11-29 23:59 |
| 7_gecco2019_train_water_quality.csv | 10787236 | 05bbe6dea804b6fc6b2bf8ecc35f37c404ff3ae3503c47cf69301edf61c8b4b9 | 2017-07-01 00:00 to 2017-09-30 23:59 |
| 8_gecco2019_valid_water_qulity.csv | 4496965 | d451142a969f5972278cbfa53d840b04805ab683b81cad092bda30820ec2e424 | 2017-10-01 00:00 to 2017-11-08 00:29 (file name misspelt in the record) |

The CSV and PDF files are git-ignored (data/raw); only this file is committed.

## Inspection (G0, 2026-10-17; no statistic of the test file's labels was computed)
- Columns: `Unnamed: 0` (row index), `Time` (yyyy-mm-dd HH:MM:SS), `Tp` °C, `pH`, `Cond` electric conductivity in **S/m**, `Turb` turbidity in **FNU**, `SAC` spectral absorption coefficient 1/m, `PFM` pulse-frequency modulation Hz (operational), `Event` boolean. Units from the rules PDF, Table 1.
- One row per minute, no gaps in the time index, monotonic, in all three files. Train 132 480 rows (92 days), valid 54 750 rows (38 days), test 31 650 rows (22 days); they follow each other in time (train < valid < test).
- Missing values: train about 200 per column, valid about 2 240 per column (a gap), test about 55 per column. A few rows have Tp, pH, Cond, Turb and SAC all exactly 0 (2 in train, 1 in valid): a sensor-panel dropout.
- Typical levels (train): turbidity median 0.128 FNU (99.9 % quantile 0.156, max 1.78); conductivity median 0.0211 S/m = 211 µS/cm.
- Labels on the **train file only**: 0.16 % of the minutes are events, in 13 separate event runs. Per the rules, events are changes of the quality indicators pH, conductivity, turbidity and SAC; temperature and PFM are operational and not events themselves.
- Competition metric (rules section 2.4 and `f1score.R`): point-wise F1 on the 1-minute rows (TP, FP, FN counted per minute).
- Naming: the rules say the leaderboard used a "validation" set and the final ranking a third "testing" set; the Zenodo description says the opposite (test = leaderboard, valid = end results). KAMI does not depend on this: the split is by time (see docs/gecco_protocol.md).
