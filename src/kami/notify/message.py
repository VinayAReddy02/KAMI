"""Text of an alert message: plain words built from the real values of the assessment, always under 600 characters.

    [KAMI DEMO - simulated data]
    Node: Gandhi Nagar Tank (node-2 · Ward 2)
    Category: Infrastructure | Priority: High
    Confidence: 0.69 (final fused value, not the model score)
    Flow/pressure: unusual for 2 h, started suddenly, 1st episode in 7 days (model score 0.99, suddenness 0.88)
    Action: Check pressure and flow at Gandhi Nagar Tank.
    Replay time: 2018-01-07 16:45

Where the words come from (nothing is invented, see docs/notifications.md):
  "unusual for X"       persistence: how long the stream's model score has stayed at or above 0.5 without a break
  "started suddenly"    suddenness >= SUDDEN_CUTOFF (the score rose by at least half of its range within 15 minutes
                        at some point in the last 2 hours); otherwise "built up gradually"
  "Nth episode in 7 days"  recurrence: separate episodes of that stream in the last 7 days
  "model score"         the calibrated evidence of one stream (p_infra or p_quality)
  "confidence"          the fused value of the reported category (it combines both streams and their history)
The action line is generic for the category and never names a cause.
"""
from __future__ import annotations

from ..live.labels import SEP, node_info

PREFIX = "[KAMI DEMO - simulated data]"
LIMIT = 600  # the text is always shorter than this
SUDDEN_CUTOFF = 0.5
STEP_MIN = 5
STREAMS = {"infra": ("Flow/pressure", "pressure and flow"), "quality": ("Turbidity/TDS", "turbidity and TDS")}
BY_CATEGORY = {"Infrastructure": ("infra",), "Quality": ("quality",), "Combined": ("infra", "quality")}
CONFIDENCE_NOTE = "final fused value, not the model score"


def _duration(steps: float) -> str:
    minutes = int(round(float(steps) * STEP_MIN))
    if minutes <= 0:
        return "unusual now"
    if minutes < 60:
        return f"unusual for {minutes} min"
    hours = minutes / 60
    return f"unusual for {hours:.0f} h" if abs(hours - round(hours)) < 0.05 else f"unusual for {hours:.1f} h"


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _reason(alert: dict, stream: str, detail: int) -> str | None:
    """One line for one stream. detail 2: with model score and suddenness; 1: model score only; 0: words only."""
    t, p = alert.get("temporal") or {}, alert.get(f"p_{stream}")
    try:
        steps, sudden, rec, p = float(t[f"{stream}_persist_steps"]), float(t[f"{stream}_suddenness"]), int(t[f"{stream}_recurrence"]), float(p)
    except (KeyError, TypeError, ValueError):
        return None
    words = [_duration(steps), "started suddenly" if sudden >= SUDDEN_CUTOFF else "built up gradually"]
    if rec >= 1:
        words.append(f"{_ordinal(rec)} episode in 7 days")
    numbers = {2: f" (model score {p:.2f}, suddenness {sudden:.2f})", 1: f" (model score {p:.2f})", 0: ""}[detail]
    return f"{STREAMS[stream][0]}: {', '.join(words)}{numbers}"


def _clip(text: str, room: int) -> str:
    return text if len(text) <= room else text[: max(room - 3, 0)].rstrip() + "..."


def format_message(alert: dict, node_name: str | None = None, limit: int = LIMIT) -> str:
    """alert: an alert event of the live processor (node_id, category, priority, confidence, ts, and either the values
    behind it: p_infra, p_quality, temporal; or only an explanation text, which is then used as it is)."""
    info = node_info(alert["node_id"])  # a node of config/nodes.json: its number and ward go into the Node line (Round 7)
    if node_name is None and info:
        node_name = info["name"]
    name = node_name if node_name and node_name != alert["node_id"] else None
    ref = f"{alert['node_id']}{SEP}Ward {info['ward']}" if info and info["ward"] is not None else alert["node_id"]
    conf = alert.get("confidence")
    conf_line = f"Confidence: {conf:.2f} ({CONFIDENCE_NOTE})" if isinstance(conf, (int, float)) else "Confidence: n/a"
    tail = f"Replay time: {str(alert.get('ts', '')).replace('T', ' ')[:16]}"
    streams = BY_CATEGORY.get(alert["category"], ())

    def build(detail: int, name_room: int) -> list[str] | None:
        shown = _clip(name, name_room) if name else None
        lines = [PREFIX, f"Node: {shown} ({ref})" if shown else f"Node: {ref}",
                 f"Category: {alert['category']} | Priority: {alert['priority']}", conf_line]
        reasons = [_reason(alert, s, detail) for s in streams]
        if not reasons or any(r is None for r in reasons):
            return None
        where = shown or alert["node_id"]
        return [*lines, *reasons, f"Action: Check {', and '.join(STREAMS[s][1] for s in streams)} at {where}.", tail]

    for detail, name_room in ((2, 80), (1, 80), (0, 80), (0, 40), (0, 20)):  # drop bracketed numbers first, then shorten the name
        lines = build(detail, name_room)
        if lines is None:
            break
        if len("\n".join(lines)) < limit:
            return "\n".join(lines)
    # no values to describe (for example the labelled test message): the given explanation, shortened if needed
    head = [PREFIX, f"Node: {_clip(name, 40)} ({ref})" if name else f"Node: {ref}",
            f"Category: {alert['category']} | Priority: {alert['priority']}", conf_line]
    explanation = " ".join(str(alert.get("explanation", "")).split())
    room = limit - 1 - sum(len(x) + 1 for x in head) - 1 - len(tail)  # one newline after each line, strictly under the limit
    return "\n".join([*head, _clip(explanation, room), tail])
