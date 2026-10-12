"""Speech output (TTS) for voice replies, Hindi and English, run locally.

One interface, `TTS.synthesize(text, lang) -> (int16 samples, sample rate)`, with local implementations and a fake
for tests. Before synthesis the text is put into a spoken form by rules (`spoken_text`): times, numbers, tanker ids
and phone numbers are written out as words, so every engine says them the same way. Nothing here logs the text.

Models: AI4Bharat Indic Parler-TTS on Hugging Face needs a login and a licence click (gated), so it is not used; see
docs/citizen.md. Open models that download without a login:
  PiperTTS   rhasspy/piper-voices (MIT), ONNX, runs on the CPU
  MmsTTS     facebook/mms-tts-hin and mms-tts-eng (CC-BY-NC 4.0: non-commercial use), PyTorch
"""
from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod

import numpy as np

log = logging.getLogger("kami.citizen")
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
HI_0_99 = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
           "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस "
           "इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ "
           "इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उनासी अस्सी "
           "इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे").split()
assert len(HI_0_99) == 100
EN_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
EN_TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
LETTERS_HI = {"T": "टी", "K": "के", "R": "आर"}


def number_words(n: int, lang: str) -> str:
    """0 to 99999 in words."""
    n = int(n)
    if lang == "hi":
        if n < 100:
            return HI_0_99[n]
        if n < 1000:
            return (HI_0_99[n // 100] + " सौ" + (" " + HI_0_99[n % 100] if n % 100 else "")).strip()
        return (number_words(n // 1000, "hi") + " हज़ार" + (" " + number_words(n % 1000, "hi") if n % 1000 else "")).strip()
    if n < 20:
        return EN_ONES[n]
    if n < 100:
        return EN_TENS[n // 10] + ("-" + EN_ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return EN_ONES[n // 100] + " hundred" + (" " + number_words(n % 100, "en") if n % 100 else "")
    return number_words(n // 1000, "en") + " thousand" + (" " + number_words(n % 1000, "en") if n % 1000 else "")


def _clock(h: int, m: int, lang: str) -> str:
    """A time of day in words, 12-hour clock with the part of the day."""
    h12 = h % 12 or 12
    if lang == "hi":
        part = "सुबह" if 4 <= h < 12 else "दोपहर" if 12 <= h < 16 else "शाम" if 16 <= h < 20 else "रात"
        return f"{part} {HI_0_99[h12]} बजे" if m == 0 else f"{part} {HI_0_99[h12]} बजकर {HI_0_99[m]} मिनट"
    part = "in the morning" if h < 12 else "in the afternoon" if h < 16 else "in the evening" if h < 20 else "at night"
    return f"{number_words(h12, 'en')} {part}" if m == 0 else f"{number_words(h12, 'en')} {number_words(m, 'en')} {part}"


def spoken_text(text: str, lang: str) -> str:
    """The text as it should be spoken: no brackets or markers, times, ids and numbers in words."""
    t = str(text).translate(_DIGITS)
    t = re.sub(r"\[[^\]]*\]", " ", t)  # the demo marker is for reading, not for listening
    t = re.sub(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})",
               lambda m: f"{_clock(int(m[1]), int(m[2]), lang)} {'से' if lang == 'hi' else 'to'} {_clock(int(m[3]), int(m[4]), lang)}"
               + (" तक" if lang == "hi" else ""), t)
    t = re.sub(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])", lambda m: _clock(int(m[1]), int(m[2]), lang), t)
    t = re.sub(r"\bTKR-?(\d+)\b", lambda m: (" ".join(LETTERS_HI[c] for c in "TKR") if lang == "hi" else "T K R") + " " + number_words(int(m[1]), lang), t)
    t = re.sub(r"(?<![\w-])\d{2,5}(?:-\d{2,5}){2,}(?![\w-])",  # a phone number: digit by digit
               lambda m: " ".join(number_words(int(c), lang) for c in m[0] if c.isdigit()), t)
    t = re.sub(r"#\s*(\d+)", lambda m: ("नंबर " if lang == "hi" else "number ") + number_words(int(m[1]), lang), t)
    t = re.sub(r"(\d+)\.(\d+)", lambda m: number_words(int(m[1]), lang) + (" दशमलव " if lang == "hi" else " point ")
               + " ".join(number_words(int(c), lang) for c in m[2]), t)
    t = re.sub(r"(?<!\w)(\d{1,5})(?:st|nd|rd|th)?(?!\w)", lambda m: number_words(int(m[1]), lang), t)
    t = t.replace("किमी", "किलोमीटर").replace(" km", " kilometres")
    t = re.sub(r"[()\"“”]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


class TTS(ABC):
    name = "tts"

    @abstractmethod
    def synthesize(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        """(int16 mono samples, sample rate). The text is given as written; the engine speaks `spoken_text(text, lang)`."""

    def load(self) -> None:
        """Load the model now (warm-up)."""


class PiperTTS(TTS):
    """Piper voices (ONNX, CPU). A voice id looks like hi_IN-pratham-medium."""

    REPO = "rhasspy/piper-voices"

    def __init__(self, voices: dict | None = None):
        self.voices = voices or {"hi": "hi_IN-priyamvada-medium", "en": "en_US-lessac-medium"}  # chosen on validation (Round 6)
        self.name = "piper:" + ",".join(self.voices[k] for k in sorted(self.voices))
        self.load_seconds = 0.0
        self._loaded: dict = {}

    def _voice(self, lang: str):
        if lang not in self._loaded:
            t = time.perf_counter()
            import onnxruntime
            from huggingface_hub import hf_hub_download
            from piper import PiperVoice

            onnxruntime.set_seed(0)  # the voice model samples noise: a fixed seed makes a run repeatable

            vid = self.voices[lang]
            region, name, quality = vid.split("-")
            base = f"{region.split('_')[0]}/{region}/{name}/{quality}/{vid}.onnx"
            model = hf_hub_download(self.REPO, base)
            hf_hub_download(self.REPO, base + ".json")
            self._loaded[lang] = PiperVoice.load(model)
            self.load_seconds += time.perf_counter() - t
        return self._loaded[lang]

    def load(self) -> None:
        for lang in self.voices:
            self._voice(lang)

    def synthesize(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        voice = self._voice(lang)
        chunks = list(voice.synthesize(spoken_text(text, lang)))
        pcm = np.concatenate([np.asarray(c.audio_int16_array, dtype=np.int16) for c in chunks]) if chunks else np.zeros(0, np.int16)
        return pcm, int(chunks[0].sample_rate) if chunks else int(voice.config.sample_rate)


class MmsTTS(TTS):
    """Meta MMS-TTS (VITS) through transformers."""

    def __init__(self, models: dict | None = None, device: str = "cuda"):
        self.models = models or {"hi": "facebook/mms-tts-hin", "en": "facebook/mms-tts-eng"}
        self.name, self.device, self.load_seconds = "mms-tts", device, 0.0
        self._loaded: dict = {}

    def _model(self, lang: str):
        if lang not in self._loaded:
            t = time.perf_counter()
            import torch
            from transformers import AutoTokenizer, VitsModel

            if self.device == "cuda" and not torch.cuda.is_available():
                self.device = "cpu"
            self._loaded[lang] = (AutoTokenizer.from_pretrained(self.models[lang]), VitsModel.from_pretrained(self.models[lang]).to(self.device).eval())
            self.load_seconds += time.perf_counter() - t
        return self._loaded[lang]

    def load(self) -> None:
        for lang in self.models:
            self._model(lang)

    def synthesize(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        import torch

        tok, model = self._model(lang)
        torch.manual_seed(0)  # VITS samples noise: fixed, so the same text gives the same audio
        enc = tok(spoken_text(text, lang).lower(), return_tensors="pt").to(self.device)
        with torch.inference_mode():
            wave = model(**enc).waveform[0].float().cpu().numpy()
        return (np.clip(wave, -1.0, 1.0) * 32767.0).astype(np.int16), int(model.config.sampling_rate)


class FakeTTS(TTS):
    """For tests: half a second of a quiet tone; records what it was asked to say."""

    name = "fake-tts"

    def __init__(self):
        self.calls: list = []

    def synthesize(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        self.calls.append((text, lang))
        return (np.sin(np.arange(8000) * 0.05) * 3000).astype(np.int16), 16000
