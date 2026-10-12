"""Test doubles for the citizen interface. All values are obviously fake; nothing here talks to a network."""
import io
import json
from datetime import datetime
from urllib.parse import parse_qs

import httpx
import numpy as np
from PIL import Image

from kami.citizen.answer import Answerer, NoticeIndex, OllamaWriter
from kami.citizen.bot import CitizenBot
from kami.citizen.data import ScheduleService
from kami.citizen.settings import load_citizen_settings
from kami.citizen.speech import FakeASR
from kami.citizen.telegram_in import TelegramClient
from kami.citizen.tickets import TicketService
from kami.citizen.translate import FakeTranslator
from kami.citizen.tts import FakeTTS
from kami.store import SqliteStore

TOKEN = "123456:CITIZEN-TEST-TOKEN"
ME, FRIEND, STRANGER = 7700112233, 7700445566, 9900000001
SECRETS = (TOKEN, TOKEN.split(":")[1], str(ME), str(FRIEND), str(STRANGER))
NOON = datetime(2018, 1, 7, 11, 0)  # the fixed replay time of the tests
NODES = [{"id": f"node-{i}", "name": n, "lat": la, "lon": lo} for i, (n, la, lo) in enumerate(
    [("Katpadi Intake", 12.9692, 79.145), ("Gandhi Nagar Tank", 12.942, 79.156), ("Sathuvachari Main", 12.944, 79.116)], start=1)]


def env(tmp_path, **over):
    e = {"KAMI_CITIZEN_ENABLE": "1", "TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": str(ME), "CITIZEN_ALLOWED_CHAT_IDS": str(FRIEND),
         "KAMI_NOTIFY_ENV_FILE": str(tmp_path / "no_such.env"), "KAMI_CITIZEN_DIR": str(tmp_path / "citizen")}
    e.update(over)
    return {k: v for k, v in e.items() if v is not None}


class FakeTelegram:
    """Scripted stand-in for api.telegram.org: serves getUpdates batches and files, records what the bot sends."""

    def __init__(self, batches=(), files: dict | None = None, fail: dict | None = None):
        self.batches, self.files, self.fail = [list(b) for b in batches], dict(files or {}), dict(fail or {})
        self.sent: list[tuple[int, str]] = []
        self.voices: list[tuple[int, int]] = []
        self.calls: list[str] = []
        self.offsets: list = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/file/bot" in path:
            self.calls.append("download")
            name = path.rsplit("/", 1)[1]
            return httpx.Response(200, content=self.files[name]) if name in self.files else httpx.Response(404, json={"ok": False, "error_code": 404})
        method = path.rsplit("/", 1)[1]
        self.calls.append(method)
        if method in self.fail:
            a = self.fail[method]
            if isinstance(a, Exception):
                raise a
            return httpx.Response(a[0], json=a[1])
        body = request.content
        form = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "ignore")).items()} if b"multipart" not in request.headers.get("content-type", "").encode() else {}
        if method == "getUpdates":
            self.offsets.append(form.get("offset"))
            return httpx.Response(200, json={"ok": True, "result": self.batches.pop(0) if self.batches else []})
        if method == "getFile":
            fid = form["file_id"]
            return httpx.Response(200, json={"ok": True, "result": {"file_path": fid, "file_size": len(self.files.get(fid, b""))}})
        if method == "sendMessage":
            self.sent.append((int(form["chat_id"]), form["text"]))
        if method == "sendVoice":
            chat = int(body.split(b'name="chat_id"')[1].split(b"\r\n")[2])
            self.voices.append((chat, len(body)))
        return httpx.Response(200, json={"ok": True, "result": {}})

    @property
    def transport(self):
        return httpx.MockTransport(self)

    def texts(self, chat: int | None = None) -> list[str]:
        return [t for c, t in self.sent if chat is None or c == chat]


class FakeAudio:
    """Stands in for ffmpeg: 'decodes' any bytes to one second of silence and 'encodes' to a short byte string."""

    def ogg_to_pcm(self, ogg: bytes):
        return np.zeros(16000, np.float32)

    def pcm_to_ogg(self, pcm, rate: int) -> bytes:
        return b"OggS-fake-" + str(len(pcm)).encode()


class FakeOllama:
    """Scripted stand-in for a local Ollama server: every chat request gets the next prepared answer."""

    def __init__(self, *answers, model="llama3.2:3b"):
        self.answers, self.model, self.prompts = list(answers), model, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": self.model}]})
        body = json.loads(request.content)
        self.prompts.append(body)
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return httpx.Response(200, json={"message": {"role": "assistant", "content": a}})

    @property
    def transport(self):
        return httpx.MockTransport(self)

    def writer(self) -> OllamaWriter:
        return OllamaWriter(self.model, transport=self.transport)


def schedule(alerts: dict | None = None, now: datetime = NOON) -> ScheduleService:
    """The real demo schedule at a fixed replay time; `alerts` = {node_id: {"priority": ...}}."""
    return ScheduleService(clock=lambda: now, open_alert=lambda node_id: (alerts or {}).get(node_id))


def answerer(llm=None, translator=None, states: dict | None = None, alerts: dict | None = None) -> Answerer:
    return Answerer(schedule(alerts), NoticeIndex(), translator, llm, node_state=lambda node_id: (states or {}).get(node_id))


def make_bot(tmp_path, tg: FakeTelegram, llm=None, translator=None, asr=None, tts=None, states=None, clock=None, **over):
    settings = load_citizen_settings(env(tmp_path, **over))
    store = SqliteStore(":memory:")
    store.init()
    tickets = TicketService(store, NODES, tmp_path / "citizen" / "uploads", node_state=lambda node_id: (states or {}).get(node_id),
                            replay_ts=lambda: "2018-01-07T11:00:00")
    kw = {"clock": clock} if clock else {}
    bot = CitizenBot(settings, TelegramClient(settings.token, transport=tg.transport), answerer(llm, translator, states), tickets,
                     asr, tts, FakeAudio() if (asr or tts) else None, **kw)
    return bot, store


def msg(chat: int, update_id: int = 1, **content) -> dict:
    return {"update_id": update_id, "message": {"message_id": update_id, "chat": {"id": chat, "type": "private", "first_name": "Asha"}, **content}}


def jpeg(gps: tuple[float, float] | None = None, size=(640, 480), fmt="JPEG") -> bytes:
    """A generated test picture (plain colour blocks), optionally with a GPS position in its EXIF data."""
    im = Image.new("RGB", size, (90, 120, 150))
    im.paste((200, 180, 60), (40, 40, size[0] // 2, size[1] // 2))
    buf = io.BytesIO()
    if gps is None or fmt != "JPEG":
        im.save(buf, fmt)
        return buf.getvalue()

    def dms(v: float):
        v = abs(v)
        d, m = int(v), int((v - int(v)) * 60)
        return (float(d), float(m), round((v - d - m / 60) * 3600, 4))

    exif = Image.Exif()
    exif[0x8825] = {1: "N" if gps[0] >= 0 else "S", 2: dms(gps[0]), 3: "E" if gps[1] >= 0 else "W", 4: dms(gps[1])}
    im.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


__all__ = ["FakeASR", "FakeTTS", "FakeTranslator"]
