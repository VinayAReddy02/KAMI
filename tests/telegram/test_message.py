"""Alert wording (PLAN_ROUND5.md M1): plain reasons from the real values, a generic action line, no cause named, under 600 characters."""
import itertools

import pytest

from kami.notify.message import LIMIT, PREFIX, SUDDEN_CUTOFF, format_message

CAUSE_WORDS = ("leak", "burst", "contamin", "pollut", "sewage", "break", "rupture", "caused", "because")


def alert(category="Infrastructure", priority="High", confidence=0.69, node="node-2", infra=(0.99, 24, 0.88, 1), quality=(0.03, 0, 0.0, 0), **over):
    """An alert event with the values behind it. infra / quality = (model score, persistence steps, suddenness, episodes)."""
    a = {"id": 1, "node_id": node, "category": category, "priority": priority, "confidence": confidence, "ts": "2018-01-07T16:45:00",
         "explanation": "Infrastructure anomaly, priority High (confidence 0.69): infrastructure evidence 0.99, above threshold for 2.0 h, "
                        "suddenness 0.88, 1 episode(s) in the last 7 days.",
         "p_infra": infra[0], "p_quality": quality[0],
         "temporal": {"infra_persist_steps": float(infra[1]), "infra_suddenness": infra[2], "infra_persist_frac": 0.3, "infra_recurrence": float(infra[3]),
                      "quality_persist_steps": float(quality[1]), "quality_suddenness": quality[2], "quality_persist_frac": 0.0,
                      "quality_recurrence": float(quality[3])}}
    a.update(over)
    return a


def test_the_first_real_alert_in_the_new_wording():
    """The values of the first alert that was delivered (node-2, 2026-10-12), now in plain words."""
    assert format_message(alert(), "Gandhi Nagar Tank") == "\n".join([
        "[KAMI DEMO - simulated data]",
        "Node: Gandhi Nagar Tank (node-2)",
        "Category: Infrastructure | Priority: High",
        "Confidence: 0.69 (final fused value, not the model score)",
        "Flow/pressure: unusual for 2 h, started suddenly, 1st episode in 7 days (model score 0.99, suddenness 0.88)",
        "Action: Check pressure and flow at Gandhi Nagar Tank.",
        "Replay time: 2018-01-07 16:45"])


def test_message_has_plain_reasons_and_action_line_and_names_no_cause():
    quality = format_message(alert("Quality", "Critical", 0.91, infra=(0.02, 0, 0.0, 0), quality=(0.97, 7, 0.21, 3)), "Katpadi Junction")
    combined = format_message(alert("Combined", "Critical", 0.84, quality=(0.9, 30, 0.6, 2)), "Katpadi Junction")
    infra = format_message(alert(), "Katpadi Junction")
    assert "Turbidity/TDS: unusual for 35 min, built up gradually, 3rd episode in 7 days (model score 0.97, suddenness 0.21)" in quality
    assert "Action: Check turbidity and TDS at Katpadi Junction." in quality and "Flow/pressure" not in quality
    assert "Flow/pressure: unusual for 2 h, started suddenly, 1st episode in 7 days (model score 0.99, suddenness 0.88)" in combined
    assert "Turbidity/TDS: unusual for 2.5 h, started suddenly, 2nd episode in 7 days (model score 0.90, suddenness 0.60)" in combined
    assert "Action: Check pressure and flow, and turbidity and TDS at Katpadi Junction." in combined
    for text in (infra, quality, combined):
        lines = text.split("\n")
        assert lines[0] == PREFIX == "[KAMI DEMO - simulated data]" and lines[-1] == "Replay time: 2018-01-07 16:45"
        assert sum(ln.startswith("Action: Check ") for ln in lines) == 1
        assert "(final fused value, not the model score)" in text  # confidence and the model score are labelled as different things
        assert "above threshold" not in text and "evidence" not in text  # the technical wording is gone
        assert not any(w in text.lower() for w in CAUSE_WORDS), "the message must not name a cause"
        assert len(text) < LIMIT


