"""Understanding, retrieval, answer writers and the grounding guard of the citizen interface.

    understand()   rules: intent (schedule, ward_status, faq), ward, day. Works on Hindi (Devanagari or Latin letters)
                   and English text directly, so a schedule question never depends on machine translation.
    retrieval      schedule: structured lookup in the schedule service (the time always comes from the data);
                   notices: TF-IDF over the English notices (Hindi questions are translated to English first).
    writers        TemplateWriter: fixed sentences in English and Hindi.
                   OllamaWriter: a local LLM writes a short English answer from the retrieved records only.
    guard          every time, date, ward, tanker id and number in an LLM answer must be in the retrieved records, the
                   day and status words must match them, and no cause word may appear; otherwise the template answer
                   is used and the event is counted as a guard fallback.
The LLM never translates. Hindi replies to LLM answers and notices come from the translation model, and the numbers
must survive that translation, otherwise the Hindi template (or the English text with a note) is used.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import httpx
import numpy as np

from .data import ALERT_NOTE, DAY_WORD, Delivery, ScheduleService, Ward, load_notices

# ---------------------------------------------------------------- language and normalisation
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
# Hindi written in Latin letters: one clear Hindi word is enough, or two of the short words that are also English
HINDI_LATIN = {"kab", "kal", "aaj", "parso", "mein", "hain", "kya", "aayega", "ayega", "aaega", "aayegi", "paani", "pani", "kitne", "baje", "kahan",
               "nahi", "nahin", "kyun", "kaise", "gaya", "aaya", "chahiye", "kitna", "batao", "bataiye", "wala", "abhi", "pahuncha", "pahunchega",
               "milega", "hoga", "kaun", "raha", "rahi", "karein", "karna", "jama", "bijli", "shikayat", "samasya", "dikkat"}
HINDI_LATIN_WEAK = {"hai", "ka", "ki", "ke", "ko", "se", "tha", "thi", "sa", "aa", "ek", "ya"}


def normalise(text: str) -> str:
    """Lower case, ASCII digits, punctuation to spaces (Devanagari signs are kept)."""
    t = str(text).translate(_DIGITS).lower()
    t = re.sub(r"[^\wऀ-ॿ:.-]+", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def detect_language(text: str) -> str:
    """'hi' for Devanagari text or Hindi written in Latin letters, else 'en'."""
    if DEVANAGARI.search(text):
        return "hi"
    words = set(re.findall(r"[a-z]+", text.lower()))
    return "hi" if words & HINDI_LATIN or len(words & HINDI_LATIN_WEAK) >= 2 else "en"


# ---------------------------------------------------------------- understanding (rules)
NUMBER_WORDS = {1: ("one", "first", "ek", "pehla", "एक", "पहला", "पहले"), 2: ("two", "second", "do", "doosra", "dusra", "दो", "दूसरा", "दूसरे"),
                3: ("three", "third", "teen", "teesra", "तीन", "तीसरा", "तीसरे"), 4: ("four", "fourth", "char", "chaar", "chautha", "चार", "चौथा", "चौथे"),
                5: ("five", "fifth", "paanch", "panch", "पांच", "पाँच", "पांचवां", "पाँचवाँ", "पांचवें"), 6: ("six", "sixth", "chhe", "chhah", "che", "छह", "छः", "छे", "छठा", "छठे"),
                7: ("seven", "seventh", "saat", "sat", "सात", "सातवां", "सातवें"), 8: ("eight", "eighth", "aath", "ath", "आठ", "आठवां", "आठवें"),
                9: ("nine", "nau", "नौ"), 10: ("ten", "das", "दस"), 11: ("eleven", "gyarah", "ग्यारह"), 12: ("twelve", "barah", "बारह"),
                15: ("fifteen", "pandrah", "पंद्रह", "पन्द्रह", "पंदरह", "पंधरह"), 20: ("twenty", "bees", "बीस")}
_NUM = {w: n for n, ws in NUMBER_WORDS.items() for w in ws}
WARD_WORD = r"(?:ward|vard|waard|word|wad|war|वार्ड|वॉर्ड|वार्ड़|वाड|वॉड|बाड|बार्ड|वर्ड)"  # incl. what speech recognition makes of it
_NUM_ALT = "|".join(sorted(map(re.escape, _NUM), key=len, reverse=True))
_NUMTOK = rf"(\d{{1,3}}|{_NUM_ALT})"
_FILL = r"(?:\s*(?:no|number|num|nambar|sankhya|नंबर|नम्बर|संख्या|क्रमांक|no\.))?"
WARD_AFTER = re.compile(rf"(?<![\wऀ-ॿ]){WARD_WORD}{_FILL}\s*[-:]?\s*{_NUMTOK}(?![\wऀ-ॿ])")
_AMBIGUOUS = {"do", "sat", "che", "char", "das", "ath", "one", "ek"}  # also ordinary words: not read as a number in front of "ward"
_NUM_ALT_SAFE = "|".join(sorted((re.escape(w) for w in _NUM if w not in _AMBIGUOUS), key=len, reverse=True))
WARD_BEFORE = re.compile(rf"(?<![\wऀ-ॿ])(\d{{1,3}}|{_NUM_ALT_SAFE}){_FILL}\s*{WARD_WORD}(?![\wऀ-ॿ])")

TANKER = ("tanker", "tankar", "tankr", "tenkar", "lorry", "टैंकर", "टेंकर", "टैन्कर", "टंकर", "water truck", "पानी की गाड़ी", "pani ki gaadi", "pani ki gadi")
TANKER_HEARD = re.compile(r"(?<![\w\u0900-\u097F])[टतपठ][ैेॅ]?[ंँनण]?्?\s?कर(?![\w\u0900-\u097F])")  # how "टैंकर" comes out of speech recognition
TIME_CUE = ("when", "what time", "which time", "timing", "schedule", "arrive", "arrival", "reach", "come", "coming", "status", "where is", "has the", "did the",
            "delivered", "late", "delay", "kab", "kitne baje", "aayega", "ayega", "aaega", "aayegi", "pahuncha", "pahunchega", "kahan", "aaya", "aa gaya",
            "कब", "कितने बजे", "आएगा", "आयेगा", "आएगी", "आयेगी", "पहुंचेगा", "पहुँचेगा", "पहुंचा", "पहुँचा", "कहां", "कहाँ", "आया", "आ गया", "समय", "देरी", "लेट")
FAQ_CUE = ("free", "charge", "cost", "price", "fee", "pay", "money", "paise", "paisa", "rupee", "litre", "liter", "container", "bucket", "extra", "additional",
           "request", "how does", "how do", "how much", "पैसे", "पैसा", "शुल्क", "मुफ्त", "मुफ़्त", "लीटर", "बर्तन", "बाल्टी", "अतिरिक्त", "कितना पानी", "kitna pani", "kitna paani")
STATUS_CUE = ("alert", "problem", "issue", "anomaly", "fault", "sensor", "network status", "any trouble", "is everything", "situation",
              "समस्या", "अलर्ट", "दिक्कत", "परेशानी", "सेंसर", "स्थिति", "गड़बड़", "dikkat", "samasya", "pareshani", "gadbad")
PAST = ("था", "थी", "थे", "आया", "आई", "गया", "गयी", "गई", "चुका", "tha", "thi", "aaya", "aayi", "gaya", "gayi", "chuka", "did", "was", "came", "arrived", "delivered")
DAY_RULES = ((2, ("day after tomorrow", "parso", "parson", "परसों", "परसो")), (-1, ("yesterday", "बीते कल", "beete kal")),
             (0, ("today", "aaj", "आज", "tonight", "this morning", "this evening")), (1, ("tomorrow",)))
KAL = ("kal", "कल")


@dataclass(frozen=True)
class Understanding:
    intent: str  # schedule | ward_status | faq
    ward: int | None = None
    ward_given: bool = False  # the question named a ward (number or name), whether or not it exists
    day: int | None = None  # day offset, None = not said


def _has(t: str, cues) -> bool:
    return any(re.search(rf"(?<![\wऀ-ॿ]){re.escape(c)}(?![\wऀ-ॿ])", t) for c in cues)


def find_ward(t: str, wards: list[Ward]) -> tuple[int | None, bool]:
    """(ward number or None, whether a ward was named). `t` is normalised text."""
    m = WARD_AFTER.search(t) or WARD_BEFORE.search(t)
    if m:
        tok = m.group(1)
        return (int(tok) if tok.isdigit() else _NUM[tok]), True
    best = None
    for w in wards:
        for name in (w.name_en, w.name_hi, *w.aliases):
            n = normalise(name)
            if n and re.search(rf"(?<![\wऀ-ॿ]){re.escape(n)}(?![a-z0-9_])", t) and (best is None or len(n) > best[1]):
                best = (w.number, len(n))
    if best:
        return best[0], True
    close = _close_name(t, wards)
    return (close, True) if close is not None else (None, False)


def _close_name(t: str, wards: list[Ward], cutoff: float = 0.72) -> int | None:
    """A ward whose name is spelled almost like one or two neighbouring words of the question (speech recognition
    writes names by ear: "Sathya Vittari", "सत्वचारी"). Only if exactly one ward is close enough."""
    from difflib import SequenceMatcher

    toks = [w for w in t.split() if len(w) >= 3]
    grams = {g.replace(" ", "") for i in range(len(toks)) for g in (toks[i], " ".join(toks[i:i + 2])) if len(g.replace(" ", "")) >= 5}
    scores = {}
    for w in wards:
        for name in (w.name_en, w.name_hi, *w.aliases):
            n = normalise(name).replace(" ", "")
            if len(n) < 5:
                continue
            for g in grams:
                if abs(len(g) - len(n)) <= 4 and g[0] == n[0]:
                    r = SequenceMatcher(None, g, n).ratio()
                    if r >= cutoff:
                        scores[w.number] = max(scores.get(w.number, 0.0), r)
    if not scores:
        return None
    best = max(scores, key=scores.get)
    others = [v for k, v in scores.items() if k != best]
    return best if not others or scores[best] - max(others) >= 0.05 else None


def find_day(t: str) -> int | None:
    for offset, cues in DAY_RULES:
        if _has(t, cues):
            return offset
    if _has(t, KAL):  # Hindi "kal" is yesterday or tomorrow: the verb decides, and a question about a tanker usually means tomorrow
        return -1 if _has(t, PAST) else 1
    return None


def understand(text: str, wards: list[Ward]) -> Understanding:
    t = normalise(text)
    ward, given = find_ward(t, wards)
    day = find_day(t)
    tanker, when, faq_cue = _has(t, TANKER) or bool(TANKER_HEARD.search(t)), _has(t, TIME_CUE), _has(t, FAQ_CUE)
    if tanker and not faq_cue and (given or when or day is not None or len(t.split()) <= 4):
        return Understanding("schedule", ward, given, day)
    if not tanker and given and _has(t, STATUS_CUE):
        return Understanding("ward_status", ward, given, day)
    if not tanker and given and when and not faq_cue:  # "ward 4 mein paani kab aayega": a schedule question without the word tanker
        return Understanding("schedule", ward, given, day)
    return Understanding("faq", ward, given, day)


# ---------------------------------------------------------------- notices retrieval (TF-IDF, English)
HINDI_STOP = set("का की के में है हैं क्या कब कैसे कहाँ कहां कितने बजे को से पर और या यह वह तो भी ही एक किस कौन "
                 "ka ki ke mein me hai hain kya kab kaise kahan kitne baje ko se par aur ya yeh woh to bhi hi kaun".split())


def hindi_tokens(text: str) -> list[str]:
    return [w for w in normalise(text).split() if w not in HINDI_STOP and len(w) > 1]


class NoticeIndex:
    """Two lexical channels over the notices. English: TF-IDF over title, text and keywords, for English questions and
    for Hindi questions after translation. Hindi: TF-IDF over a few Hindi keywords per notice (Devanagari and Latin
    letters), matched against the citizen's own words, so a translation slip ("tanker" -> "tank") cannot send a
    question to the wrong notice. A clear match in the Hindi channel wins."""

    def __init__(self, notices: list[dict] | None = None, threshold: float = 0.18, threshold_hi: float = 0.25):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.notices = notices if notices is not None else load_notices()
        self.threshold, self.threshold_hi = threshold, threshold_hi
        docs = [f"{n['title']}. {n['title']}. {n['text']} {n.get('keywords', '')}" for n in self.notices]
        self._vec = TfidfVectorizer(lowercase=True, stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self._m = self._vec.fit_transform(docs)
        self._vec_hi = TfidfVectorizer(analyzer=hindi_tokens)
        self._m_hi = self._vec_hi.fit_transform([n.get("keywords_hi", "") or "-" for n in self.notices])

    def _rank(self, vec, m, query: str, threshold: float, k: int) -> list[tuple[dict, float]]:
        sims = np.asarray((m @ vec.transform([query]).T).todense()).ravel()
        return [(self.notices[i], float(sims[i])) for i in np.argsort(-sims)[:k] if sims[i] >= threshold]

    def search(self, query_en: str | None, k: int = 2, original: str | None = None) -> list[tuple[dict, float]]:
        """Best notices with their similarity, best first; empty if nothing reaches the threshold. `original` is the
        citizen's own text when it is Hindi."""
        if original:
            asked = set(hindi_tokens(original))
            hits = [(n, sim) for n, sim in self._rank(self._vec_hi, self._m_hi, original, self.threshold_hi, k)
                    if len(asked & set(hindi_tokens(n.get("keywords_hi", "")))) >= 2]  # one shared word (such as "pani") is not enough
            if hits:
                return hits
        return self._rank(self._vec, self._m, query_en, self.threshold, k) if query_en else []


