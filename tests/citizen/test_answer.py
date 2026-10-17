"""Citizen interface: demo data, schedule service, understanding, retrieval, writers and the grounding guard (C1, C4)."""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from kami.citizen.answer import (CAUSE_WORDS, NOTE_HI, NoticeIndex, OllamaWriter, Retrieved, TemplateWriter, detect_language, guard, numbers_survive,
                                 understand)
from kami.citizen.data import ALERT_NOTE, load_notices, load_schedule, load_wards
from kami.citizen.tts import number_words, spoken_text

from .helpers import NOON, FakeOllama, FakeTranslator, answerer, schedule

ROOT = Path(__file__).resolve().parents[2]
W = load_wards()
GOOD = "Tanker TKR-10 is scheduled for Ward 4 (Bagayam) tomorrow, 8 Jan, from 06:00 to 08:00."
Q4 = "When will the water tanker reach Ward 4?"


# ------------------------------------------------------------------ C1: demo data and schedule service
def test_demo_data_is_labelled_fictional_and_wards_map_to_nodes():
    nodes = json.loads((ROOT / "config" / "nodes.json").read_text(encoding="utf-8"))["nodes"]
    assert [(w.number, w.node_id) for w in W] == [(i, f"node-{i}") for i in range(1, 9)]
    for w, n in zip(W, nodes):
        assert n["name"].startswith(w.name_en) and any("ऀ" <= ch <= "ॿ" for ch in w.name_hi)
    assert 10 <= len(load_notices()) <= 20 and {r.ward for r in load_schedule()} == set(range(1, 9))
    assert "demo_fictional" in (ROOT / "data/citizen/tanker_schedule_demo_fictional.csv").read_text(encoding="utf-8").splitlines()[0]


def test_schedule_file_is_reproduced_by_the_seeded_script():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_citizen_data.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_status_follows_the_replay_clock():
    s = schedule()
    w1 = {(d.day_offset, d.slot): d for d in s.deliveries(1)}
    assert w1[(-1, "10:00-12:00")].status == "delivered" and w1[(1, "10:00-12:00")].status == "scheduled"
    assert w1[(0, "10:00-12:00")].status == "en route"  # 11:00 is inside the slot
    late = w1[(0, "16:00-18:00")]
    assert (late.status, late.delay_minutes, late.expected) == ("delayed", 45, "16:45-18:45")
    assert schedule(now=datetime(2018, 1, 7, 8, 59)).deliveries(1, 0)[0].status == "scheduled"  # more than one hour before the slot
    assert schedule(now=datetime(2018, 1, 7, 9, 0)).deliveries(1, 0)[0].status == "en route"
    assert schedule(now=datetime(2018, 1, 7, 12, 0)).deliveries(1, 0)[0].status == "delivered"
    after = schedule(now=datetime(2018, 1, 7, 18, 30)).deliveries(1, 0)[1]
    assert after.status == "delayed"  # the delayed tanker is expected until 18:45
    assert schedule(now=datetime(2018, 1, 7, 18, 45)).deliveries(1, 0)[1].status == "delivered"
    nxt = s.next_delivery(4)
    assert (nxt.tanker_id, nxt.day_offset, nxt.date_text, nxt.slot, nxt.status) == ("TKR-10", 1, "8 Jan", "06:00-08:00", "scheduled")
    assert s.deliveries(99) == [] and s.next_delivery(99) is None
    assert schedule(now=datetime(2018, 1, 31, 23, 0)).deliveries(4, 1)[0].date_text == "1 Feb"  # dates follow the replay day


def test_open_high_alert_marks_the_ward_tankers_as_possibly_delayed():
    quiet, medium = schedule(), schedule({"node-4": {"priority": "Medium"}})
    assert not any(d.alert_note for d in quiet.deliveries(4)) and not any(d.alert_note for d in medium.deliveries(4))
    for pri in ("High", "Critical"):
        s = schedule({"node-4": {"priority": pri, "category": "Infrastructure"}})
        ds = s.deliveries(4)
        assert [d.alert_note for d in ds] == [d.status != "delivered" for d in ds] and any(d.alert_note for d in ds)
        assert not any(d.alert_note for d in s.deliveries(3))  # only the ward of that node
        assert s.next_delivery(4).facts()["note"] == ALERT_NOTE == "possibly delayed: active network alert in your area"
    a = answerer(alerts={"node-4": {"priority": "High"}})
    en, hi = a.answer(Q4), a.answer("वार्ड 4 में टैंकर कब आएगा?")
    assert "Note: possibly delayed: active network alert in your area." in en.text and NOTE_HI in hi.text
    assert not any(w in en.text.lower() for w in CAUSE_WORDS)  # no cause is stated
    broken = schedule()
    broken.open_alert = lambda node_id: 1 / 0  # the live state failing must never break an answer
    assert broken.next_delivery(4).alert_note is False


