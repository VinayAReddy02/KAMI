"""Citizen bot: allowlist, rate limit, commands, language, voice, pipe-damage tickets, polling, redaction (C2, C5)."""
import io
import json
import logging

import httpx
import pytest
from PIL import Image

from kami.citizen.answer import CAUSE_WORDS
from kami.citizen.bot import HELP, MARK, NOT_PUBLIC, RateLimiter
from kami.citizen.speech import Transcript
from kami.citizen.telegram_in import BotApiError, Poller, TelegramClient
from kami.citizen.tickets import haversine_km, inspect_photo

from .helpers import FRIEND, ME, SECRETS, STRANGER, TOKEN, FakeASR, FakeTelegram, FakeTTS, jpeg, make_bot, msg

Q_EN, Q_HI = "When will the water tanker reach Ward 4?", "वार्ड 4 में टैंकर कब आएगा?"
A_EN = "Ward 4 (Bagayam, sensor point node-4): Tanker TKR-10 is planned for tomorrow, 8 Jan, 06:00-08:00. Status: scheduled."
A_HI = "वार्ड 4 (बागायम, सेंसर पॉइंट node-4): टैंकर TKR-10 कल, 8 जनवरी को 06:00-08:00 के बीच आने की योजना है। स्थिति: निर्धारित।"
NEAR_NODE_2 = (12.9425, 79.1565)  # about 80 m from Gandhi Nagar Tank
FAR_AWAY = (13.0827, 80.2707)  # Chennai


# ------------------------------------------------------------------ who is answered
def test_allowlist_other_chats_get_one_fixed_reply_and_are_not_processed(tmp_path):
    now = [1000.0]
    tg = FakeTelegram(files={"p1": jpeg(NEAR_NODE_2), "v1": b"OggS"})
    bot, store = make_bot(tmp_path, tg, asr=FakeASR(Transcript(Q_EN, "en")), tts=FakeTTS(), clock=lambda: now[0])
    for content in ({"text": Q_EN}, {"document": {"file_id": "p1", "mime_type": "image/jpeg", "file_size": 900}}, {"voice": {"file_id": "v1", "duration": 3}},
                    {"location": {"latitude": NEAR_NODE_2[0], "longitude": NEAR_NODE_2[1]}}, {"text": "/start"}):
        bot.handle_update(msg(STRANGER, **content))
    assert tg.sent == [(STRANGER, NOT_PUBLIC)]  # one fixed line, no answer, no marker
    assert tg.calls == ["sendMessage"]  # nothing was fetched or downloaded for this chat
    assert store.read_complaints() == [] and not (tmp_path / "citizen" / "uploads").exists() and bot.asr.calls == []
    assert bot.counts["not_allowed"] == 5 and bot.counts["text_questions"] == 0
    now[0] += 3599
    bot.handle_update(msg(STRANGER, text="hello?"))
    assert len(tg.sent) == 1  # still within the hour: silent
    now[0] += 2
    bot.handle_update(msg(STRANGER, text="hello?"))
    assert tg.sent[-1] == (STRANGER, NOT_PUBLIC) and len(tg.sent) == 2
    for chat in (ME, FRIEND):  # TELEGRAM_CHAT_ID and CITIZEN_ALLOWED_CHAT_IDS are answered
        bot.handle_update(msg(chat, text=Q_EN))
        assert tg.sent[-1] == (chat, f"{A_EN}\n{MARK['en']}")
    for odd in ({}, {"message": {}}, {"message": {"chat": {"id": "x"}}}, {"edited_message": {"chat": {"id": ME}}}, None):
        bot.handle_update(odd)  # malformed updates are ignored without an error
    assert len(tg.sent) == 4