# ---------------------------------------------------------------- what was retrieved
@dataclass
class Retrieved:
    kind: str  # schedule | ward_status | faq | ask_ward | no_info
    ward: Ward | None = None
    day: int | None = None
    deliveries: list[Delivery] = field(default_factory=list)
    node_state: dict | None = None  # {"category":..., "priority":...} or None when the live state is not available
    notices: list[dict] = field(default_factory=list)
    reason: str = ""  # for no_info: unknown_ward | nothing_planned | no_notice | no_translation

    def records(self) -> list[dict]:
        """The retrieved records as plain facts: the only material an answer may use."""
        if self.kind == "schedule":
            return [d.facts() for d in self.deliveries]
        if self.kind == "ward_status":
            s = self.node_state or {}
            return [{"ward": self.ward.number, "ward_name": self.ward.name_en, "sensor_status": s.get("category", "not available"),
                     **({"priority": s["priority"]} if s.get("category") not in (None, "Normal") else {})}]
        if self.kind == "faq":
            return [{"notice": n["title"], "text": n["text"]} for n in self.notices]
        return []


# ---------------------------------------------------------------- template writer (fixed sentences, English and Hindi)
MONTHS_HI = {"Jan": "जनवरी", "Feb": "फ़रवरी", "Mar": "मार्च", "Apr": "अप्रैल", "May": "मई", "Jun": "जून", "Jul": "जुलाई", "Aug": "अगस्त",
             "Sep": "सितंबर", "Oct": "अक्टूबर", "Nov": "नवंबर", "Dec": "दिसंबर"}
