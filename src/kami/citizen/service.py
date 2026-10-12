"""Assembles the citizen interface for a running system and keeps it off unless it is explicitly allowed.

    build_citizen(stack, live, allow_inbound=False)   -> the ticket service is always there (GET /complaints);
                                                         the bot, the poller and the models only when inbound handling
                                                         is allowed by the caller AND switched on in the settings.

Callers that allow inbound handling: scripts/run_demo.py (normal start) and scripts/run_citizen_bot.py. Every check,
test and launch() default does not, so they never poll Telegram, never call Ollama and never load a speech model.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime

import httpx

from .answer import Answerer, NoticeIndex, OllamaWriter
from .bot import CitizenBot
from .data import ScheduleService
from .settings import CitizenSettings, load_citizen_settings, work_dir
from .telegram_in import Poller, TelegramClient
from .tickets import TicketService

log = logging.getLogger("kami.citizen")
# the models chosen on the validation questions in Round 6 (results/citizen/model_selection.md)
DEFAULT_ASR = "faster-whisper:large-v3-turbo"
DEFAULT_NMT = "nllb"
DEFAULT_TTS = "piper"


@dataclass
class SpeechStack:
    """The local language models. Any of them may be None (then that feature is off and the bot says so)."""

    asr: object = None
    translator: object = None
    tts: object = None
    audio: object = None
    ready: bool = False
    problem: str | None = None

    def names(self) -> dict:
        return {k: getattr(getattr(self, k), "name", None) for k in ("asr", "translator", "tts")}

    def warm_up(self) -> None:
        """Load every model once (blocking). Called in a background thread at start-up."""
        try:
            for m in (self.asr, self.translator, self.tts):
                if m is not None:
                    m.load()
            self.ready = True
        except Exception as e:
            self.problem = f"speech models could not be loaded ({type(e).__name__})"
            log.warning("citizen bot: %s; voice and Hindi notices are off", self.problem)


def local_speech(settings: CitizenSettings) -> SpeechStack:
    """The real local models (GPU if usable). Importing the heavy packages happens only here and only when called."""
    from .audio import FfmpegAudio
    from .speech import FasterWhisperASR
    from .translate import MarianTranslator, NllbTranslator
    from .tts import MmsTTS, PiperTTS

    asr_name = settings.asr or DEFAULT_ASR
    tts_name = settings.tts or DEFAULT_TTS
    from .data import speech_vocabulary

    asr = FasterWhisperASR(asr_name.split(":", 1)[1] if ":" in asr_name else asr_name, settings.device, hotwords=speech_vocabulary())
    translator = NllbTranslator(device=settings.device) if DEFAULT_NMT == "nllb" else MarianTranslator(settings.device)
    tts = MmsTTS(device=settings.device) if tts_name.startswith("mms") else PiperTTS()
    return SpeechStack(asr, translator, tts, FfmpegAudio())


def ollama_ready(url: str, model: str, transport=None) -> bool:
    """True if a local Ollama answers and has the model. Never raises."""
    try:
        if httpx.URL(url).host not in ("127.0.0.1", "localhost", "::1"):
            return False
        with httpx.Client(timeout=5.0, transport=transport) as c:
            r = c.get(url.rstrip("/") + "/api/tags")
        names = {m.get("name") for m in r.json().get("models", [])} if r.status_code == 200 else set()
        return model in names or f"{model}:latest" in names
    except Exception:
        return False


class CitizenService:
    def __init__(self, settings: CitizenSettings, tickets: TicketService, detail: str, bot: CitizenBot | None = None, poller: Poller | None = None,
                 speech: SpeechStack | None = None):
        self.settings, self.tickets, self.detail = settings, tickets, detail
        self.bot, self.poller, self.speech = bot, poller, speech

    @property
    def enabled(self) -> bool:
        return self.poller is not None

    def start(self) -> None:
        if self.speech is not None and not self.speech.ready:
            threading.Thread(target=self._warm, name="kami-citizen-warmup", daemon=True).start()
        if self.poller is not None:
            self.poller.start()

    def _warm(self) -> None:
        self.speech.warm_up()
        if self.bot is not None and self.speech.ready:  # voice is offered only once the models are loaded
            self.bot.asr, self.bot.tts, self.bot.audio = self.speech.asr, self.speech.tts, self.speech.audio
            self.bot.answerer.translator = self.speech.translator

    def stop(self) -> None:
        if self.poller is not None:
            self.poller.stop()

    def status(self) -> dict:
        """For GET /citizen/status: no token, no chat id, no text."""
        out = {"enabled": self.enabled, "detail": self.detail, "data": "demo_fictional"}
        if self.enabled:
            out.update(self.bot.status())
            out["polling"] = self.poller.state
            out["models"] = {**(self.speech.names() if self.speech else {}), "speech_ready": bool(self.speech and self.speech.ready),
                             "speech_problem": self.speech.problem if self.speech else None}
        return out


def build_citizen(stack, live=None, allow_inbound: bool = False, env=None, transport=None, speech: SpeechStack | None = None,
                  llm_transport=None) -> CitizenService:
    """`live` is the running LiveSystem (replay clock and node states) or None for a bot without the sensor pipeline."""
    from ..live.system import load_nodes_config

    settings = load_citizen_settings(env)
    proc = live.processor if live is not None else None

    def node_state(node_id):
        return proc.latest(node_id) if proc is not None else None

    def open_alert(node_id):
        alerts = proc.list_alerts(node=node_id, status="active", limit=1) if proc is not None else []
        return alerts[0] if alerts else None

    def clock() -> datetime:
        ts = live.fleet.last_ts if live is not None else None
        return datetime.fromisoformat(ts) if ts else datetime.now()

    tickets = TicketService(stack.store, load_nodes_config()["nodes"], work_dir(env) / "uploads", node_state,
                            replay_ts=lambda: live.fleet.last_ts if live is not None else None)
    if not allow_inbound:
        return CitizenService(settings, tickets, "off for this run (checks and tests never poll)")
    if not settings.ready:
        (log.warning if settings.enable_requested else log.info)("Citizen bot: off (%s)", settings.describe())
        return CitizenService(settings, tickets, settings.describe())
    if speech is None:
        try:
            speech = local_speech(settings)
        except Exception as e:  # packages of requirements-citizen.txt not installed: text questions still work
            speech = SpeechStack(problem=f"speech packages not available ({type(e).__name__})")
            log.warning("citizen bot: %s; voice and Hindi notices are off", speech.problem)
    llm = None
    if ollama_ready(settings.ollama_url, settings.ollama_model, llm_transport):
        llm = OllamaWriter(settings.ollama_model, settings.ollama_url, transport=llm_transport)
    else:
        log.warning("citizen bot: Ollama or its model is not available; answers use the fixed sentences")
    answerer = Answerer(ScheduleService(clock=clock, open_alert=open_alert), NoticeIndex(), speech.translator if speech.ready else None, llm, node_state)
    client = TelegramClient(settings.token, transport=transport)
    ready = speech.ready
    bot = CitizenBot(settings, client, answerer, tickets, speech.asr if ready else None, speech.tts if ready else None, speech.audio if ready else None)
    log.warning("Citizen bot: on (%d allowed chat(s))", settings.allowed_count)
    return CitizenService(settings, tickets, settings.describe(), bot, Poller(client, bot.handle_update), speech)