def test_rate_limit_per_chat(tmp_path):
    now = [0.0]
    tg = FakeTelegram()
    bot, _ = make_bot(tmp_path, tg, clock=lambda: now[0])
    for i in range(12):
        now[0] += 1
        bot.handle_update(msg(ME, i, text=Q_EN))
    assert len(tg.texts(ME)) == 11 and tg.texts(ME)[:10] == [f"{A_EN}\n{MARK['en']}"] * 10
    assert tg.texts(ME)[10].startswith("Too many requests") and bot.counts["rate_limited"] == 2  # told once, then silent
    bot.handle_update(msg(FRIEND, 50, text=Q_EN))
    assert tg.texts(FRIEND) == [f"{A_EN}\n{MARK['en']}"]  # another chat has its own limit
    now[0] += 60
    bot.handle_update(msg(ME, 60, text=Q_EN))
    assert tg.texts(ME)[-1].startswith("Ward 4") and bot.counts["text_questions"] == 12
    rl = RateLimiter(limit=2, window=10)
    assert [rl.allow("a", t) for t in (0, 1, 2, 9.9, 10, 10.5, 11)] == [True, True, False, False, True, False, True]


# ------------------------------------------------------------------ commands, language, questions
def test_commands_help_and_language(tmp_path):
    tg, now = FakeTelegram(), [0.0]
    bot, _ = make_bot(tmp_path, tg, clock=lambda: now.__setitem__(0, now[0] + 10) or now[0])  # 10 s between messages: under the rate limit
    bot.handle_update(msg(ME, text="/start"))
    assert tg.texts()[-1] == HELP["hi"] + "\n\n" + HELP["en"] and "demo_fictional" in HELP["en"] and "demo_fictional" in HELP["hi"]
    assert "not analysed automatically" in HELP["en"] and "invented" in HELP["en"]
    bot.handle_update(msg(ME, text=Q_HI))
    assert tg.texts()[-1] == f"{A_HI}\n{MARK['hi']}"  # Devanagari text is answered in Hindi
    bot.handle_update(msg(ME, text=Q_EN))
    assert tg.texts()[-1] == f"{A_EN}\n{MARK['en']}"
    bot.handle_update(msg(ME, text="/language hi"))
    assert tg.texts()[-1].startswith("अब जवाब हिंदी में मिलेंगे।")
    bot.handle_update(msg(ME, text=Q_EN))
    assert tg.texts()[-1] == f"{A_HI}\n{MARK['hi']}"  # the chat's setting wins over the language of the message
    bot.handle_update(msg(ME, text="/help"))
    assert tg.texts()[-1] == HELP["hi"]
    bot.handle_update(msg(ME, text="/language en"))
    bot.handle_update(msg(ME, text=Q_HI))
    assert tg.texts()[-1] == f"{A_EN}\n{MARK['en']}"
    bot.handle_update(msg(ME, text="/language auto"))
    bot.handle_update(msg(ME, text=Q_HI))
    assert tg.texts()[-1] == f"{A_HI}\n{MARK['hi']}"
    bot.handle_update(msg(ME, text="/language de"))
    assert "/language hi" in tg.texts()[-1]
    bot.handle_update(msg(ME, sticker={"file_id": "s"}))
    assert "/help" in tg.texts()[-1] and bot.counts["unsupported"] == 1


def test_every_answer_carries_the_demo_marker_and_unknown_questions_say_so(tmp_path):
    tg = FakeTelegram()
    bot, _ = make_bot(tmp_path, tg)
    for q in (Q_EN, Q_HI, "Who won the cricket match?", "Is there any problem in ward 3?", "tanker"):
        bot.handle_update(msg(ME, text=q))
        assert tg.texts()[-1].endswith(MARK["en"]) or tg.texts()[-1].endswith(MARK["hi"]), q
    assert "fictional" in MARK["en"] and "काल्पनिक" in MARK["hi"]
    assert "do not have that information" in tg.texts()[2] and bot.counts["no_information"] == 1