# ------------------------------------------------------------------ C4: understanding (rules; Hindi, Hinglish and English)
@pytest.mark.parametrize("text, intent, ward, day", [
    ("When will the water tanker reach Ward 4?", "schedule", 4, None),
    ("Ward 4 mein tanker kab aayega?", "schedule", 4, None),
    ("वार्ड 4 में टैंकर कब आएगा?", "schedule", 4, None),
    ("वार्ड चार में कल टैंकर कब आएगा", "schedule", 4, 1),
    ("आज वार्ड ६ में टैंकर आया क्या", "schedule", 6, 0),
    ("गांधी नगर में टैंकर कब आएगा?", "schedule", 2, None),
    ("kal tanker aaya tha kya ward 2 mein", "schedule", 2, -1),
    ("Has the tanker for Katpadi been delivered today?", "schedule", 1, 0),
    ("parso ward 8 tanker", "schedule", 8, 2),
    ("tanker timing for ward number 7 tomorrow", "schedule", 7, 1),
    ("3 number ward ka tanker kahan hai", "schedule", 3, None),
    ("ward 5 mein paani kab aayega", "schedule", 5, None),
    ("Ward 12 tanker timing", "schedule", 12, None),
    ("tanker", "schedule", None, None),
    ("Is there any problem in ward 3?", "ward_status", 3, None),
    ("वार्ड 7 में कोई समस्या है क्या?", "ward_status", 7, None),
    ("Is tanker water free?", "faq", None, None),
    ("टैंकर के पैसे लगते हैं क्या?", "faq", None, None),
    ("When do ward offices open?", "faq", None, None),
    ("How do I report a broken pipe?", "faq", None, None),
    ("What is the helpline number?", "faq", None, None),
    ("Who won the cricket match?", "faq", None, None),
])
def test_understanding_rules(text, intent, ward, day):
    u = understand(text, W)
    assert (u.intent, u.ward, u.day) == (intent, ward, day)


@pytest.mark.parametrize("heard, ward, day", [
    ("बाड चार मी तैन कर कब आएगा।", 4, None), ("आज वाड एक में तैन कर कितने बज़े आएगा।", 1, 0), ("कल वाड दो मेतेंकर कब आएगा।", 2, 1),
    ("बागायम में कल पैनकर कितने बजे आएगा।", 4, 1), ("सत्वचारी में आज टैंकर आया क्या?", 3, 0), ("वाड 15 में तैनकर कब आएगा?", 15, None),
    ("Tanker timing for War 2 tomorrow.", 2, 1),
])
def test_rules_tolerate_what_speech_recognition_hears(heard, ward, day):
    """Spellings that the speech model produced for the validation questions (synthetic speech)."""
    u = understand(heard, W)
    assert (u.intent, u.ward, u.day) == ("schedule", ward, day)


def test_close_names_do_not_fire_on_ordinary_words():
    for text in ("When will the tanker come tomorrow?", "tanker kab aayega", "टैंकर कब आएगा?", "Tell me about the tanker schedule today",
                 "Is the tanker for the old market late?", "पानी की गाड़ी कब आएगी?"):
        assert understand(text, W).ward is None, text
    assert understand("When will the tanker come to Thorapady?", W).ward == 8 and understand("Katpady tanker time", W).ward == 1
    # a name that speech recognition changed too much stays unmatched (the citizen is then asked for the ward) rather than guessed
    assert understand("Has the tanker for Sathya Vittari been delivered today?", W).ward is None


def test_language_detection():
    assert detect_language("वार्ड 4 में टैंकर कब आएगा?") == "hi" and detect_language("Ward 4 mein tanker kab aayega?") == "hi"
    assert detect_language("When will the tanker reach Ward 4?") == "en" and detect_language("Tell me about ward 4") == "en"