DAY_HI = {-1: "बीते कल", 0: "आज", 1: "कल", 2: "परसों"}
STATUS_HI = {"scheduled": "निर्धारित", "en route": "रास्ते में", "delivered": "पहुँच चुका है", "delayed": "देरी से"}
CATEGORY_HI = {"Infrastructure": "इन्फ्रास्ट्रक्चर (प्रवाह या दबाव)", "Quality": "गुणवत्ता (टर्बिडिटी या टीडीएस)", "Combined": "संयुक्त (दोनों)"}
PRIORITY_HI = {"Low": "कम", "Medium": "मध्यम", "High": "उच्च", "Critical": "गंभीर"}
NOTE_EN = "Note: " + ALERT_NOTE + "."
NOTE_HI = "ध्यान दें: आपके क्षेत्र में नेटवर्क अलर्ट सक्रिय है, इसलिए देरी हो सकती है।"
CAN_DO_EN = "I can tell you the tanker schedule of wards 1 to 8, answer questions from the water notices, and take a report of a damaged pipe (send a photo and the location)."
CAN_DO_HI = "मैं वार्ड 1 से 8 के टैंकर का समय बता सकता हूँ, जल सूचनाओं से जुड़े सवालों के जवाब दे सकता हूँ, और टूटी पाइप की शिकायत दर्ज कर सकता हूँ (फोटो और स्थान भेजें)।"


