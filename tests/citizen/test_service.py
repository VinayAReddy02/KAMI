"""Citizen interface: off by default, the assembled service with fakes, the API endpoints (C2, C5, C7)."""
import json
import logging
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from kami.api.app import create_app
from kami.citizen.service import SpeechStack, build_citizen, ollama_ready
from kami.citizen.settings import load_citizen_settings
from kami.citizen.speech import Transcript
from kami.citizen.tickets import public_view
from kami.ingest.bus import InProcessBus
from kami.live.system import build_live
from kami.runtime import Stack
from kami.store import SqliteStore

from .helpers import FRIEND, ME, SECRETS, TOKEN, FakeASR, FakeAudio, FakeOllama, FakeTelegram, FakeTranslator, FakeTTS, env, jpeg, msg


def new_stack() -> Stack:
    return Stack.create(mode="fallback", store=SqliteStore(":memory:"), bus=InProcessBus())


def fakes() -> SpeechStack:
    return SpeechStack(FakeASR(Transcript("When will the water tanker reach Ward 4?", "en")), FakeTranslator(), FakeTTS(), FakeAudio(), ready=True)


def wait_for(cond, seconds=5.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


# ------------------------------------------------------------------ off by default
def test_off_by_default_nothing_polls_without_the_enable_setting(tmp_path, monkeypatch):
    tg = FakeTelegram(batches=[[msg(ME, 5, text="hello")]])
    # 1. the caller does not allow inbound handling (every check, test and launch() default): off even with complete settings
    svc = build_citizen(new_stack(), None, allow_inbound=False, env=env(tmp_path), transport=tg.transport)
    svc.start()
    assert not svc.enabled and svc.bot is None and svc.poller is None and "off for this run" in svc.detail
    # 2. the caller allows it but KAMI_CITIZEN_ENABLE is not 1
    for value in (None, "0", "yes", ""):
        off = build_citizen(new_stack(), None, allow_inbound=True, env=env(tmp_path, KAMI_CITIZEN_ENABLE=value), transport=tg.transport, speech=fakes())
        off.start()
        assert not off.enabled and off.status() == {"enabled": False, "detail": "KAMI_CITIZEN_ENABLE is not 1", "data": "demo_fictional"}
    # 3. switched on but a setting is missing or malformed: off, and the reason names the setting only
    for name, value in (("TELEGRAM_BOT_TOKEN", None), ("TELEGRAM_CHAT_ID", None), ("TELEGRAM_BOT_TOKEN", "not-a-token"), ("CITIZEN_ALLOWED_CHAT_IDS", "12345,@someone")):
        bad = build_citizen(new_stack(), None, allow_inbound=True, env=env(tmp_path, **{name: value}), transport=tg.transport, speech=fakes())
        assert not bad.enabled and name in bad.detail and not any(s in bad.detail for s in SECRETS)
    # 4. the live system built the default way never polls, even when the environment is complete
    for k, v in env(tmp_path).items():
        monkeypatch.setenv(k, v)
    stack = new_stack()
    build_live(stack, speed=0)
    assert stack.extras["citizen"].enabled is False
    stack.extras["citizen"].start()
    stack.extras["notifications"].stop()
    time.sleep(0.1)
    assert tg.calls == [] and tg.sent == []  # not one request went to (the stand-in for) Telegram


def test_settings_keep_secrets_out_of_their_text_forms(tmp_path):
    s = load_citizen_settings(env(tmp_path))
    assert s.ready and s.is_allowed(ME) and s.is_allowed(FRIEND) and not s.is_allowed(1) and not s.is_allowed(str(ME)) and s.allowed_count == 2
    assert s.token == TOKEN and not any(v in repr(s) + str(s) + s.describe() for v in SECRETS)
    assert (s.ollama_model, s.ollama_url, s.device) == ("llama3.2:3b", "http://127.0.0.1:11434", "cuda")
    assert load_citizen_settings(env(tmp_path, CITIZEN_DEVICE="CPU", OLLAMA_MODEL="qwen2.5:3b")).device == "cpu"


# ------------------------------------------------------------------ the assembled service, with fakes
def test_enabled_service_polls_answers_and_stops(tmp_path, caplog):
    tg = FakeTelegram(batches=[[], [msg(ME, 11, text="When will the water tanker reach Ward 4?"), msg(ME, 12, voice={"file_id": "v", "duration": 3})]],
                      files={"v": b"OggS"})
    llm = FakeOllama("Tanker TKR-10 is scheduled for Ward 4 tomorrow, 8 Jan, 06:00-08:00.")
    stack = new_stack()
    with caplog.at_level(logging.DEBUG):
        svc = build_citizen(stack, None, allow_inbound=True, env=env(tmp_path), transport=tg.transport, speech=fakes(), llm_transport=llm.transport)
        assert svc.enabled and svc.status()["polling"] == "stopped"
        svc.start()
        assert wait_for(lambda: len(tg.sent) >= 2 and len(tg.voices) >= 1)
        svc.stop()
    st = svc.status()
    assert st["enabled"] and st["counts"]["text_questions"] == 1 and st["counts"]["voice_questions"] == 1 and st["counts"]["voice_replies"] == 1
    assert st["allowed_chats"] == 2 and st["llm"] == "llama3.2:3b" and st["models"]["asr"] == "fake-asr" and st["models"]["speech_ready"] is True
    assert st["data"] == "demo_fictional" and len(llm.prompts) == 2  # both answers were written by the (stand-in) local LLM
    assert not any(s in json.dumps(st) + caplog.text for s in SECRETS)
    assert "Citizen bot: on (2 allowed chat(s))" in caplog.text


def test_without_ollama_the_template_writer_is_used(tmp_path, caplog):
    tg = FakeTelegram(batches=[[], [msg(ME, 11, text="When will the water tanker reach Ward 4?")]])
    dead = httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("no ollama")))
    with caplog.at_level(logging.WARNING):
        svc = build_citizen(new_stack(), None, allow_inbound=True, env=env(tmp_path), transport=tg.transport, speech=fakes(), llm_transport=dead)
    svc.start()
    assert wait_for(lambda: len(tg.sent) >= 1)
    svc.stop()
    assert svc.status()["llm"] is None and "Status: scheduled." in tg.sent[0][1] and "Ollama or its model is not available" in caplog.text
    other = FakeOllama("x", model="some-other-model")
    assert not ollama_ready("http://127.0.0.1:11434", "llama3.2:3b", other.transport) and ollama_ready("http://127.0.0.1:11434", "some-other-model", other.transport)
    assert not ollama_ready("https://example.org", "llama3.2:3b", other.transport)  # never a remote server