# ------------------------------------------------------------------ C4: retrieval and the template writer
def test_schedule_answers_take_every_time_from_the_data():
    a = answerer()
    r = a.answer(Q4)
    assert r.text == "Ward 4 (Bagayam, sensor point node-4): Tanker TKR-10 is planned for tomorrow, 8 Jan, 06:00-08:00. Status: scheduled."
    assert (r.kind, r.ward, r.writer, r.no_info, r.lang) == ("schedule", 4, "template", False, "en")
    assert r.records == [{"ward": 4, "ward_name": "Bagayam", "tanker": "TKR-10", "day": "tomorrow", "date": "8 Jan", "planned_slot": "06:00-08:00", "status": "scheduled"}]
    hi = a.answer("वार्ड 4 में टैंकर कब आएगा?")
    assert hi.text == "वार्ड 4 (बागायम, सेंसर पॉइंट node-4): टैंकर TKR-10 कल, 8 जनवरी को 06:00-08:00 के बीच आने की योजना है। स्थिति: निर्धारित।" and hi.lang == "hi"
    assert a.answer("Ward 4 mein tanker kab aayega?").text == hi.text  # Hindi in Latin letters gets the Hindi answer
    today = a.answer("Has the tanker for Katpadi been delivered today?").text
    assert "TKR-06 is planned for today, 7 Jan, 10:00-12:00. Status: en route." in today
    assert "TKR-08 is delayed by 45 minutes. Expected today, 7 Jan, 16:45-18:45 (planned 16:00-18:00)." in today
    assert "delivered yesterday, 6 Jan, in the 06:00-08:00 slot" in a.answer("Did the tanker come to ward 2 yesterday?").text
    assert guard(r.text, a.retrieve(understand(Q4, W), Q4), W) == []  # the template itself is always grounded


def test_ward_status_says_what_the_sensors_show_and_no_cause():
    a = answerer(states={"node-3": {"category": "Infrastructure", "priority": "High", "status": "ok"}, "node-5": {"category": "Normal", "priority": "Low", "status": "ok"},
                         "node-6": {"category": "Normal", "priority": "Low", "status": "warming_up"}})
    alert = a.answer("Is there any problem in ward 3?").text
    assert alert == ("Ward 3 (Sathuvachari, sensor point node-3): our sensors there currently show an Infrastructure alert, priority High. "
                     "This says what the sensors show, not the reason.")
    assert a.answer("Is there any problem in ward 5?").text == "Ward 5 (Old Town, sensor point node-5): our sensors there currently show no anomaly."
    for q in ("Any alert in ward 6?", "Any alert in ward 8?"):  # warming up, or no live state at all
        assert "not available" in a.answer(q).text
    assert "इन्फ्रास्ट्रक्चर" in a.answer("वार्ड 3 में कोई समस्या है क्या?").text and "उच्च" in a.answer("वार्ड 3 में कोई समस्या है क्या?").text
    assert not any(w in alert.lower() for w in CAUSE_WORDS)


def test_notice_questions_are_answered_from_the_notices():
    a = answerer()
    assert a.answer("Is tanker water free?").text.startswith("Tanker water delivered under the ward schedule is free of charge.")
    assert "1800-000-0000" in a.answer("What is the helpline number?").text and "fictional" in a.answer("What is the helpline number?").text
    assert "10:00 to 17:00" in a.answer("When do ward offices open?").text
    assert "Send a photo of the damaged pipe" in a.answer("How do I report a broken pipe?").text
    idx = NoticeIndex()
    assert idx.search("What do the alert priority levels mean?")[0][0]["id"] == "alert_levels" and idx.search("zzz qqq") == []
    # a Hindi question is matched on Hindi keywords first, so a translation slip ("tanker" -> "tank") cannot pick the wrong notice
    assert idx.search("Is the tank water free?", original="टैंकर का पानी मुफ्त है क्या?")[0][0]["id"] == "tanker_charges"
    assert idx.search(None, original="tanker ka paani free hai kya?")[0][0]["id"] == "tanker_charges"
    assert idx.search(None, original="क्या हाल है?") == [] and idx.search(None) == []


def test_unanswerable_questions_get_the_no_information_reply():
    a = answerer(llm=FakeOllama("should never be asked").writer())
    for q in ("Who won the cricket match?", "What will the weather be next week?", "Ward 12 tanker timing", "When will the tanker reach ward 9?"):
        r = a.answer(q)
        assert r.no_info and r.kind == "no_info" and r.writer == "template" and "do not have" in r.text, q
    hi = a.answer("वार्ड 15 में टैंकर कब आएगा?")
    assert hi.no_info and "जानकारी नहीं है" in hi.text and "वार्ड 1 से 8" in hi.text
    ask = a.answer("When will the tanker come?")
    assert ask.kind == "ask_ward" and not ask.no_info and "ward number (1 to 8)" in ask.text
    assert a.llm._client is not None and a.answer("tanker kab aayega").kind == "ask_ward"
    none_planned = a.answer("Tanker timing for ward 5 the day after tomorrow")
    assert none_planned.no_info == (none_planned.kind == "no_info")  # a ward without a delivery that day says so instead of guessing
    assert "no tanker is planned" in TemplateWriter().write("", Retrieved("no_info", W[4], 2, reason="nothing_planned"), "en")


