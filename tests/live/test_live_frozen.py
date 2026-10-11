"""W-1: the live (streaming) path runs the fusion rule frozen in Round 2 and gives the same category as the batch
frozen rule on a fixed validation sample. Validation rows only: no held-out set is read here."""
import json

import numpy as np
import pytest

from kami.eval.data import load_dataset
from kami.eval.final_models import fusion_models
from kami.eval.round2_data import attach_evidence
from kami.live.frozen import FROZEN_CONFIG, FrozenRule
from kami.live.processor import BUF, SIGNALS, LiveProcessor
from kami.models.fusion import CATS

NODE, EVENT, BEFORE, LENGTH = "scn-node-1", "scn-node-1-val-021", 300, 1200  # a validation Combined event and its surroundings


@pytest.fixture(scope="module")
def sample():
    full = load_dataset("scenarios")
    node = full[full.node_id == NODE].sort_values("ts").reset_index(drop=True)
    first = int(np.flatnonzero((node.event_id == EVENT).to_numpy())[0])
    lo = first - BEFORE
    window = node.iloc[lo:lo + LENGTH]
    assert (window.split == "val").all() and (node.iloc[lo - BUF:lo].split == "val").all()
    return node.iloc[lo - BUF:lo], window


def test_live_processor_uses_the_frozen_round2_rule():
    cfg = json.loads(FROZEN_CONFIG.read_text(encoding="utf-8"))
    proc = LiveProcessor()
    assert proc.design == cfg["selected_design"] == "F-B"
    assert proc.fusion.params == tuple(cfg["designs"]["F-B"]["final_params"])
    assert proc.fusion.describe()["label"] == "Fusion F-B, frozen Round 2"


def test_live_category_equals_batch_frozen_rule_on_a_validation_sample(sample):
    history, window = sample
    # batch: stored causal features -> evidence -> temporal features of this sample -> frozen rule (the code of the final run)
    frame = attach_evidence(window, "val").reset_index(drop=True)
    frozen = json.loads(FROZEN_CONFIG.read_text(encoding="utf-8"))
    batch = fusion_models(frozen, frame)[frozen["selected_design"]](frame)
    # live: the same readings one at a time through the streaming processor
    proc = LiveProcessor(rule=FrozenRule())
    proc.prime(NODE, history)
    live = []
    for row in window.itertuples(index=False):
        a = proc.on_reading({"node_id": NODE, "ts": row.ts.isoformat(), **{s: getattr(row, s) for s in SIGNALS}})
        live.append(CATS.index(a["category"]))
    live = np.array(live)
    assert len(set(batch)) >= 3, "the sample must contain several categories, otherwise the comparison is trivial"
    mismatch = np.flatnonzero(live != batch)
    assert len(mismatch) == 0, f"{len(mismatch)} of {len(batch)} rows differ, first at {mismatch[:5]}"