def test_a_failing_answer_gives_an_apology_and_the_bot_keeps_working(tmp_path):
    tg = FakeTelegram()
    bot, _ = make_bot(tmp_path, tg)
    real = bot.answerer.answer
    bot.answerer.answer = lambda text, lang=None: 1 / 0
    bot.handle_update(msg(ME, text=Q_EN))
    assert tg.texts()[-1].startswith("Sorry, something went wrong") and bot.counts["errors"] == 1
    bot.answerer.answer = real
    bot.handle_update(msg(ME, text=Q_EN))
    assert tg.texts()[-1].startswith("Ward 4")


# ------------------------------------------------------------------ voice
def test_voice_question_is_recognised_answered_in_text_and_spoken(tmp_path):
    tg = FakeTelegram(files={"v1": b"OggS-voice-bytes"})
    asr, tts = FakeASR(Transcript(Q_HI, "hi", 0.4)), FakeTTS()
    bot, _ = make_bot(tmp_path, tg, asr=asr, tts=tts)
    bot.handle_update(msg(ME, voice={"file_id": "v1", "duration": 4, "file_size": 16}))
    assert tg.texts() == [f"मैंने सुना: {Q_HI}\n\n{A_HI}\n{MARK['hi']}"]  # the citizen sees what was understood
    assert tts.calls == [(A_HI, "hi")] and tg.voices == [(ME, tg.voices[0][1])] and tg.voices[0][1] > 20
    assert tg.calls == ["getFile", "download", "sendChatAction", "sendMessage", "sendVoice"]
    assert asr.calls == [(16000, None)] and bot.counts["voice_replies"] == 1
    assert not (tmp_path / "citizen").exists()  # the voice note is never written to disk
    en = FakeTelegram(files={"v2": b"OggS"})
    bot2, _ = make_bot(tmp_path, en, asr=FakeASR(Transcript(Q_EN, "en")), tts=FakeTTS())
    bot2.handle_update(msg(ME, voice={"file_id": "v2", "duration": 4}))
    assert en.texts() == [f"I heard: {Q_EN}\n\n{A_EN}\n{MARK['en']}"]


def test_voice_limits_and_failures(tmp_path):
    tg = FakeTelegram(files={"v1": b"OggS", "big": b"x" * (2 * 1024 * 1024 + 1)})
    asr = FakeASR(Transcript("   ", "hi"))
    bot, _ = make_bot(tmp_path, tg, asr=asr, tts=FakeTTS())
    bot.handle_update(msg(ME, voice={"file_id": "v1", "duration": 61}))
    assert "60" in tg.texts()[-1] and "getFile" not in tg.calls  # too long: not even fetched
    bot.handle_update(msg(ME, voice={"file_id": "big", "duration": 5}))
    assert "60" in tg.texts()[-1] and asr.calls == []  # larger than the size limit: the download stops
    bot.handle_update(msg(ME, voice={"file_id": "v1", "duration": 5}))
    assert "वॉइस नोट समझ नहीं आया" in tg.texts()[-1] and bot.counts["voice_unclear"] == 1 and tg.voices == []
    off = FakeTelegram(files={"v1": b"OggS"})
    bot_off, _ = make_bot(tmp_path, off)  # speech models not loaded
    bot_off.handle_update(msg(ME, voice={"file_id": "v1", "duration": 5}))
    assert "लिखकर भेजें" in off.texts()[-1] and off.calls == ["sendMessage"]

    class BrokenTTS(FakeTTS):
        def synthesize(self, text, lang):
            raise RuntimeError("no voice")

    tg2 = FakeTelegram(files={"v1": b"OggS"})
    bot3, _ = make_bot(tmp_path, tg2, asr=FakeASR(Transcript(Q_EN, "en")), tts=BrokenTTS())
    bot3.handle_update(msg(ME, voice={"file_id": "v1", "duration": 5}))
    assert len(tg2.texts()) == 1 and tg2.voices == [] and bot3.counts["voice_reply_failed"] == 1  # the text answer still arrives