def test_speech_that_fails_to_load_leaves_text_answers_working(tmp_path):
    class Broken(FakeASR):
        def load(self):
            raise RuntimeError("no GPU")

    speech = SpeechStack(Broken(Transcript("x", "en")), FakeTranslator(), FakeTTS(), FakeAudio())
    tg = FakeTelegram(batches=[[], [msg(ME, 11, voice={"file_id": "v", "duration": 3}), msg(ME, 12, text="When will the water tanker reach Ward 4?")]], files={"v": b"OggS"})
    svc = build_citizen(new_stack(), None, allow_inbound=True, env=env(tmp_path), transport=tg.transport, speech=speech, llm_transport=FakeOllama("x").transport)
    svc.start()
    assert wait_for(lambda: len(tg.sent) >= 2)
    svc.stop()
    assert "लिखकर भेजें" in tg.sent[0][1] and tg.sent[1][1].startswith("Ward 4")  # voice is refused politely, text is answered
    assert svc.status()["models"]["speech_ready"] is False and "RuntimeError" in svc.status()["models"]["speech_problem"]


# ------------------------------------------------------------------ API
def test_complaints_api_lists_tickets_without_file_names_and_serves_the_small_copy(tmp_path):
    stack = new_stack()
    app = create_app(stack)
    build_live(stack, speed=0)
    svc = stack.extras["citizen"]
    with TestClient(app) as c:
        assert c.get("/complaints").json() == [] and c.get("/complaints/1/thumb").status_code == 404
        st = c.get("/citizen/status").json()
        assert st == {"enabled": False, "detail": "off for this run (checks and tests never poll)", "data": "demo_fictional"}
        assert svc.tickets.add_photo("chat-a", jpeg()).kind == "need_location"
        out = svc.tickets.add_location("chat-a", 12.9425, 79.1565)
        assert out.kind == "ticket" and out.ticket["node_id"] == "node-2"
        svc.tickets.add_photo("chat-b", jpeg((12.9692, 79.1451)))
        rows = c.get("/complaints").json()
        assert [r["id"] for r in rows] == [2, 1] and rows[0]["node_name"] == "Katpadi Intake" and rows[1]["node_name"] == "Gandhi Nagar Tank"
        assert all("photo_file" not in r and "thumb_file" not in r and r["thumb_url"] == f"/complaints/{r['id']}/thumb" for r in rows)
        assert rows[1] == public_view(out.ticket) and rows[1]["photo_analysed"] is False and rows[1]["status"] == "open"
        img = c.get(rows[1]["thumb_url"])
        assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg" and img.content[:3] == b"\xff\xd8\xff" and len(img.content) < 40_000
        assert c.get("/complaints/99/thumb").status_code == 404 and c.get("/complaints/abc/thumb").status_code == 422
        assert c.get("/complaints", params={"limit": 1}).json()[0]["id"] == 2
    stack.extras["notifications"].stop()


def test_a_real_request_is_refused_and_would_fail_the_test(no_real_http, tmp_path):
    from kami.citizen.answer import LLMUnavailable, OllamaWriter, Retrieved
    from kami.citizen.telegram_in import TelegramClient

    with pytest.raises(AssertionError, match="real HTTP request"):
        TelegramClient(TOKEN).get_updates(None, poll_seconds=0)  # a client without a mock transport cannot reach Telegram
    with pytest.raises(AssertionError, match="real HTTP request"):
        OllamaWriter("llama3.2:3b").write("q", Retrieved("faq", notices=[{"title": "t", "text": "x"}]), "en")  # nor a local Ollama
    with pytest.raises(AssertionError, match="real HTTP request"):
        httpx.get("https://huggingface.co/api/models/x")  # nor a model hub
    assert no_real_http == ["POST api.telegram.org", "POST 127.0.0.1", "GET huggingface.co"]
    no_real_http.clear()  # the three attempts above were the point of this test
    assert LLMUnavailable is not None