def _date_hi(date_text: str) -> str:
    d, m = date_text.split()
    return f"{d} {MONTHS_HI[m]}"


def _delivery_en(d: Delivery) -> str:
    day = f"{DAY_WORD.get(d.day_offset, d.date_text)}, {d.date_text}"
    if d.status == "delivered":
        s = f"Tanker {d.tanker_id} delivered {day}, in the {d.expected} slot."
    elif d.status == "delayed":
        s = f"Tanker {d.tanker_id} is delayed by {d.delay_minutes} minutes. Expected {day}, {d.expected} (planned {d.slot})."
    else:
        s = f"Tanker {d.tanker_id} is planned for {day}, {d.slot}. Status: {d.status}."
    return s + (" " + NOTE_EN if d.alert_note else "")


def _delivery_hi(d: Delivery) -> str:
    day = f"{DAY_HI.get(d.day_offset, '')}, {_date_hi(d.date_text)}".lstrip(", ")
    if d.status == "delivered":
        s = f"टैंकर {d.tanker_id} {day} को {d.expected} के बीच पहुँच चुका है।"
    elif d.status == "delayed":
        s = f"टैंकर {d.tanker_id} {d.delay_minutes} मिनट की देरी से चल रहा है। अनुमानित समय: {day}, {d.expected} (निर्धारित {d.slot})।"
    else:
        s = f"टैंकर {d.tanker_id} {day} को {d.slot} के बीच आने की योजना है। स्थिति: {STATUS_HI[d.status]}।"
    return s + (" " + NOTE_HI if d.alert_note else "")