# ------------------------------------------------------------------ pipe-damage tickets
def test_photo_then_location_makes_a_ticket_linked_to_the_nearest_node(tmp_path):
    tg = FakeTelegram(files={"p_small": jpeg(size=(90, 60)), "p_big": jpeg(size=(1280, 960))})
    states = {"node-2": {"category": "Infrastructure", "priority": "High", "status": "ok"}}
    bot, store = make_bot(tmp_path, tg, states=states)
    bot.handle_update(msg(ME, text="/language en"))
    bot.handle_update(msg(ME, photo=[{"file_id": "p_small", "width": 90, "height": 60, "file_size": 800},
                                     {"file_id": "p_big", "width": 1280, "height": 960, "file_size": 90000}]))
    assert "share the location" in tg.texts()[-1] and store.read_complaints() == [] and tg.calls.count("download") == 1
    bot.handle_update(msg(ME, location={"latitude": NEAR_NODE_2[0], "longitude": NEAR_NODE_2[1]}))
    reply = tg.texts()[-1]
    assert reply == ("Report received. Ticket #1. Nearest sensor point: Gandhi Nagar Tank (node-2 · Ward 2), 0.08 km away. Our sensors there currently show an Infrastructure alert, "
                     f"priority High. The photo is stored for staff; it is not analysed automatically.\n{MARK['en']}")
    assert not any(w in reply.lower() for w in CAUSE_WORDS)
    (t,) = store.read_complaints()
    assert (t["id"], t["node_id"], t["node_name"], t["distance_km"], t["in_demo_area"]) == (1, "node-2", "Gandhi Nagar Tank", 0.08, True)
    assert (t["node_category"], t["node_priority"], t["status"], t["location_source"], t["photo_analysed"]) == ("Infrastructure", "High", "open", "telegram_location", False)
    assert (t["lat"], t["lon"], t["replay_ts"]) == (NEAR_NODE_2[0], NEAR_NODE_2[1], "2018-01-07T11:00:00")
    assert not any(k in t for k in ("chat_id", "chat", "name", "first_name", "user"))  # a ticket stores no chat id and no name
    up = tmp_path / "citizen" / "uploads"
    assert (up / t["photo_file"]).read_bytes() == tg.files["p_big"]  # the largest size was taken
    with Image.open(up / t["thumb_file"]) as im:
        assert im.format == "JPEG" and max(im.size) <= 360 and not im.getexif()  # the small copy has no metadata
    assert bot.counts["tickets"] == 1 and bot.tickets.pending_count() == 0


def test_location_first_exif_location_and_outside_the_demo_area(tmp_path):
    tg = FakeTelegram(files={"plain": jpeg(), "exif": jpeg(NEAR_NODE_2), "far": jpeg(FAR_AWAY), "png": jpeg(fmt="PNG")})
    bot, store = make_bot(tmp_path, tg, states={"node-2": {"category": "Normal", "priority": "Low", "status": "ok"}})
    bot.handle_update(msg(ME, location={"latitude": NEAR_NODE_2[0], "longitude": NEAR_NODE_2[1]}))
    assert "फोटो भेजें" in tg.texts()[-1]  # default language Hindi
    bot.handle_update(msg(ME, photo=[{"file_id": "png", "file_size": 500}]))
    assert "टिकट #1" in tg.texts()[-1] and "कोई असामान्यता नहीं" in tg.texts()[-1] and "स्वचालित विश्लेषण नहीं" in tg.texts()[-1]
    bot.handle_update(msg(ME, text="/language en"))
    bot.handle_update(msg(ME, document={"file_id": "exif", "mime_type": "image/jpeg", "file_size": 5000}))  # a photo sent as a file keeps its EXIF position
    assert tg.texts()[-1].startswith("Report received. Ticket #2. Nearest sensor point: Gandhi Nagar Tank (node-2 · Ward 2), 0.0") and "show no anomaly" in tg.texts()[-1]
    bot.handle_update(msg(ME, document={"file_id": "far", "mime_type": "image/jpeg", "file_size": 5000}))
    assert "Ticket #3" in tg.texts()[-1] and "outside the demo area" in tg.texts()[-1] and "not linked to a sensor" in tg.texts()[-1]
    t3, t2, t1 = store.read_complaints()
    assert (t3["in_demo_area"], t3["node_id"], t3["node_category"]) == (False, None, None) and t3["distance_km"] > 100
    assert t2["location_source"] == "photo_exif" and abs(t2["lat"] - NEAR_NODE_2[0]) < 1e-3 and t1["location_source"] == "telegram_location"
    assert inspect_photo(tg.files["exif"])[1] == pytest.approx(NEAR_NODE_2, abs=1e-4) and inspect_photo(tg.files["plain"])[1] is None
    assert haversine_km(12.942, 79.156, 12.9692, 79.145) == pytest.approx(3.25, abs=0.05)


