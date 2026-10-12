"""Evaluation helpers of the citizen interface (Round 6, C6). Separate from the frozen anomaly evaluation.

The questions are authored (data/citizen/eval_questions.jsonl), the schedule is fictional, and the truth of a question
is the structured lookup with the question's gold ward and day at a fixed replay time, with one planted alert.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

import numpy as np

from .answer import Reply, _claims
from .data import ScheduleService
from .settings import DATA_DIR
from .tts import number_words

QUESTIONS = DATA_DIR / "eval_questions.jsonl"
EVAL_NOW = datetime(2018, 1, 7, 11, 0)  # fixed replay time of the evaluation
EVAL_ALERTS = {"node-3": {"category": "Infrastructure", "priority": "High", "status": "ok"}}  # one planted open alert (ward 3)
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def eval_world() -> tuple[ScheduleService, callable]:
    """The schedule at the fixed time with the planted alert, and the node-state function that goes with it."""
    def node_state(node_id: str) -> dict:
        return EVAL_ALERTS.get(node_id, {"category": "Normal", "priority": "Low", "status": "ok"})

    return ScheduleService(clock=lambda: EVAL_NOW, open_alert=lambda node_id: EVAL_ALERTS.get(node_id)), node_state


def load_questions(split: str | None = None) -> list[dict]:
    rows = [json.loads(ln) for ln in QUESTIONS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [r for r in rows if split is None or r["split"] == split]


def truth(q: dict, schedule: ScheduleService, node_state) -> dict:
    """What a correct answer must contain, from the gold slots of the question."""
    e = q["expect"]
    if q["intent"] == "schedule":
        ds = schedule.deliveries(e["ward"], e["day"]) if e["day"] is not None else [d for d in [schedule.next_delivery(e["ward"])] if d]
        if not ds:
            return {"kind": "no_info"}
        return {"kind": "schedule", "times": sorted({t for d in ds for t in d.expected.split("-")}),
                "times_allowed": sorted({t for d in ds for t in (d.expected + "-" + d.slot).split("-")}), "tankers": sorted({int(d.tanker_id.split("-")[1]) for d in ds}),
                "statuses": sorted({d.status for d in ds if d.status in ("delivered", "delayed")}), "alert_note": any(d.alert_note for d in ds)}
    if q["intent"] == "ward_status":
        s = node_state(schedule.wards[e["ward"]].node_id)
        return {"kind": "ward_status", "category": s["category"], "priority": s["priority"]}
    if q["intent"] == "faq":
        return {"kind": "faq", "notice": e["notice"], "must": e["must"]}
    return {"kind": "no_info"}


def judge(q: dict, reply: Reply, t: dict) -> dict:
    """slot_ok: intent, ward and day were understood. answer_ok: the English answer states the true facts and no wrong
    time or tanker. final_ok: the reply in the citizen's language still has the times, tanker ids and numbers.
    no_info_ok: 'no information' was said exactly when there is nothing to say."""
    e = q["expect"]
    if q["intent"] == "schedule":
        slot_ok = reply.intent == "schedule" and reply.ward == e["ward"] and reply.day == e["day"]
    elif q["intent"] == "ward_status":
        slot_ok = reply.intent == "ward_status" and reply.ward == e["ward"]
    elif q["intent"] == "faq":
        slot_ok = reply.kind == "faq" and bool(reply.records) and _notice_id(reply) == e["notice"]
    else:
        slot_ok = reply.kind in ("no_info", "ask_ward")
    said, low = _claims(reply.text_en), reply.text_en.lower()
    if t["kind"] == "no_info":
        answer_ok = reply.no_info
    elif t["kind"] == "schedule":
        answer_ok = (not reply.no_info and set(t["times"]) <= said["time"] <= set(t["times_allowed"]) and said["tanker"] <= set(t["tankers"])
                     and all(s in said["status"] for s in t["statuses"]) and (not t["alert_note"] or "delay" in low))
    elif t["kind"] == "ward_status":
        answer_ok = ("no anomaly" in low or "normal" in low) if t["category"] == "Normal" else (t["category"].lower() in low and t["priority"].lower() in low)
    else:
        answer_ok = not reply.no_info and all(m.lower() in low or _time_said(m, said) for m in t["must"])
    final = reply.text.translate(_DIGITS)
    digits = {int(x) for x in re.findall(r"\d+", final)}
    if t["kind"] == "schedule":
        final_ok = answer_ok and all(int(x[:2]) in digits for x in t["times"]) and (reply.lang == "en" or set(t["tankers"]) <= digits)
    elif t["kind"] == "faq" and reply.lang == "hi":
        final_ok = answer_ok and not reply.translation_fallback and bool(re.search(r"[ऀ-ॿ]", final))
    else:
        final_ok = answer_ok
    return {"slot_ok": bool(slot_ok), "answer_ok": bool(answer_ok), "final_ok": bool(final_ok), "no_info_ok": bool(reply.no_info == (t["kind"] == "no_info"))}


def _time_said(must: str, said: dict) -> bool:
    return bool(re.fullmatch(r"\d{2}:\d{2}", must)) and must in said["time"]


def _notice_id(reply: Reply) -> str | None:
    from .data import load_notices

    title = reply.records[0].get("notice") if reply.records else None
    return next((n["id"] for n in load_notices() if n["title"] == title), None)


# ---------------------------------------------------------------- word error rate
def words(text: str, lang: str, normalise: bool = True) -> list[str]:
    """Words for scoring. normalise=True also writes digits as words and removes spelling variants that sound the same
    (nukta, chandrabindu/anusvara), so 'वार्ड 4' and 'वार्ड चार' count as equal."""
    t = str(text).translate(_DIGITS).lower()
    if normalise:
        t = re.sub(r"\d+", lambda m: " " + number_words(int(m[0]), lang) + " " if len(m[0]) <= 5 else m[0], t)
        t = t.replace("़", "").replace("ँ", "ं").replace("-", " ")
    return re.sub(r"[^\wऀ-ॿ\s]", " ", t, flags=re.UNICODE).split()


def wer(ref: list[str], hyp: list[str]) -> float:
    """Word error rate: word-level edit distance divided by the number of reference words."""
    if not ref:
        return 0.0 if not hyp else 1.0
    d = np.arange(len(hyp) + 1)
    for i, r in enumerate(ref, start=1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, start=1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
            prev, d[j] = d[j], cur
    return float(d[len(hyp)]) / len(ref)


def corpus_wer(pairs: list[tuple[list[str], list[str]]]) -> float:
    """Total errors over total reference words (not the mean of per-sentence rates)."""
    n = sum(len(r) for r, _ in pairs)
    return float(sum(wer(r, h) * len(r) for r, h in pairs) / n) if n else 0.0


def pct(xs: list[float], q: float) -> float | None:
    return round(float(np.percentile(xs, q)), 1) if xs else None