# ------------------------------------------------------------------ C4: the local LLM writer and the grounding guard
def test_a_grounded_llm_answer_is_used_and_the_prompt_has_only_the_records():
    llm = FakeOllama(GOOD)
    r = answerer(llm=llm.writer()).answer(Q4)
    assert (r.text, r.writer, r.guard_fallback, r.guard_violations) == (GOOD, "ollama", False, [])
    body = llm.prompts[0]
    assert body["options"]["temperature"] == 0 and body["stream"] is False and body["model"] == "llama3.2:3b"
    user = body["messages"][1]["content"]
    assert "- Tanker TKR-10 for Ward 4 (Bagayam, sensor point node-4): tomorrow, 8 Jan, time slot 06:00-08:00, status scheduled" in user and Q4 in user
    assert "TKR-05" not in user and "Katpadi" not in user  # nothing that was not retrieved
    assert "ONLY the facts in RECORDS" in body["messages"][0]["content"] and "Never say why" in body["messages"][0]["content"]


def test_guard_replaces_an_answer_with_a_planted_wrong_time():
    for planted in ("Tanker TKR-10 will reach Ward 4 tomorrow, 8 Jan, between 07:00 and 09:00.", "The tanker comes to Ward 4 tomorrow at 6:30 am.",
                    "Tanker TKR-10 reaches Ward 4 tomorrow at 5 pm."):
        r = answerer(llm=FakeOllama(planted).writer()).answer(Q4)
        assert r.guard_fallback and r.writer == "template" and any(v.startswith("time not in the records") for v in r.guard_violations), planted
        assert r.text == "Ward 4 (Bagayam, sensor point node-4): Tanker TKR-10 is planned for tomorrow, 8 Jan, 06:00-08:00. Status: scheduled."
        assert "07:00" not in r.text and "6:30" not in r.text and "5 pm" not in r.text


def test_guard_replaces_an_answer_with_a_planted_wrong_ward():
    for planted, why in (("Tanker TKR-10 is planned for Ward 5 tomorrow, 8 Jan, 06:00-08:00.", "ward not in the records: 5"),
                         ("Tanker TKR-10 is planned for Katpadi tomorrow, 8 Jan, 06:00-08:00.", "ward name not in the records: ward 1")):
        r = answerer(llm=FakeOllama(planted).writer()).answer(Q4)
        assert r.guard_fallback and why in r.guard_violations and r.text.startswith("Ward 4 (Bagayam, sensor point node-4):"), planted


def test_guard_replaces_an_answer_that_names_a_cause():
    for planted in (GOOD + " The earlier delay was due to a pipe leak.", GOOD + " There may be contamination in the area.",
                    GOOD + " It is late because of a burst main."):
        r = answerer(llm=FakeOllama(planted).writer()).answer(Q4)
        assert r.guard_fallback and any(v.startswith("cause word") for v in r.guard_violations), planted
        assert not any(w in r.text.lower() for w in CAUSE_WORDS)


@pytest.mark.parametrize("planted, kind", [
    ("Tanker TKR-10 is planned for Ward 4 today, 8 Jan, 06:00-08:00.", "day"),
    ("Tanker TKR-03 is planned for Ward 4 tomorrow, 8 Jan, 06:00-08:00.", "tanker"),
    ("Tanker TKR-10 is planned for Ward 4 tomorrow, 9 Jan, 06:00-08:00.", "date"),
    ("Tanker TKR-10 is planned for Ward 4 tomorrow, 06:00-08:00, and will bring 500 litres.", "number"),
    ("Tanker TKR-10 has been delivered to Ward 4.", "status"),
    ("Tanker TKR-10 for Ward 4 is delayed; expect it tomorrow, 06:00-08:00.", "status"),
    ("", "empty"),
    ("x", "missing"),
    ("I am not sure when the tanker will come.", "missing"),
    ("The 4 metre tankers will arrive tomorrow, 8 Jan, during the time slot 06:00-08:00.", "missing: the ward"),
    ("Ward 4 will meet tomorrow from 06:00-08:00.", "missing: the tanker id"),
    ("The tanker will reach Ward 4 soon.", "missing"),
])
def test_guard_catches_other_ungrounded_claims(planted, kind):
    r = answerer(llm=FakeOllama(planted or "   ").writer()).answer(Q4)
    assert r.guard_fallback and r.writer == "template" and any(kind in v for v in r.guard_violations), r.guard_violations