def test_pending_photo_expires_and_bad_files_are_refused(tmp_path):
    now = [0.0]
    tg = FakeTelegram(files={"plain": jpeg(), "junk": b"this is not a picture", "gif": jpeg(fmt="GIF")})
    bot, store = make_bot(tmp_path, tg, clock=lambda: now[0])
    bot.tickets.clock = lambda: now[0]
    bot.handle_update(msg(ME, text="/language en"))
    bot.handle_update(msg(ME, photo=[{"file_id": "plain", "file_size": 900}]))
    assert bot.tickets.pending_count() == 1
    now[0] += 601
    assert bot.tickets.pending_count() == 0  # kept for 10 minutes only, and only in memory
    bot.handle_update(msg(ME, location={"latitude": 12.94, "longitude": 79.15}))
    assert "send a photo" in tg.texts()[-1] and store.read_complaints() == []
    now[0] += 30
    for fid, mime in (("junk", "image/jpeg"), ("gif", "image/png")):
        bot.handle_update(msg(ME, document={"file_id": fid, "mime_type": mime, "file_size": 100}))
        assert tg.texts()[-1].startswith("Only JPEG or PNG")
    bot.handle_update(msg(ME, document={"file_id": "plain", "mime_type": "application/pdf", "file_size": 100}))
    assert "/help" in tg.texts()[-1]  # not an image type: not downloaded at all
    bot.handle_update(msg(ME, photo=[{"file_id": "plain", "file_size": 11 * 1024 * 1024}]))
    assert "10 MB" in tg.texts()[-1]
    bot.handle_update(msg(ME, location={"latitude": 0, "longitude": 0}))
    assert "could not be read" in tg.texts()[-1]
    assert store.read_complaints() == [] and not (tmp_path / "citizen" / "uploads").exists()
    assert tg.calls.count("download") == 3  # the first photo and the two bad files; never the PDF or the oversized photo


# ------------------------------------------------------------------ the token and chat ids stay inside
def test_token_and_chat_ids_never_appear_in_logs_or_replies(tmp_path, caplog):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    text = ""
    with caplog.at_level(logging.DEBUG):
        for fail in ({}, {"sendMessage": (401, {"ok": False, "error_code": 401, "description": f"Unauthorized {TOKEN}"})},
                     {"sendMessage": httpx.ConnectError(f"cannot reach {url} chat {ME}")},
                     {"getFile": (400, {"ok": False, "error_code": 400, "description": f"file of chat {ME} not found"})},
                     {"sendVoice": (429, {"ok": False, "error_code": 429, "description": url, "parameters": {"retry_after": 3}})}):
            tg = FakeTelegram(files={"p": jpeg(NEAR_NODE_2), "v": b"OggS"}, fail=fail)
            bot, store = make_bot(tmp_path, tg, asr=FakeASR(Transcript(Q_EN, "en")), tts=FakeTTS())
            for content in ({"text": Q_EN}, {"voice": {"file_id": "v", "duration": 3}}, {"document": {"file_id": "p", "mime_type": "image/jpeg", "file_size": 9}},
                            {"text": "/start"}):
                bot.handle_update(msg(ME, **content))
            bot.handle_update(msg(STRANGER, text="hi"))
            text += json.dumps(bot.status()) + repr(bot.client) + repr(bot.settings) + json.dumps(store.read_complaints()) + "".join(t for _, t in tg.sent)
        text += caplog.text + "".join(str(r.__dict__) for r in caplog.records)
    assert "Telegram: bot token rejected" in text and "Telegram: network error (ConnectError)" in text and "Ticket #1" in text  # the haystack is real
    for secret in SECRETS:
        assert secret not in text, "a secret value leaked"
    assert Q_EN not in caplog.text and "Asha" not in text  # no message text and no name in the logs
    err = BotApiError("rejected", 400, 400)
    assert str(err) == "Telegram: the request was not accepted (HTTP 400, error_code 400)"


