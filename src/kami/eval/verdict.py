"""The frozen rule that decides "does the selected fusion design beat threshold voting?" (freeze.VERDICT_RULE).

Paired bootstrap: the same resampled events and days are applied to both models, and the verdict is read from the
95% interval of the difference in event-counted F1 (the objective that was tuned: each detected event counts once). The rule lives in hashed code
and is recorded in the frozen configuration so it cannot be chosen after the test numbers are known.
"""
from __future__ import annotations

from .bootstrap import paired_diff

VOTE = "threshold voting (no fusion)"


def decide(sel_metrics: dict, vote_metrics: dict, sel_reps: dict, vote_reps: dict, cap: float) -> dict:
    paired = paired_diff(sel_reps, vote_reps)
    lo, hi = paired["f1_event_counted"]["ci95"]
    sel_within = bool(sel_metrics["event"]["fa_per_day"] <= cap)
    vote_within = bool(vote_metrics["event"]["fa_per_day"] <= cap)
    if lo > 0 and sel_within:
        outcome = "beats"
    elif lo > 0:
        outcome = "higher_f1_but_above_cap"
    elif hi < 0:
        outcome = "worse"
    else:
        outcome = "no_detectable_difference"
    point = {k: sel_metrics["event"][k] - vote_metrics["event"][k]
             for k in ("f1", "f1_event_counted", "precision", "recall", "fa_per_day")}
    point["category_accuracy"] = sel_metrics["category_accuracy_event"] - vote_metrics["category_accuracy_event"]
    return {"outcome": outcome, "difference_selected_minus_voting": point, "paired_ci95": paired,
            "selected_within_cap": sel_within, "voting_within_cap": vote_within, "cap": cap}
