"""The fusion rule the live demo runs: the design and parameters frozen in Round 2.

`results/fusion/frozen_config.json` is only READ here. The decision code is the same class the batch evaluation used
(`eval.fusion_tune`), so the live category equals the batch frozen rule on the same evidence (tested in
tests/whatsapp/test_live_frozen.py). This is a deployment change: nothing is tuned, fitted or evaluated here.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..eval.fusion_tune import FusionBDesign, VotingDesign
from ..models.fusion import dempster_shafer, reliability

ROOT = Path(__file__).resolve().parents[3]
FROZEN_CONFIG = ROOT / "results" / "fusion" / "frozen_config.json"
# designs that need no fitted model; F-A would need its regression refitted on the validation frame
_DESIGNS = {"F-B": lambda: FusionBDesign(True), "F-B (no temporal)": lambda: FusionBDesign(False),
            "threshold voting (no fusion)": lambda: VotingDesign()}


class FrozenRule:
    """`predict` gives the category index per row (0 N, 1 I, 2 Q, 3 C), `predict_proba` the pignistic probabilities."""

    def __init__(self, path: Path = FROZEN_CONFIG):
        cfg = json.loads(Path(path).read_text(encoding="utf-8"))
        self.design_name = cfg["selected_design"]
        if self.design_name not in _DESIGNS:
            raise NotImplementedError(f"live deployment of the frozen design {self.design_name!r} is not implemented")
        self.params = tuple(cfg["designs"][self.design_name]["final_params"])
        self.design = _DESIGNS[self.design_name]()
        self.frozen_commit = cfg["git_commit"]
        self.label = f"Fusion {self.design_name}, frozen Round 2"

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return self.design.decide(df, self.params)

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if self.design.temporal:
            rm, tp, lam = self.params[:3]
            ri = reliability(df["infra_persist_steps"], df["infra_recurrence"], rm, tp, lam)
            rq = reliability(df["quality_persist_steps"], df["quality_recurrence"], rm, tp, lam)
        else:
            ri = rq = np.ones(len(df))
        return dempster_shafer(df["p_infra"].to_numpy(), df["p_quality"].to_numpy(), ri, rq)

    def describe(self) -> dict:
        names = ("r_min", "tau_p", "lambda", "gamma_infra", "gamma_quality") if len(self.params) == 5 else ("theta_infra", "theta_quality")
        return {"label": self.label, "design": self.design_name, "params": dict(zip(names, self.params)),
                "frozen_commit": self.frozen_commit[:7], "source": "results/fusion/frozen_config.json"}