def test_guard_on_notice_answers_and_accepted_rewordings():
    a = answerer(llm=FakeOllama("The ward offices are open from 10:00 to 17:00, Monday to Saturday.", "Ward offices open at 9:00 every day.",
                                "You can call the helpline on 1800-111-2222.").writer())
    assert a.answer("When do ward offices open?").writer == "ollama"
    bad = a.answer("When do ward offices open?")
    assert bad.guard_fallback and bad.text.startswith("Ward offices are open from 10:00 to 17:00")
    mixed = answerer(llm=FakeOllama("Tap water is supplied from 08:00 to 17:00.").writer()).answer("What are the piped water supply hours?")
    assert mixed.guard_fallback and any("some of the times" in v for v in mixed.guard_violations)  # two half ranges glued together
    assert "06:00 to 08:00" in mixed.text and "17:00 to 19:00" in mixed.text
    for invented in ("The tap water is not supplied.", "Piped water is supplied every day in the morning and in the evening."):
        r = answerer(llm=FakeOllama(invented).writer()).answer("What are the piped water supply hours?")
        assert r.guard_fallback and "06:00 to 08:00" in r.text, invented  # a made-up negation, or the hours left out
    r = answerer(llm=FakeOllama("No, tanker water is not free.").writer()).answer("Is tanker water free?")
    assert r.guard_fallback and "a negation that is not in the notice" in r.guard_violations and "free of charge" in r.text
    phone = a.answer("What is the helpline number?")
    assert phone.guard_fallback and "1800-000-0000" in phone.text and "1800-111-2222" not in phone.text
    r = Retrieved("schedule", W[3], None, [schedule().next_delivery(4)])
    status = Retrieved("ward_status", W[2], node_state={"category": "Infrastructure", "priority": "High"})
    assert guard("Sensors in Ward 3 show an Infrastructure alert with High priority.", status, W) == []
    assert guard("Everything is fine in Ward 3.", status, W) == ["missing: the alert category and priority"]
    assert guard("Ward 3 has no anomaly.", Retrieved("ward_status", W[2], node_state={"category": "Normal", "priority": "Low"}), W) == []
    notice = Retrieved("faq", notices=[{"title": "Tanker charges", "text": "Tanker water delivered under the ward schedule is free of charge."}])
    assert guard("Yes, tanker water under the ward schedule is free of charge.", notice, W) == []
    assert guard("Bananas are a good source of potassium.", notice, W) == ["missing: content from the notice"]
    for fine in (GOOD, "The tanker (TKR-10) will be delivered to Ward 4 tomorrow, 8 January, between 6 am and 8 am.",
                 "Ward 4: tanker TKR-10, tomorrow 8 Jan, 06:00 to 08:00, status scheduled."):
        assert guard(fine, r, W) == [], fine


def test_llm_failures_fall_back_to_the_template_and_only_a_local_url_is_accepted():
    for failure in (httpx.ConnectError("no ollama"), httpx.ReadTimeout("slow")):
        r = answerer(llm=FakeOllama(failure).writer()).answer(Q4)
        assert r.llm_unavailable and r.writer == "template" and not r.guard_fallback and "TKR-10" in r.text
    bad = OllamaWriter("m", transport=httpx.MockTransport(lambda req: httpx.Response(500, text="x")))
    assert answerer(llm=bad).answer(Q4).llm_unavailable
    for url in ("https://ollama.com", "http://203.0.113.5:11434", "http://example.org:11434"):
        with pytest.raises(ValueError, match="local"):
            OllamaWriter("m", url)


