"""Text of an alert message: plain, under 600 characters, real values from the fusion output."""
from __future__ import annotations

PREFIX = "[KAMI DEMO - simulated data]"
LIMIT = 600  # the text is always shorter than this


def format_message(alert: dict, node_name: str | None = None, limit: int = LIMIT) -> str:
    """alert: an alert event from the live processor (node_id, category, priority, confidence, explanation, ts)."""
    node = f"{node_name} ({alert['node_id']})" if node_name and node_name != alert["node_id"] else alert["node_id"]
    conf = alert.get("confidence")
    head = [PREFIX, f"Node: {node}",
            f"Category: {alert['category']} | Priority: {alert['priority']} | Confidence: "
            + (f"{conf:.2f}" if isinstance(conf, (int, float)) else "n/a")]
    tail = f"Replay time: {str(alert.get('ts', '')).replace('T', ' ')[:16]}"
    explanation = " ".join(str(alert.get("explanation", "")).split())
    room = limit - 1 - sum(len(x) + 1 for x in head) - 1 - len(tail)  # one newline after each line, strictly under the limit
    if len(explanation) > room:
        explanation = explanation[: max(room - 3, 0)].rstrip() + "..."
    return "\n".join([*head, explanation, tail])