class TemplateWriter:
    name = "template"

    def write(self, question_en: str, r: Retrieved, lang: str) -> str:
        hi = lang == "hi"
        if r.kind == "ask_ward":
            return ("कृपया अपना वार्ड नंबर (1 से 8) या वार्ड का नाम बताएं, जैसे: \"वार्ड 4 में टैंकर कब आएगा?\"" if hi
                    else "Please tell me your ward number (1 to 8) or ward name, for example: \"When will the tanker reach Ward 4?\"")
        if r.kind == "no_info":
            if r.reason == "unknown_ward":
                return ("क्षमा करें, मेरे पास इस वार्ड की जानकारी नहीं है। इस डेमो में केवल वार्ड 1 से 8 हैं।" if hi
                        else "Sorry, I do not have information for that ward. This demo has wards 1 to 8 only.")
            if r.reason == "nothing_planned":
                w, day = r.ward, r.day
                if hi:
                    return f"वार्ड {w.number} ({w.name_hi}): {DAY_HI.get(day, 'आने वाले दिनों')} के लिए कोई टैंकर निर्धारित नहीं है।"
                return f"Ward {w.number} ({w.name_en}): no tanker is planned for {DAY_WORD.get(day, 'the coming days')}."
            return ("क्षमा करें, मेरे पास यह जानकारी नहीं है। " + CAN_DO_HI) if hi else ("Sorry, I do not have that information. " + CAN_DO_EN)
        if r.kind == "schedule":
            w = r.ward
            head = f"वार्ड {w.number} ({w.name_hi}): " if hi else f"Ward {w.number} ({w.name_en}): "
            return head + " ".join((_delivery_hi if hi else _delivery_en)(d) for d in r.deliveries)
        if r.kind == "ward_status":
            w, s = r.ward, r.node_state
            if s is None:
                return (f"वार्ड {w.number} ({w.name_hi}): सेंसर की वर्तमान स्थिति अभी उपलब्ध नहीं है।" if hi
                        else f"Ward {w.number} ({w.name_en}): the current sensor status is not available right now.")
            if s["category"] == "Normal":
                return (f"वार्ड {w.number} ({w.name_hi}): वहाँ के सेंसर अभी कोई असामान्यता नहीं दिखा रहे हैं।" if hi
                        else f"Ward {w.number} ({w.name_en}): our sensors there currently show no anomaly.")
            if hi:
                return (f"वार्ड {w.number} ({w.name_hi}): वहाँ के सेंसर अभी {CATEGORY_HI[s['category']]} अलर्ट दिखा रहे हैं, प्राथमिकता {PRIORITY_HI[s['priority']]}। "
                        "यह केवल बताता है कि सेंसर क्या दिखा रहे हैं, कारण नहीं।")
            return (f"Ward {w.number} ({w.name_en}): our sensors there currently show {_article(s['category'])} {s['category']} alert, priority {s['priority']}. "
                    "This says what the sensors show, not the reason.")
        return r.notices[0]["text"]  # faq: the notice itself (English; the caller translates it for a Hindi reply)


def _article(word: str) -> str:
    return "an" if word[:1] in "AEIOU" else "a"


# ---------------------------------------------------------------- local LLM writer (Ollama)
SYSTEM_PROMPT = (
    "You answer questions of residents about a water service. Use ONLY the facts in RECORDS. "
    "Mention every record. For a tanker give its id, the day, the time slot and the status exactly as written. "
    "For a delayed tanker give the expected_slot and say that it is delayed. If a record has a note, repeat the note. "
    "Copy every time, date, ward number, tanker id and number exactly as written in RECORDS. "
    "Do not add advice, reasons or facts that are not in RECORDS. Never say why something happened. "
    "Answer in plain English in one to three short sentences. Do not use the word RECORDS in the answer.")


class LLMUnavailable(Exception):
    pass


class OllamaWriter:
    """Writes the English answer with a local model served by Ollama. Only a local URL is accepted."""

    name = "ollama"

    def __init__(self, model: str, url: str = "http://127.0.0.1:11434", transport: httpx.BaseTransport | None = None, timeout: float = 60.0):
        host = httpx.URL(url).host
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("OLLAMA_URL must point to this machine (local models only)")
        self.model, self._url = model, url.rstrip("/")
        self._client = httpx.Client(timeout=timeout, transport=transport)

    @staticmethod
    def prompt(question_en: str, r: Retrieved) -> str:
        lines = []
        for rec in r.records():
            if "tanker" in rec:  # a schedule record as one plain sentence: small models copy it more reliably than key: value pairs
                ln = f"Tanker {rec['tanker']} for Ward {rec['ward']} ({rec['ward_name']}): {rec['day']}, {rec['date']}, time slot {rec['planned_slot']}, status {rec['status']}"
                if "expected_slot" in rec:
                    ln += f", delayed by {rec['delay_minutes']} minutes, expected time slot {rec['expected_slot']}"
                lines.append(ln + (f". Note: {rec['note']}" if "note" in rec else ""))
            else:
                lines.append(", ".join(f"{k}: {v}" for k, v in rec.items()))
        return "RECORDS:\n" + "\n".join(f"- {ln}" for ln in lines) + f"\n\nQUESTION: {question_en}\n\nANSWER:"

    def write(self, question_en: str, r: Retrieved, lang: str) -> str:
        body = {"model": self.model, "stream": False, "keep_alive": "30m",
                "options": {"temperature": 0, "seed": 0, "num_predict": 160},
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": self.prompt(question_en, r)}]}
        try:
            resp = self._client.post(f"{self._url}/api/chat", json=body)
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"Ollama not reachable ({type(e).__name__})") from None
        if resp.status_code != 200:
            raise LLMUnavailable(f"Ollama answered HTTP {resp.status_code}")
        try:
            text = resp.json()["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise LLMUnavailable("Ollama gave an unexpected answer") from None
        return " ".join(str(text).split())


# ---------------------------------------------------------------- grounding guard
CAUSE_WORDS = ("leak", "burst", "contaminat", "pollut", "sewage", "rupture", "broken pipe", "pipe break", "sabotage", "because of", "due to", "caused by")
STATUS_WORDS = ("en route", "on the way", "on its way", "delayed", "scheduled", "cancelled", "canceled")
_DELIVERED = re.compile(r"\b(?:has|have|had|was|were|been|already|is)\s+(?:been\s+|already\s+)*delivered\b|\bdelivered\s+(?:today|yesterday|at|in|on)\b|status:\s*delivered")
_PHONE = re.compile(r"(?<![\w-])(\d{2,5}(?:[\s-]\d{2,5}){2,})(?![\w-])")
DAY_WORDS = ("day after tomorrow", "tomorrow", "today", "yesterday")
_MONTH = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_TIME = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])")
_AMPM = re.compile(r"(?<!\d)(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])")
_DATE = re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})\b|\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?!\d)")
_TANKER_ID = re.compile(r"\btkr[\s-]?(\d{1,3})\b")
_WARD_NUM = re.compile(r"\bward\s*(?:no\.?|number)?\s*(\d{1,3})\b")
_NUMBER = re.compile(r"(?<![\w.:-])(\d+(?:\.\d+)?)(?![\w:-]|\.\d)")


