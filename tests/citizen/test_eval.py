"""Citizen evaluation helpers (C6): the question set, the truth, the judge and the word error rate."""
from collections import Counter

from kami.citizen.answer import Answerer, Reply
from kami.citizen.evaluate import corpus_wer, eval_world, judge, load_questions, truth, wer, words

from .helpers import FakeOllama


def test_question_set_shape_and_split():
    qs = load_questions()
    by = Counter((q["lang"], q["split"]) for q in qs)
    assert len(qs) == 60 and by == {("en", "val"): 10, ("en", "test"): 20, ("hi", "val"): 10, ("hi", "test"): 20}
    assert len({q["id"] for q in qs}) == 60 and len({q["text"] for q in qs}) == 60
    for split in ("val", "test"):
        part = [q for q in qs if q["split"] == split]
        assert {q["intent"] for q in part} == {"schedule", "ward_status", "faq", "none"}  # both splits cover every kind of question
    assert {q["expect"]["ward"] for q in qs if q["intent"] == "schedule"} == set(range(1, 9))  # schedule questions for every ward
    assert sum(q["intent"] == "none" for q in qs) >= 8 and sum(q.get("script") == "latin" for q in qs) >= 4
    assert all(any("ऀ" <= ch <= "ॿ" for ch in q.get("speech_text", q["text"])) for q in qs if q["lang"] == "hi")


def test_truth_comes_from_the_structured_lookup():
    sch, ns = eval_world()
    q = {"intent": "schedule", "expect": {"ward": 1, "day": 0}}
    assert truth(q, sch, ns) == {"kind": "schedule", "times": ["10:00", "12:00", "16:45", "18:45"], "times_allowed": ["10:00", "12:00", "16:00", "16:45", "18:00", "18:45"],
                                 "tankers": [6, 8], "statuses": ["delayed"], "alert_note": False}
    w3 = truth({"intent": "schedule", "expect": {"ward": 3, "day": None}}, sch, ns)
    assert w3["alert_note"] is True  # the planted alert at node-3 marks the pending tanker of ward 3
    assert truth({"intent": "ward_status", "expect": {"ward": 3}}, sch, ns) == {"kind": "ward_status", "category": "Infrastructure", "priority": "High"}
    assert truth({"intent": "ward_status", "expect": {"ward": 2}}, sch, ns)["category"] == "Normal"
    assert truth({"intent": "none", "expect": {}}, sch, ns) == {"kind": "no_info"}
    assert truth({"intent": "schedule", "expect": {"ward": 5, "day": 2}}, sch, ns)["kind"] in ("schedule", "no_info")


def test_judge_accepts_right_answers_and_rejects_wrong_ones():
    sch, ns = eval_world()
    a = Answerer(sch, node_state=ns)
    q = {"id": "x", "lang": "en", "intent": "schedule", "text": "What time does the tanker come to ward 1 today?", "expect": {"ward": 1, "day": 0}}
    t = truth(q, sch, ns)
    good = a.answer(q["text"])
    assert judge(q, good, t) == {"slot_ok": True, "answer_ok": True, "final_ok": True, "no_info_ok": True}

    def with_text(text):
        return Reply(text, text, "en", good.intent, good.kind, good.ward, good.day, "ollama", False, records=good.records)

    assert not judge(q, with_text("Tanker TKR-06 comes today 10:00-12:00."), t)["answer_ok"]  # the second, delayed tanker is missing
    assert not judge(q, with_text(good.text.replace("16:45-18:45", "17:45-19:45")), t)["answer_ok"]  # a wrong time
    assert not judge(q, with_text(good.text.replace("TKR-08", "TKR-09")), t)["answer_ok"]  # a wrong tanker
    assert not judge(q, with_text(good.text.replace("is delayed by", "is planned with")), t)["answer_ok"]  # the delay is not said
    wrong_ward = a.answer("What time does the tanker come to ward 2 today?")
    assert judge(q, wrong_ward, t)["slot_ok"] is False
    none_q = {"id": "n", "lang": "en", "intent": "none", "text": "Who won the cricket match yesterday?", "expect": {}}
    assert all(judge(none_q, a.answer(none_q["text"]), truth(none_q, sch, ns)).values())
    assert not judge(none_q, good, truth(none_q, sch, ns))["no_info_ok"]  # answering something where nothing is known is wrong
    faq = {"id": "f", "lang": "en", "intent": "faq", "text": "What are the piped water supply hours?", "expect": {"notice": "supply_timings", "must": ["06:00", "08:00", "17:00", "19:00"]}}
    assert all(judge(faq, a.answer(faq["text"]), truth(faq, sch, ns)).values())
    short = Answerer(sch, node_state=ns, llm=FakeOllama("Piped water is supplied from 6 am to 8 am in the morning.").writer()).answer(faq["text"])
    assert short.guard_fallback and all(judge(faq, short, truth(faq, sch, ns)).values())  # half of the hours: the guard replaces it with the notice
    half = Reply("Piped water is supplied from 06:00 to 08:00.", "Piped water is supplied from 06:00 to 08:00.", "en", "faq", "faq", None, None, "ollama", False,
                 records=short.records)
    assert not judge(faq, half, truth(faq, sch, ns))["answer_ok"]  # and the judge itself counts an incomplete answer as wrong
    status = {"id": "s", "lang": "en", "intent": "ward_status", "text": "Is there any problem in ward 3?", "expect": {"ward": 3}}
    assert all(judge(status, a.answer(status["text"]), truth(status, sch, ns)).values())


def test_word_error_rate():
    assert wer("a b c d".split(), "a b c d".split()) == 0.0 and wer("a b c d".split(), "a x c d".split()) == 0.25
    assert wer("a b c d".split(), "a c d".split()) == 0.25 and wer("a b".split(), "a b c d".split()) == 1.0 and wer([], []) == 0.0
    assert corpus_wer([("a b c d".split(), "a b c d".split()), ("a b".split(), "x y".split())]) == 2 / 6
    assert words("वार्ड 4 में टैंकर कब आएगा?", "hi") == words("वार्ड चार में टैंकर कब आएगा", "hi")  # digits and number words count as equal
    assert words("When will the tanker reach Ward 4?", "en") == ["when", "will", "the", "tanker", "reach", "ward", "four"]
    assert words("पाँच फ़ोन", "hi") == words("पांच फोन", "hi") and words("Ward 4", "en", normalise=False) == ["ward", "4"]
