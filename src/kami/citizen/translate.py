"""Translation Hindi <-> English (NMT), run locally.

One interface, `Translator.translate(text, src, dst)`, with local implementations and a fake for tests. Text is
translated sentence by sentence. The local LLM is never used to translate. Nothing here logs the text.

Models: the AI4Bharat IndicTrans2 models on Hugging Face need a login and a licence click (gated), so they are not
used; see docs/citizen.md. Open models that download without a login:
  NllbTranslator    facebook/nllb-200-distilled-600M (CC-BY-NC 4.0: non-commercial use)
  MarianTranslator  Helsinki-NLP/opus-mt-hi-en and opus-mt-en-hi (Apache-2.0)
"""
from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod

log = logging.getLogger("kami.citizen")
_SENTENCE = re.compile(r"(?<=[.!?।])\s+")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(str(text).strip()) if s.strip()]


class Translator(ABC):
    name = "nmt"

    @abstractmethod
    def translate(self, text: str, src: str, dst: str) -> str:
        """src, dst: 'hi' or 'en'."""

    def load(self) -> None:
        """Load the model now (warm-up)."""


class _TransformersTranslator(Translator):
    max_new_tokens = 200

    def __init__(self, device: str = "cuda"):
        self.device, self.load_seconds = device, 0.0
        self._loaded = False

    def _device(self):
        import torch

        if self.device == "cuda" and not torch.cuda.is_available():
            log.warning("translation: GPU not usable, using the CPU")
            self.device = "cpu"
        return self.device

    def translate(self, text: str, src: str, dst: str) -> str:
        if src == dst:
            return text
        self.load()
        return " ".join(self._batch(sentences(text), src, dst))


class NllbTranslator(_TransformersTranslator):
    CODES = {"hi": "hin_Deva", "en": "eng_Latn"}

    def __init__(self, model: str = "facebook/nllb-200-distilled-600M", device: str = "cuda"):
        super().__init__(device)
        self.model_name, self.name = model, f"nllb:{model.split('/')[-1]}"

    def load(self) -> None:
        if self._loaded:
            return
        t = time.perf_counter()
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        dev = self._device()
        self._tok = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name, dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev).eval()
        self._loaded, self.load_seconds = True, time.perf_counter() - t

    def _batch(self, parts: list[str], src: str, dst: str) -> list[str]:
        import torch

        if not parts:
            return []
        self._tok.src_lang = self.CODES[src]
        enc = self._tok(parts, return_tensors="pt", padding=True, truncation=True, max_length=256).to(self.device)
        with torch.inference_mode():
            out = self._model.generate(**enc, forced_bos_token_id=self._tok.convert_tokens_to_ids(self.CODES[dst]), num_beams=4,
                                       max_length=256)
        return [s.strip() for s in self._tok.batch_decode(out, skip_special_tokens=True)]


class MarianTranslator(_TransformersTranslator):
    MODELS = {("hi", "en"): "Helsinki-NLP/opus-mt-hi-en", ("en", "hi"): "Helsinki-NLP/opus-mt-en-hi"}
    name = "opus-mt"

    def load(self) -> None:
        if self._loaded:
            return
        t = time.perf_counter()
        from transformers import MarianMTModel, MarianTokenizer

        dev = self._device()
        self._pairs = {k: (MarianTokenizer.from_pretrained(m), MarianMTModel.from_pretrained(m).to(dev).eval()) for k, m in self.MODELS.items()}
        self._loaded, self.load_seconds = True, time.perf_counter() - t

    def _batch(self, parts: list[str], src: str, dst: str) -> list[str]:
        import torch

        if not parts:
            return []
        tok, model = self._pairs[(src, dst)]
        enc = tok(parts, return_tensors="pt", padding=True, truncation=True, max_length=256).to(self.device)
        with torch.inference_mode():
            out = model.generate(**enc, num_beams=4, max_length=256)
        return [s.strip() for s in tok.batch_decode(out, skip_special_tokens=True)]


class FakeTranslator(Translator):
    """For tests: a lookup table {(text, src, dst): translation}; unknown text raises, like a failing model would."""

    name = "fake-nmt"

    def __init__(self, table: dict | None = None):
        self.table, self.calls = dict(table or {}), []

    def translate(self, text: str, src: str, dst: str) -> str:
        self.calls.append((text, src, dst))
        return self.table[(text, src, dst)]