def _claims(text: str) -> dict[str, set]:
    """What a text states that can be checked: times, dates, tanker ids, ward numbers, other numbers, day and status words."""
    t = " " + str(text).translate(_DIGITS).lower() + " "
    out = {k: set() for k in ("time", "date", "tanker", "ward", "number", "day", "status", "phone")}
    for ph in _PHONE.findall(t):
        out["phone"].add(re.sub(r"\D", "", ph))
    t = _PHONE.sub(" ", t)
    for h, m, ap in _AMPM.findall(t):
        hh = int(h) % 12 + (12 if ap.startswith("p") else 0)
        out["time"].add(f"{hh:02d}:{m or '00'}")
    t_wo = _AMPM.sub(" ", t)
    for h, m in _TIME.findall(t_wo):
        out["time"].add(f"{int(h):02d}:{m}")
    for d1, m1, m2, d2 in _DATE.findall(t_wo):
        out["date"].add(f"{int(d1 or d2)} {(m1 or m2)[:3]}")
    for n in _TANKER_ID.findall(t_wo):
        out["tanker"].add(int(n))
    for n in _WARD_NUM.findall(t_wo):
        out["ward"].add(int(n))
    rest = _TANKER_ID.sub(" ", _WARD_NUM.sub(" ", _DATE.sub(" ", _TIME.sub(" ", t_wo))))
    rest = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", rest)  # 15th -> 15
    for n in _NUMBER.findall(rest):
        out["number"].add(float(n))
    rest_days = t
    for w in DAY_WORDS:  # longest first, so "day after tomorrow" is not also counted as "tomorrow"
        if w in rest_days:
            out["day"].add(w)
            rest_days = rest_days.replace(w, " ")
    for w in STATUS_WORDS:
        if w in t:
            out["status"].add({"on the way": "en route", "on its way": "en route", "canceled": "cancelled"}.get(w, w))
    if _DELIVERED.search(t):  # "will be delivered" is a plan, not a claim that it happened
        out["status"].add("delivered")
    return out


def guard(answer_en: str, r: Retrieved, wards: list[Ward]) -> list[str]:
    """Violations of an English answer against the retrieved records (empty list = grounded)."""
    if not answer_en or not answer_en.strip():
        return ["empty answer"]
    if len(answer_en) > 700:
        return ["answer too long"]
    low = answer_en.lower()
    bad = [f"cause word '{w}'" for w in CAUSE_WORDS if w in low]
    facts = " . ".join(", ".join(f"{k}: {v}" for k, v in rec.items()) for rec in r.records())
    if r.kind == "schedule":
        facts += " . " + " . ".join(f"ward {d.ward} {d.expected} {d.slot} {d.date_text} {DAY_WORD.get(d.day_offset, '')}" for d in r.deliveries)
    elif r.kind == "ward_status":
        facts += f" . ward {r.ward.number}"
    have, said = _claims(facts), _claims(answer_en)
    have["number"] |= {float(x) for x in have["ward"] | have["tanker"]} | {float(d.split()[0]) for d in have["date"]}
    for kind in ("time", "date", "tanker", "ward", "number", "day", "status", "phone"):
        extra = said[kind] - have[kind]
        if kind == "status" and r.kind == "faq":
            extra = set()  # a notice may use these words freely
        if kind == "day" and r.kind != "schedule":
            extra = set()
        bad += [f"{kind} not in the records: {x}" for x in sorted(map(str, extra))]
    names = {w.number: [normalise(n) for n in (w.name_en, *w.aliases) if not DEVANAGARI.search(n)] for w in wards}
    allowed = {r.ward.number} if r.ward else set()
    for num, ns in names.items():
        if num not in allowed and any(re.search(rf"\b{re.escape(n)}\b", normalise(answer_en)) for n in ns):
            bad.append(f"ward name not in the records: ward {num}")
    return bad + _missing(low, said, r)


