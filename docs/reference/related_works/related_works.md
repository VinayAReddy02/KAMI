# Related works and reference index

This file lists every work and data source referred to so far. Entries marked **(verify)** have not been checked yet. Step 0 of the plan is to confirm access, licence, variables and labels before any dataset is relied on.

## A. Works cited in the first-phase report

1. M. N. Kanyama, F. Bhunu Shava, A. M. Gamundani, A. Hartmann. "Machine learning applications for anomaly detection in Smart Water Metering Networks: A systematic review." *Physics and Chemistry of the Earth*, vol. 134, 2024, Art. 103558. doi: 10.1016/j.pce.2024.103558
2. J. Babela, M. Munk, D. Munkova. "A multisource dataset for anomaly detection and fault prediction in urban water distribution networks." *Scientific Data*, vol. 13, Art. 901, 2026. doi: 10.1038/s41597-026-07203-5 **(verify: confirm the dataset exists, is downloadable, and which variables and labels it has)**
3. Z. Li, W. Ma, D. Zhong, J. Ma, Q. Zhang, Y. Yuan, X. Liu, X. Wang, K. Zou. "Applications of machine learning in drinking water quality management: A critical review on water distribution system." *Journal of Cleaner Production*, vol. 481, Art. 144171, 2024. doi: 10.1016/j.jclepro.2024.144171

## B. Methods used as baselines

4. F. T. Liu, K. M. Ting, Z.-H. Zhou. "Isolation forest." *Proc. 8th IEEE International Conference on Data Mining (ICDM)*, 2008, pp. 413-422. doi: 10.1109/ICDM.2008.17
5. B. Schölkopf, J. C. Platt, J. Shawe-Taylor, A. J. Smola, R. C. Williamson. "Estimating the support of a high-dimensional distribution." *Neural Computation*, vol. 13, no. 7, 2001, pp. 1443-1471.

## C. The senior's project (reference only)

6. "Water Access Navigator: An AI-Driven Multilingual Chatbot for Accessible Water Information Dissemination in India." Senior's project paper. File: `senior_project/AI_water_prj.docx`
   - Source code: kept outside this repo at `D:\GYATT\5th sem\AI\Senior\Water-Access-Navigator`. Read-only reference. Public repo: github.com/saket-thota/Water-Access-Navigator. No licence file was seen.

## D. Paper format references

7. ACM SIG proceedings template. File: `paper_format/Template_report.docx`
8. D. Baradari, N. Kosmyna, O. Petrov, R. Kaplun, P. Maes. "NeuroChat: A Neuroadaptive AI Chatbot for Customizing Learning Experiences." arXiv:2503.07599, 2025. Used only as the model for paper structure and flow. File: `paper_format/Paper_content_sample_NeuroChat.pdf`

## E. Candidate public datasets (all to verify in step 0)

| Candidate | What it may provide | What to check |
|---|---|---|
| BattLeDIM (Battle of the Leakage Detection and Isolation Methods) | Water-network pressure and flow time series with leak events | Download location, licence, which sensors, how leaks are labelled |
| LeakDB | Simulated leakage scenarios for water distribution networks | Variables, size, labels, licence |
| BATADAL (Battle of the Attack Detection Algorithms) | Water-network SCADA data with labelled abnormal periods | Variables (levels, flows, pressures), labels, licence |
| USGS National Water Information System continuous water-quality records | Real turbidity and specific-conductance time series (conductance can proxy TDS) | Station choice, parameters available, sampling interval, terms of use |
| Babela et al. multisource dataset (item 2) | Flow and pressure with confirmed leaks | See item 2 |

None of these has synchronised flow, pressure, turbidity and TDS together. This is why the fusion stage will be evaluated on semi-synthetic scenarios built by injecting events into real background series, and why those scenarios must be labelled as such everywhere they appear.

## F. Project documents (in this folder)

- `project/KAMI_Project_Abstract_Clean_1.pdf`: the original broad abstract.
- `project/KAMI_Concise_Project_Report.docx`: the first-phase report.
- `faculty/Faculty_feedback.txt`: the methodology feedback.
