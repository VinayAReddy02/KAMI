"""The citizen bot: decides who is answered, in which language, and routes each message to the right handler.

    update -> allowlist -> rate limit -> /start /help /language | text question | voice question | photo | location

Nothing in here logs a chat id, a name, a message text, audio or a position. The per-chat state (language, rate
window, a photo waiting for its location) lives in memory only.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter, deque

from .answer import Answerer, Reply, detect_language
from .telegram_in import BotApiError, TelegramClient
from .tickets import MAX_PHOTO_BYTES, TicketService
from .answer import CATEGORY_HI, PRIORITY_HI, _article

log = logging.getLogger("kami.citizen")
RATE_MAX, RATE_WINDOW = 10, 60.0  # requests per chat per minute
NOT_PUBLIC_EVERY = 3600.0  # the "not public" line is sent to an unknown chat at most once per hour
MAX_VOICE_SECONDS, MAX_VOICE_BYTES = 60, 2 * 1024 * 1024
MARK = {"en": "[KAMI demo: the schedule, wards and notices are fictional]", "hi": "[KAMI डेमो: समय-सारणी, वार्ड और सूचनाएँ काल्पनिक हैं]"}
NOT_PUBLIC = ("This is a demo bot of a college project. It is not a public service and does not answer here.\n"
              "यह एक कॉलेज प्रोजेक्ट का डेमो बॉट है। यह सार्वजनिक सेवा नहीं है।")
HELP = {
    "en": ("KAMI water demo bot (demo_fictional: the tanker schedule, the wards, the notices and the helpline number are invented).\n"
           "You can:\n"
           "- ask when the tanker comes: \"When will the tanker reach Ward 4?\"\n"
           "- ask about the notices: supply hours, charges, how to report a pipe, what the alert levels mean\n"
           "- ask what the sensors show in a ward: \"Is there a problem in Ward 3?\"\n"
           "- report a damaged pipe: send a photo and the location (the photo is stored for staff; it is not analysed automatically)\n"
           "Type or send a voice note (up to 60 seconds), in Hindi or English.\n"
           "/language hi, /language en or /language auto sets the reply language."),
    "hi": ("KAMI जल डेमो बॉट (demo_fictional: टैंकर की समय-सारणी, वार्ड, सूचनाएँ और हेल्पलाइन नंबर काल्पनिक हैं)।\n"
           "आप यह कर सकते हैं:\n"
           "- टैंकर का समय पूछें: \"वार्ड 4 में टैंकर कब आएगा?\"\n"
           "- सूचनाओं के बारे में पूछें: पानी का समय, शुल्क, पाइप की शिकायत कैसे करें, अलर्ट स्तर का अर्थ\n"
           "- पूछें कि वार्ड में सेंसर क्या दिखा रहे हैं: \"वार्ड 3 में कोई समस्या है क्या?\"\n"
           "- टूटी पाइप की शिकायत: फोटो और स्थान भेजें (फोटो कर्मचारियों के लिए रखी जाती है; इसका स्वचालित विश्लेषण नहीं होता)\n"
           "हिंदी या अंग्रेज़ी में लिखें या वॉइस नोट भेजें (60 सेकंड तक)।\n"
           "/language hi, /language en या /language auto से जवाब की भाषा चुनें।"),
}
TEXTS = {
    "rate": {"en": "Too many requests. Please wait a minute and try again.", "hi": "बहुत अधिक अनुरोध। कृपया एक मिनट रुककर फिर प्रयास करें।"},
    "lang_set": {"en": "Replies will be in English.", "hi": "अब जवाब हिंदी में मिलेंगे।"},
    "lang_auto": {"en": "Replies will follow the language of each message.", "hi": "अब जवाब आपके संदेश की भाषा में मिलेंगे।"},
    "lang_usage": {"en": "Use /language hi, /language en or /language auto.", "hi": "/language hi, /language en या /language auto लिखें।"},
    "voice_off": {"en": "Voice notes cannot be processed right now. Please type your question.", "hi": "अभी वॉइस नोट नहीं सुना जा सकता। कृपया अपना सवाल लिखकर भेजें।"},
    "voice_long": {"en": "The voice note is too long. Please keep it under 60 seconds.", "hi": "वॉइस नोट बहुत लंबा है। कृपया 60 सेकंड से छोटा भेजें।"},
    "voice_unclear": {"en": "Sorry, I could not understand the voice note. Please try again or type your question.",
                      "hi": "क्षमा करें, वॉइस नोट समझ नहीं आया। कृपया दोबारा भेजें या लिखकर पूछें।"},
    "heard": {"en": "I heard: ", "hi": "मैंने सुना: "},
    "need_location": {"en": "Photo received. Now please share the location of the place (attach > Location). I keep the photo for 10 minutes.",
                      "hi": "फोटो मिल गई। अब कृपया उस जगह का स्थान भेजें (अटैच > लोकेशन)। फोटो 10 मिनट तक रखी जाएगी।"},
    "need_photo": {"en": "Location received. Now please send a photo of the damaged pipe within 10 minutes.",
                   "hi": "स्थान मिल गया। अब कृपया 10 मिनट के भीतर टूटी पाइप की फोटो भेजें।"},
    "too_big": {"en": "The photo is larger than 10 MB. Please send a smaller one.", "hi": "फोटो 10 MB से बड़ी है। कृपया छोटी फोटो भेजें।"},
    "not_an_image": {"en": "Only JPEG or PNG photos can be accepted.", "hi": "केवल JPEG या PNG फोटो स्वीकार की जा सकती है।"},
    "bad_location": {"en": "The location could not be read. Please share it again.", "hi": "स्थान पढ़ा नहीं जा सका। कृपया दोबारा भेजें।"},
    "unsupported": {"en": "I can read text, voice notes, photos and locations. Send /help to see what you can ask.",
                    "hi": "मैं टेक्स्ट, वॉइस नोट, फोटो और स्थान समझ सकता हूँ। क्या पूछ सकते हैं, यह देखने के लिए /help भेजें।"},
    "error": {"en": "Sorry, something went wrong while preparing the answer. Please try again.", "hi": "क्षमा करें, जवाब तैयार करते समय कुछ गड़बड़ हुई। कृपया दोबारा प्रयास करें।"},
}


class RateLimiter:
    def __init__(self, limit: int = RATE_MAX, window: float = RATE_WINDOW):
        self.limit, self.window = limit, window
        self._hits: dict = {}

    def allow(self, key, now: float) -> bool:
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


def ticket_reply(t: dict, lang: str) -> str:
    """What the citizen is told about a new ticket: its number, the nearest sensor point and what the sensors there show
    now. No cause, and no claim that the photo was looked at."""
    hi = lang == "hi"
    if not t["in_demo_area"]:
        return (f"शिकायत दर्ज हो गई। टिकट #{t['id']}। यह स्थान डेमो क्षेत्र के बाहर है (निकटतम सेंसर बिंदु {t['nearest_node_name']} {t['distance_km']} किमी दूर है), "
                "इसलिए इसे किसी सेंसर से नहीं जोड़ा गया। फोटो कर्मचारियों के लिए रखी गई है; इसका स्वचालित विश्लेषण नहीं होता।" if hi else
                f"Report received. Ticket #{t['id']}. The place is outside the demo area (the nearest sensor point, {t['nearest_node_name']}, is {t['distance_km']} km away), "
                "so it is not linked to a sensor. The photo is stored for staff; it is not analysed automatically.")
    cat, pri = t["node_category"], t["node_priority"]
    if cat is None:
        state = "वहाँ के सेंसर की वर्तमान स्थिति अभी उपलब्ध नहीं है।" if hi else "The current sensor status there is not available right now."
    elif cat == "Normal":
        state = "वहाँ के सेंसर अभी कोई असामान्यता नहीं दिखा रहे हैं।" if hi else "Our sensors there currently show no anomaly."
    else:
        state = (f"वहाँ के सेंसर अभी {CATEGORY_HI[cat]} अलर्ट दिखा रहे हैं, प्राथमिकता {PRIORITY_HI[pri]}।" if hi
                 else f"Our sensors there currently show {_article(cat)} {cat} alert, priority {pri}.")
    if hi:
        return (f"शिकायत दर्ज हो गई। टिकट #{t['id']}। निकटतम सेंसर बिंदु: {t['node_name']} ({t['distance_km']} किमी)। {state} "
                "फोटो कर्मचारियों के लिए रखी गई है; इसका स्वचालित विश्लेषण नहीं होता।")
    return (f"Report received. Ticket #{t['id']}. Nearest sensor point: {t['node_name']} ({t['distance_km']} km). {state} "
            "The photo is stored for staff; it is not analysed automatically.")


class CitizenBot:
    def __init__(self, settings, client: TelegramClient, answerer: Answerer, tickets: TicketService, asr=None, tts=None, audio=None,
                 clock=time.time):
        self.settings, self.client, self.answerer, self.tickets = settings, client, answerer, tickets
        self.asr, self.tts, self.audio, self.clock = asr, tts, audio, clock
        self.counts: Counter = Counter()
        self._rate = RateLimiter()
        self._pref: dict = {}  # chat -> 'hi' | 'en' (set with /language)
        self._last: dict = {}  # chat -> language of the last question
        self._not_public: dict = {}
        self._rate_told: dict = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------- entry point (called by the poller thread)
    def handle_update(self, update: dict) -> None:
        msg = update.get("message") if isinstance(update, dict) else None
        chat = msg.get("chat") if isinstance(msg, dict) else None
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        if not isinstance(chat_id, int) or isinstance(chat_id, bool):
            return
        now = self.clock()
        if not self.settings.is_allowed(chat_id):
            self.counts["not_allowed"] += 1
            if now - self._not_public.get(chat_id, -1e12) >= NOT_PUBLIC_EVERY:
                self._not_public[chat_id] = now
                self._send(chat_id, NOT_PUBLIC, mark=None)
            return  # nothing else is read, downloaded or stored for this chat
        if not self._rate.allow(chat_id, now):
            self.counts["rate_limited"] += 1
            if now - self._rate_told.get(chat_id, -1e12) >= RATE_WINDOW:
                self._rate_told[chat_id] = now
                self._send(chat_id, TEXTS["rate"][self._lang(chat_id)], mark=None)
            return
        try:
            self._route(chat_id, msg)
        except Exception as e:  # never let one message end the bot; the citizen still gets a line
            self.counts["errors"] += 1
            log.warning("citizen bot: a message could not be answered (%s)", type(e).__name__)
            self._send(chat_id, TEXTS["error"][self._lang(chat_id)], mark=None)

    def _route(self, chat_id: int, msg: dict) -> None:
        text = msg.get("text")
        if isinstance(text, str) and text.strip():
            if text.strip().startswith("/"):
                return self._command(chat_id, text.strip())
            return self._question(chat_id, text.strip()[:500], voice=False)
        if isinstance(msg.get("voice"), dict):
            return self._voice(chat_id, msg["voice"])
        if isinstance(msg.get("location"), dict):
            self.counts["locations"] += 1
            loc = msg["location"]
            return self._ticket_outcome(chat_id, self.tickets.add_location(chat_id, loc.get("latitude"), loc.get("longitude")))
        photo = self._photo_file(msg)
        if photo is not None:
            return self._photo(chat_id, *photo)
        self.counts["unsupported"] += 1
        self._send(chat_id, TEXTS["unsupported"][self._lang(chat_id)])

    # ----------------------------------------------------------- commands and language
    def _lang(self, chat_id: int, detected: str | None = None) -> str:
        """The reply language: the chat's /language setting, else the language of this message, else the last one, else Hindi."""
        return self._pref.get(chat_id) or detected or self._last.get(chat_id) or "hi"

    def _command(self, chat_id: int, text: str) -> None:
        self.counts["commands"] += 1
        parts = text.split()
        cmd = parts[0].split("@")[0].lower()
        if cmd == "/language":
            arg = parts[1].lower() if len(parts) > 1 else ""
            if arg in ("hi", "en"):
                self._pref[chat_id] = arg
                return self._send(chat_id, TEXTS["lang_set"][arg], lang=arg)
            if arg == "auto":
                self._pref.pop(chat_id, None)
                return self._send(chat_id, TEXTS["lang_auto"]["en"] + "\n" + TEXTS["lang_auto"]["hi"], mark=None)
            return self._send(chat_id, TEXTS["lang_usage"]["en"] + "\n" + TEXTS["lang_usage"]["hi"], mark=None)
        if chat_id in self._pref:
            return self._send(chat_id, HELP[self._pref[chat_id]], mark=None)
        self._send(chat_id, HELP["hi"] + "\n\n" + HELP["en"], mark=None)  # /start, /help and anything else: say what the bot can do

    # ----------------------------------------------------------- questions
    def _question(self, chat_id: int, text: str, voice: bool, spoken_lang: str | None = None) -> None:
        self.counts["voice_questions" if voice else "text_questions"] += 1
        lang = self._lang(chat_id, spoken_lang or detect_language(text))
        self._last[chat_id] = lang
        self.client.send_chat_action(chat_id, "typing")
        reply: Reply = self.answerer.answer(text, lang)
        self.counts["no_information"] += reply.no_info
        self.counts["guard_fallbacks"] += reply.guard_fallback
        self.counts["answers_by_llm"] += reply.writer == "ollama"
        out = (TEXTS["heard"][lang] + text + "\n\n" if voice else "") + reply.text
        self._send(chat_id, out, lang=lang)
        if voice and self.tts is not None and self.audio is not None:
            try:
                pcm, rate = self.tts.synthesize(reply.text, lang)
                self.client.send_voice(chat_id, self.audio.pcm_to_ogg(pcm, rate))
                self.counts["voice_replies"] += 1
            except Exception as e:  # the text answer was already sent
                self.counts["voice_reply_failed"] += 1
                log.warning("citizen bot: the voice reply could not be made (%s)", type(e).__name__)

    def _voice(self, chat_id: int, voice: dict) -> None:
        lang = self._lang(chat_id)
        if self.asr is None or self.audio is None:
            self.counts["voice_unavailable"] += 1
            return self._send(chat_id, TEXTS["voice_off"][lang])
        if int(voice.get("duration") or 0) > MAX_VOICE_SECONDS or int(voice.get("file_size") or 0) > MAX_VOICE_BYTES:
            self.counts["voice_too_long"] += 1
            return self._send(chat_id, TEXTS["voice_long"][lang])
        try:
            path, _ = self.client.get_file(str(voice.get("file_id")))
            ogg = self.client.download(path, MAX_VOICE_BYTES)
        except BotApiError as e:
            self.counts["errors"] += 1
            log.warning("citizen bot: a voice note could not be fetched: %s", e)
            return self._send(chat_id, TEXTS["voice_long" if e.kind == "too_big" else "error"][lang])
        pcm = self.audio.ogg_to_pcm(ogg)  # 16 kHz mono; the audio is never written to disk
        del ogg
        if len(pcm) > (MAX_VOICE_SECONDS + 1) * 16000:
            self.counts["voice_too_long"] += 1
            return self._send(chat_id, TEXTS["voice_long"][lang])
        heard = self.asr.transcribe(pcm, self._pref.get(chat_id))
        if not heard.text.strip():
            self.counts["voice_unclear"] += 1
            return self._send(chat_id, TEXTS["voice_unclear"][lang])
        self._question(chat_id, heard.text.strip()[:500], voice=True, spoken_lang=heard.language)

    # ----------------------------------------------------------- pipe-damage reports
    @staticmethod
    def _photo_file(msg: dict) -> tuple[str, int] | None:
        """(file id, size) of a photo, or of an image sent as a file (which keeps its EXIF data)."""
        sizes = msg.get("photo")
        if isinstance(sizes, list) and sizes:
            best = max((s for s in sizes if isinstance(s, dict)), key=lambda s: int(s.get("file_size") or s.get("width", 0) * s.get("height", 0)), default=None)
            if best and isinstance(best.get("file_id"), str):
                return best["file_id"], int(best.get("file_size") or 0)
        doc = msg.get("document")
        if isinstance(doc, dict) and str(doc.get("mime_type", "")).lower() in ("image/jpeg", "image/png") and isinstance(doc.get("file_id"), str):
            return doc["file_id"], int(doc.get("file_size") or 0)
        return None

    def _photo(self, chat_id: int, file_id: str, size: int) -> None:
        self.counts["photos"] += 1
        lang = self._lang(chat_id)
        if size > MAX_PHOTO_BYTES:
            return self._send(chat_id, TEXTS["too_big"][lang])
        try:
            path, _ = self.client.get_file(file_id)
            data = self.client.download(path, MAX_PHOTO_BYTES)
        except BotApiError as e:
            self.counts["errors"] += 1
            log.warning("citizen bot: a photo could not be fetched: %s", e)
            return self._send(chat_id, TEXTS["too_big" if e.kind == "too_big" else "error"][lang])
        self._ticket_outcome(chat_id, self.tickets.add_photo(chat_id, data))

    def _ticket_outcome(self, chat_id: int, out) -> None:
        lang = self._lang(chat_id)
        if out.kind == "ticket":
            self.counts["tickets"] += 1
            return self._send(chat_id, ticket_reply(out.ticket, lang), lang=lang)
        self._send(chat_id, TEXTS[out.reason if out.kind == "rejected" else out.kind][lang])

    # ----------------------------------------------------------- sending and status
    def _send(self, chat_id: int, text: str, lang: str | None = None, mark: str | None = "auto") -> None:
        if mark == "auto":
            text = f"{text}\n{MARK[lang or self._lang(chat_id)]}"
        try:
            self.client.send_message(chat_id, text[:3900])
            self.counts["replies"] += 1
        except BotApiError as e:
            self.counts["send_failed"] += 1
            log.warning("citizen bot: a reply could not be sent: %s", e)

    def status(self) -> dict:
        """Counts only: no chat id, no text."""
        return {"counts": dict(self.counts), "allowed_chats": self.settings.allowed_count, "pending_reports": self.tickets.pending_count(),
                "voice": self.asr is not None, "llm": getattr(self.answerer.llm, "model", None)}