_STOP = set("the a an is are was were be been to of in on at for and or it this that with from by as you your can will not do does have has".split())


def _missing(low: str, said: dict, r: Retrieved) -> list[str]:
    """What a grounded answer must contain. An answer that states nothing wrong but also nothing useful is replaced too."""
    out = []
    if r.kind == "schedule":
        if r.ward.number not in said["ward"] and normalise(r.ward.name_en) not in normalise(low):
            out.append("missing: the ward")
        for d in r.deliveries:
            if int(d.tanker_id.split("-")[1]) not in said["tanker"]:
                out.append(f"missing: the tanker id {d.tanker_id}")
            if d.expected[:5] not in said["time"]:
                out.append(f"missing: the time {d.expected[:5]} of tanker {d.tanker_id}")
            if d.status in ("delivered", "delayed") and d.status not in said["status"]:
                out.append(f"missing: the status {d.status} of tanker {d.tanker_id}")
            if d.alert_note and "delay" not in low:
                out.append("missing: the note about a possible delay")
    elif r.kind == "ward_status":
        s = r.node_state
        if s is None:
            if "not available" not in low and "unavailable" not in low:
                out.append("missing: that the sensor status is not available")
        elif s["category"] == "Normal":
            if not any(w in low for w in ("no anomal", "normal", "no alert", "no problem", "no issue")):
                out.append("missing: that the sensors show no anomaly")
        elif s["category"].lower() not in low or s["priority"].lower() not in low:
            out.append("missing: the alert category and priority")
    elif r.kind == "faq":
        words = [w for w in re.findall(r"[a-z]{3,}", low) if w not in _STOP]
        source = " ".join(n["text"].lower() + " " + n["title"].lower() for n in r.notices)
        if len(words) < 3 or sum(w in source for w in words) / len(words) < 0.4:
            out.append("missing: content from the notice")
        facts_per_sentence = []
        for n in r.notices:
            for sentence in re.split(r"(?<=[.!?])\s+", n["text"]):
                c = _claims(sentence)
                times = c["time"]
                if times and said["time"] & times and not times <= said["time"]:
                    out.append("missing: some of the times of a notice sentence (" + ", ".join(sorted(times - said["time"])) + ")")
                if times or c["number"] or c["phone"]:
                    facts_per_sentence.append(times <= said["time"] and c["number"] <= said["number"] and c["phone"] <= said["phone"])
        if facts_per_sentence and not any(facts_per_sentence):  # the notice has times or numbers and the answer carries none of its sentences fully
            out.append("missing: the times or numbers of the notice")
        negations = {w for w in ("not", "no", "never", "nobody", "cannot", "none", "without") if re.search(rf"\b{w}\b", low)}
        if negations - {w for w in negations if re.search(rf"\b{w}\b", source)}:
            out.append("a negation that is not in the notice")
    return out


def numbers_survive(source_en: str, target: str) -> bool:
    """After a translation: every time, tanker id, ward number, phone number and whole number of the English text must
    still be in the translated text. A full hour may be written as a plain number there (06:00 -> 6)."""
    a, b = _claims(source_en), _claims(target)
    digits = {int(p) for p in re.findall(r"\d+", str(target).translate(_DIGITS))}
    for tm in a["time"] - b["time"]:
        h, m = int(tm[:2]), tm[3:]
        if m != "00" or not ({h, h - 12 if h > 12 else h} & digits):
            return False
    need = {int(n) for n in a["tanker"] | a["ward"]} | {int(n) for n in a["number"] if float(n).is_integer()}
    return need <= digits and a["phone"] <= b["phone"]


def canonical_question(u: Understanding, ward: Ward | None) -> str:
    """The understood question in plain English (used as the LLM's question for Hindi schedule and status questions)."""
    where = f"Ward {ward.number} ({ward.name_en})" if ward else "my ward"
    if u.intent == "ward_status":
        return f"What do the sensors show in {where} right now?"
    if u.day is None:
        return f"When is the next water tanker for {where}?"
    return f"What is the tanker schedule for {where} {DAY_WORD.get(u.day, '')}?".replace(" ?", "?")


# ---------------------------------------------------------------- the answerer
@dataclass
class Reply:
    text: str  # the reply in the citizen's language (without the demo marker)
    text_en: str  # the English answer before any translation
    lang: str
    intent: str
    kind: str  # what was retrieved: schedule | ward_status | faq | ask_ward | no_info
    ward: int | None
    day: int | None
    writer: str  # which writer's text was used: template | ollama
    no_info: bool
    guard_violations: list = field(default_factory=list)  # violations found in the LLM answer (before the guard replaced it)
    guard_fallback: bool = False
    llm_unavailable: bool = False
    translation_fallback: bool = False
    records: list = field(default_factory=list)
    ms: dict = field(default_factory=dict)  # latency per stage in milliseconds