def test_words_follow_the_numbers():
    def line(**kw):
        return format_message(alert(**kw), "X").split("\n")[4]

    assert SUDDEN_CUTOFF == 0.5
    assert "started suddenly" in line(infra=(0.99, 24, 0.5, 1)) and "built up gradually" in line(infra=(0.99, 24, 0.49, 1))
    assert "unusual for 5 min" in line(infra=(0.99, 1, 0.9, 1)) and "unusual for 55 min" in line(infra=(0.99, 11, 0.9, 1))
    assert "unusual for 1 h," in line(infra=(0.99, 12, 0.9, 1)) and "unusual for 1.8 h" in line(infra=(0.99, 22, 0.9, 1))
    assert "unusual for 32.2 h" in line(infra=(0.99, 386, 0.9, 1)) and "unusual now" in line(infra=(0.99, 0, 0.9, 1))
    for n, word in ((1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (21, "21st"), (112, "112th")):
        assert f"{word} episode in 7 days" in line(infra=(0.99, 24, 0.9, n))
    assert "episode" not in line(infra=(0.99, 24, 0.9, 0))


def test_longest_message_stays_under_600_characters():
    worst = alert("Combined", "Critical", 1.0, node="node-123456", infra=(1.0, 99999, 0.99, 123), quality=(1.0, 88888, 0.99, 112))
    for n in itertools.chain(range(0, 130), (200, 500, 5000)):
        text = format_message(worst, "W" * n if n else None)
        lines = text.split("\n")
        assert len(text) < 600, (n, len(text))
        assert lines[0] == PREFIX and lines[-1] == "Replay time: 2018-01-07 16:45"
        assert sum(ln.startswith("Flow/pressure: unusual for 8333.2 h, started suddenly, 123rd episode in 7 days") for ln in lines) == 1
        assert sum(ln.startswith("Turbidity/TDS: unusual for 7407.3 h") for ln in lines) == 1
        assert sum(ln.startswith("Action: Check pressure and flow, and turbidity and TDS at ") for ln in lines) == 1
    full = format_message(worst, "W" * 60)  # a long but realistic name still gets every number
    assert "(model score 1.00, suddenness 0.99)" in full and "W" * 60 in full
    assert "..." in format_message(worst, "W" * 5000)  # only an absurd name is shortened


def test_without_values_the_given_explanation_is_used():
    """The labelled test message (scripts/send_test_alert.py) has no assessment behind it."""
    a = {"id": 0, "node_id": "test", "category": "TEST", "priority": "High", "confidence": None, "ts": "2026-10-12T10:00:00",
         "explanation": "TEST MESSAGE from scripts/send_test_alert.py. This is not an alert: no sensor data and no model produced it."}
    text = format_message(a, "TEST (no real node)")
    assert text.split("\n") == [PREFIX, "Node: TEST (no real node) (test)", "Category: TEST | Priority: High", "Confidence: n/a",
                                a["explanation"], "Replay time: 2026-10-12 10:00"]
    long = format_message({**a, "explanation": "x" * 5000}, "N" * 300)
    assert len(long) < 600 and long.startswith(PREFIX) and long.endswith("Replay time: 2026-10-12 10:00") and "..." in long
    partial = alert(temporal={"infra_persist_steps": 3.0})  # incomplete values: fall back rather than guess
    assert "above threshold for 2.0 h" in format_message(partial, "X") and "Action:" not in format_message(partial, "X")


@pytest.mark.parametrize("category", ["Infrastructure", "Quality", "Combined"])
def test_node_id_is_used_when_there_is_no_name(category):
    text = format_message(alert(category, quality=(0.9, 30, 0.6, 2)), None)
    assert "Node: node-2\n" in text and text.split("\n")[-2].endswith(" at node-2.")