# ------------------------------------------------------------------ polling
def test_poller_skips_the_backlog_follows_the_offset_and_survives_errors():
    seen, sleeps = [], []
    tg = FakeTelegram(batches=[[{"update_id": 40, "message": {}}],  # waiting before the start: skipped, not answered late
                               [{"update_id": 41, "message": {"text": "a"}}, {"update_id": 42, "message": {"text": "boom"}}],
                               [{"update_id": 43, "message": {"text": "c"}}]])
    client = TelegramClient(TOKEN, transport=tg.transport)

    def handler(u):
        seen.append(u["update_id"])
        if u["message"].get("text") == "boom":
            raise RuntimeError("bad message")
        if u["update_id"] == 43:
            p.stop()

    p = Poller(client, handler, sleep=sleeps.append)
    p.start()
    p.join(5)
    assert seen == [41, 42, 43] and tg.offsets[:4] == ["-1", "41", "43", None][:len(tg.offsets[:4])] or tg.offsets[:3] == ["-1", "41", "43"]
    assert p.updates == 3 and p.errors == 1 and p.skipped == 1 and p.state == "stopped"


def test_poller_backs_off_on_network_errors_and_stops_on_a_rejected_token():
    sleeps = []
    net = FakeTelegram(fail={"getUpdates": httpx.ConnectError("down")})
    p = Poller(TelegramClient(TOKEN, transport=net.transport), lambda u: None, sleep=lambda s: (sleeps.append(s), len(sleeps) >= 5 and p.stop()))
    p.start()
    p.join(5)
    assert sleeps == [2.0, 5.0, 15.0, 30.0, 30.0] and p.errors == 5
    bad = FakeTelegram(fail={"getUpdates": (401, {"ok": False, "error_code": 401, "description": "Unauthorized"})})
    p2 = Poller(TelegramClient(TOKEN, transport=bad.transport), lambda u: None, sleep=sleeps.append)
    p2.start()
    p2.join(5)
    assert p2.state == "stopped: Telegram: bot token rejected, check TELEGRAM_BOT_TOKEN in .env" and bad.calls == ["getUpdates"]
    busy = FakeTelegram(fail={"getUpdates": (409, {"ok": False, "error_code": 409, "description": "Conflict"})})
    waits = []
    p3 = Poller(TelegramClient(TOKEN, transport=busy.transport), lambda u: None, sleep=lambda s: (waits.append(s), p3.stop()))
    p3.start()
    p3.join(5)
    assert waits == [30.0]  # another poller is running: wait, do not hammer


def test_client_download_stops_at_the_size_limit_and_never_shows_the_token():
    tg = FakeTelegram(files={"f": b"x" * 5000})
    c = TelegramClient(TOKEN, transport=tg.transport)
    assert c.download("f", 5000) == b"x" * 5000 and repr(c) == "TelegramClient()"
    with pytest.raises(BotApiError) as e:
        c.download("f", 4999)
    assert e.value.kind == "too_big" and TOKEN not in str(e.value)
    with pytest.raises(BotApiError) as e:
        c.download("missing", 10)
    assert e.value.kind == "token" or e.value.status == 404
    assert io.BytesIO(c.download("f", 10_000)).read(3) == b"xxx"