class Answerer:
    """Question text in, grounded reply out. `translator` (hi<->en) is needed only for notices and LLM answers in Hindi;
    `node_state(node_id)` gives the node's latest assessment or None; `llm` is optional (None = template only)."""

    def __init__(self, schedule: ScheduleService, index: NoticeIndex | None = None, translator=None, llm: OllamaWriter | None = None,
                 node_state=lambda node_id: None):
        self.schedule, self.index = schedule, index or NoticeIndex()
        self.translator, self.llm, self.node_state = translator, llm, node_state
        self.template = TemplateWriter()
        self.wards = list(schedule.wards.values())

    def retrieve(self, u: Understanding, question_en: str | None, original: str | None = None) -> Retrieved:
        ward = self.schedule.wards.get(u.ward) if u.ward is not None else None
        if u.intent in ("schedule", "ward_status"):
            if u.ward_given and ward is None:
                return Retrieved("no_info", reason="unknown_ward")
            if ward is None:
                return Retrieved("ask_ward")
        if u.intent == "schedule":
            if u.day is None:
                nxt = self.schedule.next_delivery(ward.number)
                ds = [nxt] if nxt else []
            else:
                ds = self.schedule.deliveries(ward.number, u.day)
            return Retrieved("schedule", ward, u.day, ds) if ds else Retrieved("no_info", ward, u.day, reason="nothing_planned")
        if u.intent == "ward_status":
            try:
                s = self.node_state(ward.node_id)
            except Exception:
                s = None
            state = {"category": s["category"], "priority": s["priority"]} if isinstance(s, dict) and s.get("category") and s.get("status") != "warming_up" else None
            return Retrieved("ward_status", ward, node_state=state)
        hits = self.index.search(question_en, original=original)
        if hits:
            return Retrieved("faq", notices=[n for n, _ in hits])
        return Retrieved("no_info", reason="no_notice" if question_en is not None else "no_translation")

    def answer(self, text: str, lang: str | None = None) -> Reply:
        ms, t0 = {}, time.perf_counter()
        lang = lang or detect_language(text)
        u = understand(text, self.wards)
        ms["understand"] = (time.perf_counter() - t0) * 1000
        question_en = text
        if lang == "hi" and u.intent == "faq":
            t = time.perf_counter()
            question_en = self._translate(text, "hi", "en")
            ms["translate_in"] = (time.perf_counter() - t) * 1000
        elif lang == "hi":
            # a schedule or status question in Hindi goes to the LLM as a plain English question built from the understood
            # ward and day, not as a machine translation (a mis-heard or mistranslated question must not steer the wording)
            question_en = canonical_question(u, self.schedule.wards.get(u.ward) if u.ward is not None else None)
        t = time.perf_counter()
        r = self.retrieve(u, question_en, original=text if lang == "hi" else None)
        ms["retrieve"] = (time.perf_counter() - t) * 1000
        reply = Reply("", "", lang, u.intent, r.kind, u.ward, u.day, "template", r.kind == "no_info", records=r.records())
        template_en = self.template.write(question_en or "", r, "en")
        reply.text_en = template_en
        if self.llm is not None and r.kind in ("schedule", "ward_status", "faq") and question_en is not None:
            t = time.perf_counter()
            try:
                llm_en = self.llm.write(question_en, r, "en")
            except LLMUnavailable:
                reply.llm_unavailable, llm_en = True, None
            ms["llm"] = (time.perf_counter() - t) * 1000
            if llm_en is not None:
                reply.guard_violations = guard(llm_en, r, self.wards)
                if reply.guard_violations:
                    reply.guard_fallback = True
                else:
                    reply.text_en, reply.writer = llm_en, "ollama"
        if lang != "hi":
            reply.text = reply.text_en
        elif reply.writer == "template" and r.kind != "faq":
            reply.text = self.template.write(question_en or "", r, "hi")  # fixed Hindi sentences: no translation involved
        else:
            t = time.perf_counter()
            hi = self._translate(reply.text_en, "en", "hi")
            ms["translate_out"] = (time.perf_counter() - t) * 1000
            if hi and numbers_survive(reply.text_en, hi):
                reply.text = hi
            else:
                reply.translation_fallback = True
                if r.kind == "faq":
                    reply.text = "(हिंदी अनुवाद उपलब्ध नहीं है)\n" + template_en
                else:
                    reply.text, reply.text_en, reply.writer = self.template.write(question_en or "", r, "hi"), template_en, "template"
        ms["total"] = (time.perf_counter() - t0) * 1000
        reply.ms = {k: round(v, 1) for k, v in ms.items()}
        return reply

    def _translate(self, text: str, src: str, dst: str) -> str | None:
        if self.translator is None:
            return None
        try:
            out = self.translator.translate(text, src, dst)
        except Exception:
            return None
        return out if isinstance(out, str) and out.strip() else None
