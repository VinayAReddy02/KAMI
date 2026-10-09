# Fusion designs

Two calibrated evidence streams (`p_infra` from flow/pressure, `p_quality` from turbidity/TDS, Step 4) and their causal temporal features (suddenness, persistence, recurrence) are fused into a category (Normal, Infrastructure, Quality, Combined), a priority, a confidence and an explanation. Code: `src/kami/models/fusion.py`; experiments: `python -m kami.eval.run_fusion`.

## F-A: log-odds combination with temporal modifiers
Multinomial logistic regression (class-balanced) over `logit(p_infra)`, `logit(p_quality)` and, per stream, `log1p(persist_steps)`, `persist_frac`, `suddenness`, `log1p(recurrence)`. Category log-odds are a linear combination of the calibrated evidence, with the temporal terms acting as modifiers. Fitted on validation only. The "no temporal" ablation drops the modifiers.

## F-B: Dempster-Shafer with reliability discounting
Frame {N, I, Q, C}. The infrastructure stream gives mass `r_i p_i` to {I, C}, `r_i (1-p_i)` to {N, Q} and `1 - r_i` to the whole frame; the quality stream is symmetric ({Q, C}, {N, I}). Reliability `r = r_min + (1 - r_min)(1 - exp(-persistence/tau))`, raised towards 1 by recurring episodes with rate lambda: short transients are discounted. Dempster's rule combines the sources (no conflict arises with this frame). A stream is reported active when its discounted belief `r * p >= gamma`; the category follows from which streams are active; the confidence is the pignistic probability of that category. `r_min`, `tau`, `lambda`, `gamma` are chosen on validation. The "no temporal" ablation fixes r = 1 and tunes gamma only.

Note: with argmax of the pignistic probability the reliability has almost no effect (the N-versus-I margin is `r(2p-1)(...)`, whose sign depends only on p), which is why the decision uses the discounted belief.

## Priority (rule-based, testable)
Points: +1 Combined, +1 persistence >= 1 h, +1 persistence >= 6 h, +1 intensity (largest active evidence) >= 0.9, +1 at least 2 recurring episodes in 7 days. 0 -> Low (also Normal), 1 -> Medium, 2 -> High, 3 or more -> Critical. Persistence and intensity can only raise priority (unit-tested).

## Explanation
Template text quoting the real values: each active stream's evidence probability, hours above threshold, suddenness, episodes in the last 7 days, plus category, priority and confidence. See `results/fusion/sample_assessments.json`.

## Selection and honest outcome
The design with the best out-of-fold validation macro-F1 on the scenarios is selected (ties go to F-B). Both designs are reported on test, once each. Results: `results/tables/fusion_ablation.md`, `results/tables/confusion_matrices.md`, summary in `results/SUMMARY.md`.
