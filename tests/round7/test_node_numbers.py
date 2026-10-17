"""Round 7, N1: the node number and ward appear everywhere a node is named (labels, API, alert message, citizen bot)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kami.api.app import _numbered, create_app
from kami.citizen.answer import guard, numbers_survive, understand
from kami.citizen.bot import HELP, ticket_reply
from kami.citizen.data import load_wards
from kami.ingest.bus import InProcessBus
from kami.live.labels import node_fields, node_label, node_short, ward_label
from kami.live.system import build_live
from kami.notify.message import LIMIT, PREFIX, format_message
from kami.runtime import Stack
from kami.store import SqliteStore

from ..citizen.helpers import FakeOllama, FakeTranslator, answerer

ROOT = Path(__file__).resolve().parents[2]
NODES = json.loads((ROOT / "config" / "nodes.json").read_text(encoding="utf-8"))["nodes"]
W = load_wards()
Q4 = "When will the water tanker reach Ward 4?"


# ------------------------------------------------------------------ one formatter
def test_labels_come_from_the_node_and_ward_files():
    wards = {w.node_id: w for w in W}
    for n in NODES:
        w = wards[n["id"]]
        assert node_label(n["id"]) == f"{n['name']} ({n['id']} · Ward {w.number})"
        assert node_short(n["id"]) == f"{w.number} · {w.name_en}"
        assert ward_label(w.number) == ward_label(w) == f"Ward {w.number} ({w.name_en}, sensor point {n['id']})"
        assert ward_label(w, hi=True) == f"वार्ड {w.number} ({w.name_hi}, सेंसर पॉइंट {n['id']})"
    assert node_label("node-4") == "Bagayam Booster (node-4 · Ward 4)" and node_short("node-4") == "4 · Bagayam"
    assert node_label("node-99") == "node-99" and node_short("node-99") == "node-99" and ward_label(99) == "Ward 99"


# ------------------------------------------------------------------ API: additive fields
def test_network_nodes_carry_number_ward_and_labels():
    stack = Stack.create(mode="fallback", store=SqliteStore(":memory:"), bus=InProcessBus())
    app = create_app(stack)
    build_live(stack, speed=0)
    with TestClient(app) as c:
        nodes = c.get("/network").json()["nodes"]
    assert len(nodes) == 8
    for n in nodes:
        assert {"id", "name", "lat", "lon", "latest"} <= set(n)  # the existing fields are unchanged
        assert (n["number"], n["ward"], n["label"], n["short"]) == (int(n["id"].split("-")[1]), int(n["id"].split("-")[1]), node_label(n["id"]), node_short(n["id"]))


def test_alerts_state_and_tickets_get_node_number_and_ward():
    alert = {"id": 3, "node_id": "node-4", "category": "Infrastructure", "priority": "High"}
    out = _numbered(alert)
    assert {k: out[k] for k in alert} == alert  # nothing existing changes
    assert (out["node_number"], out["ward"], out["node_label"], out["node_short"]) == (4, 4, "Bagayam Booster (node-4 · Ward 4)", "4 · Bagayam")
    assert _numbered({"nearest_node_id": "node-2"}, "nearest_node_id")["node_label"] == "Gandhi Nagar Tank (node-2 · Ward 2)"
    assert _numbered({"node_id": "x"})["node_number"] is None and node_fields(None)["label"] is None


# ------------------------------------------------------------------ Telegram alert message
@pytest.mark.parametrize("node", [n["id"] for n in NODES])
@pytest.mark.parametrize("category", ["Infrastructure", "Quality", "Combined"])
def test_alert_message_names_the_node_with_number_and_ward_and_stays_short(node, category):
    t = {f"{s}_{k}": v for s in ("infra", "quality") for k, v in (("persist_steps", 287), ("suddenness", 0.99), ("recurrence", 23))}
    msg = format_message({"node_id": node, "category": category, "priority": "Critical", "confidence": 0.99, "ts": "2018-12-31T23:55:00",
                          "p_infra": 0.999, "p_quality": 0.999, "temporal": t})
    assert msg.startswith(PREFIX + "\n") and f"\nNode: {node_label(node)}\n" in msg and len(msg) < LIMIT
    assert "(model score 0.999".replace("0.999", "1.00") in msg  # the longest case still keeps every number


# ------------------------------------------------------------------ citizen bot replies
def test_template_replies_name_the_ward_with_its_sensor_point_in_english_and_hindi():
    a = answerer(states={"node-3": {"category": "Infrastructure", "priority": "High", "status": "ok"}})
    assert a.answer(Q4).text.startswith("Ward 4 (Bagayam, sensor point node-4): Tanker TKR-10")
    assert a.answer("वार्ड 4 में टैंकर कब आएगा?").text.startswith("वार्ड 4 (बागायम, सेंसर पॉइंट node-4): टैंकर TKR-10")
    assert a.answer("Is there any problem in ward 3?").text.startswith("Ward 3 (Sathuvachari, sensor point node-3): our sensors")
    assert a.answer("वार्ड 3 में कोई समस्या है क्या?").text.startswith("वार्ड 3 (सतुवाचारी, सेंसर पॉइंट node-3):") or \
        "सेंसर पॉइंट node-3" in a.answer("वार्ड 3 में कोई समस्या है क्या?").text
    assert guard(a.answer(Q4).text, a.retrieve(understand(Q4, W), Q4), W) == []  # the template stays grounded


def test_help_and_ticket_replies_carry_the_numbered_sensor_point():
    assert "Ward 4 (Bagayam, sensor point node-4)" in HELP["en"] and "सेंसर पॉइंट node-4" in HELP["hi"]
    t = {"id": 5, "in_demo_area": True, "node_id": "node-2", "node_name": "Gandhi Nagar Tank", "nearest_node_id": "node-2",
         "nearest_node_name": "Gandhi Nagar Tank", "distance_km": 0.08, "node_category": "Normal", "node_priority": None}
    assert "Nearest sensor point: Gandhi Nagar Tank (node-2 · Ward 2), 0.08 km away." in ticket_reply(t, "en")
    assert "Gandhi Nagar Tank (node-2 · Ward 2)" in ticket_reply(t, "hi")
    far = {**t, "in_demo_area": False, "node_id": None, "node_name": None, "distance_km": 41.2}
    assert "(the nearest sensor point, Gandhi Nagar Tank (node-2 · Ward 2), is 41.2 km away)" in ticket_reply(far, "en")


def test_guard_accepts_the_wards_own_sensor_point_and_rejects_another_one():
    good = "Tanker TKR-10 for Ward 4 (Bagayam, sensor point node-4) is planned for tomorrow, 8 Jan, 06:00-08:00."
    r = answerer(llm=FakeOllama(good).writer()).answer(Q4)
    assert r.writer == "ollama" and not r.guard_fallback and r.text == good
    wrong = "Tanker TKR-10 for Ward 4 (Bagayam, sensor point node-5) is planned for tomorrow, 8 Jan, 06:00-08:00."
    r = answerer(llm=FakeOllama(wrong).writer()).answer(Q4)
    assert r.guard_fallback and any("5" in v for v in r.guard_violations) and r.text.startswith("Ward 4 (Bagayam, sensor point node-4):")


def test_hindi_translation_must_keep_the_sensor_point_number():
    good = "Tanker TKR-10 for Ward 4 (Bagayam, sensor point node-4) is planned for tomorrow, 8 Jan, 06:00-08:00."
    kept = "वार्ड 4 (बागायम, सेंसर पॉइंट node-4) के लिए टैंकर TKR-10 कल, 8 जनवरी को 06:00-08:00 निर्धारित है।"
    lost = "बागायम के लिए टैंकर कल सुबह आएगा।"
    assert numbers_survive(good, kept) and not numbers_survive(good, lost)
    for hi, ok in ((kept, True), (lost, False)):
        r = answerer(llm=FakeOllama(good).writer(), translator=FakeTranslator({(good, "en", "hi"): hi})).answer("वार्ड 4 में टैंकर कब आएगा?")
        assert r.translation_fallback == (not ok) and "node-4" in r.text