# ------------------------------------------------------------------ Hindi replies: translation model, never the LLM
def test_hindi_replies_use_fixed_sentences_or_the_translation_model():
    q_hi, a_hi = "टैंकर का पानी मुफ्त है क्या?", "वार्ड अनुसूची के तहत दिया जाने वाला टैंकर का पानी निःशुल्क है। टैंकर पर कोई भी भुगतान नहीं मांग सकता।"
    free = next(n["text"] for n in load_notices() if n["id"] == "tanker_charges")
    tr = FakeTranslator({(q_hi, "hi", "en"): "Is tanker water free?", (free, "en", "hi"): a_hi})
    r = answerer(translator=tr).answer(q_hi)
    assert (r.text, r.lang, r.kind, r.translation_fallback) == (a_hi, "hi", "faq", False) and r.text_en == free
    sched = answerer(translator=tr).answer("वार्ड 4 में टैंकर कब आएगा?")
    assert "निर्धारित" in sched.text and len(tr.calls) == 2  # a schedule answer in Hindi needs no translation at all
    bare = answerer().answer(q_hi)  # no translation model: the Hindi keywords still find the notice, which is then sent in English with a note
    assert bare.kind == "faq" and bare.translation_fallback and bare.text == "(हिंदी अनुवाद उपलब्ध नहीं है)\n" + free
    assert answerer().answer("कल क्रिकेट मैच कौन जीता?").no_info and answerer().answer("चाँद पर पानी है क्या?").no_info


def test_llm_answer_in_hindi_must_keep_its_numbers():
    q_hi = "वार्ड 4 में टैंकर कब आएगा?"
    good_hi = "टैंकर TKR-10 कल, 8 जनवरी को 06:00 से 08:00 तक वार्ड 4 (बागायम) के लिए निर्धारित है।"
    lost_hi = "टैंकर कल सुबह वार्ड 4 में आएगा।"
    for hi, kept in ((good_hi, True), (lost_hi, False)):
        tr, llm = FakeTranslator({(GOOD, "en", "hi"): hi}), FakeOllama(GOOD)
        r = answerer(llm=llm.writer(), translator=tr).answer(q_hi)
        # the LLM is asked a clean English question built from the understood ward and day, not a machine translation
        assert "QUESTION: When is the next water tanker for Ward 4 (Bagayam, sensor point node-4)?" in llm.prompts[0]["messages"][1]["content"]
        assert [c[1:] for c in tr.calls] == [("en", "hi")]
        assert r.translation_fallback == (not kept) and r.writer == ("ollama" if kept else "template")
        assert r.text == (good_hi if kept else "वार्ड 4 (बागायम, सेंसर पॉइंट node-4): टैंकर TKR-10 कल, 8 जनवरी को 06:00-08:00 के बीच आने की योजना है। स्थिति: निर्धारित।")
    assert numbers_survive("Open from 06:00 to 08:00, up to 200 litres.", "सुबह 6 बजे से 8 बजे तक, 200 लीटर तक।")
    assert numbers_survive("Call 1800-000-0000.", "1800-000-0000 पर कॉल करें।") and not numbers_survive("Call 1800-000-0000.", "हेल्पलाइन पर कॉल करें।")
    assert not numbers_survive("Due on the 15th.", "हर महीने देय।") and numbers_survive("Due on the 15th.", "हर महीने की १५ तारीख।")


# ------------------------------------------------------------------ spoken form for the voice reply
def test_spoken_text_writes_times_ids_and_numbers_as_words():
    hi = spoken_text("वार्ड 4 (बागायम): टैंकर TKR-10 कल, 8 जनवरी को 06:00-08:00 के बीच आने की योजना है। [KAMI डेमो]", "hi")
    assert hi == "वार्ड चार बागायम : टैंकर टी के आर दस कल, आठ जनवरी को सुबह छह बजे से सुबह आठ बजे तक के बीच आने की योजना है।"
    en = spoken_text("Tanker TKR-08 is delayed by 45 minutes. Expected 16:45-18:45. Ticket #12.", "en")
    assert en == "Tanker T K R eight is delayed by forty-five minutes. Expected four forty-five in the evening to six forty-five in the evening. Ticket number twelve."
    assert not any(ch.isdigit() for ch in hi + en + spoken_text("Call 1800-000-0000, 0.42 km, 200 litres, the 15th", "en"))
    assert [number_words(n, "hi") for n in (0, 19, 29, 45, 99, 200, 1800)] == ["शून्य", "उन्नीस", "उनतीस", "पैंतालीस", "निन्यानवे", "दो सौ", "एक हज़ार आठ सौ"]
    assert [number_words(n, "en") for n in (0, 13, 40, 99, 205, 1800)] == ["zero", "thirteen", "forty", "ninety-nine", "two hundred five", "one thousand eight hundred"]
