"""Speech recognition (ASR) for voice questions, Hindi and English, run locally.

One interface, `ASR.transcribe(pcm, language)`, with a local implementation (faster-whisper on the GPU, CPU fallback)
and a fake for tests. The model is loaded once and reused. Nothing here logs audio or the recognised text.
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("kami.citizen")
LANGS = ("hi", "en")
_CLOSE_TO_HINDI = ("ur", "mr", "ne", "pa", "sa", "bn", "gu")  # what Whisper sometimes reports for Hindi speech


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str  # 'hi' or 'en'
    seconds: float = 0.0  # time the recognition took


class ASR(ABC):
    name = "asr"

    @abstractmethod
    def transcribe(self, pcm: np.ndarray, language: str | None = None) -> Transcript:
        """pcm: float32 samples in [-1, 1], 16 kHz mono. language: 'hi', 'en' or None to detect (between these two)."""

    def load(self) -> None:
        """Load the model now (warm-up), so the first citizen does not wait."""


def add_cuda_dlls() -> None:
    """On Windows the CUDA libraries that CTranslate2 needs (cuBLAS, cuDNN) come with the PyTorch wheel: make them findable."""
    if os.name != "nt":
        return
    try:
        import importlib.util

        spec = importlib.util.find_spec("torch")
        lib = os.path.join(os.path.dirname(spec.origin), "lib") if spec and spec.origin else None
    except Exception:
        lib = None
    if lib and os.path.isdir(lib):
        try:
            os.add_dll_directory(lib)
        except OSError:
            pass
        if lib not in os.environ.get("PATH", ""):
            os.environ["PATH"] = lib + os.pathsep + os.environ.get("PATH", "")


class FasterWhisperASR(ASR):
    """OpenAI Whisper through CTranslate2 (`faster-whisper`). Default model: large-v3-turbo."""

    def __init__(self, model: str = "large-v3-turbo", device: str = "cuda", beam_size: int = 5, hotwords: str | None = None):
        self.model_name, self.device, self.beam_size = model, device, beam_size
        self.hotwords = hotwords  # domain words given to the model as hints (ward names, "ward", "tanker"); None = no hints
        self.name = f"faster-whisper:{model}"
        self.load_seconds = 0.0
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        t = time.perf_counter()
        add_cuda_dlls()
        from faster_whisper import WhisperModel

        if self.device == "cuda":
            try:
                self._model = WhisperModel(self.model_name, device="cuda", compute_type="float16")
                self._model.transcribe(np.zeros(1600, np.float32), language="en")  # fails here, not later, if CUDA is unusable
            except Exception as e:
                log.warning("speech recognition: GPU not usable (%s), using the CPU", type(e).__name__)
                self.device, self._model = "cpu", None
        if self._model is None:
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        self.load_seconds = time.perf_counter() - t

    def _run(self, pcm: np.ndarray, language: str | None):
        segments, info = self._model.transcribe(pcm, language=language, task="transcribe", beam_size=self.beam_size, vad_filter=False,
                                                condition_on_previous_text=False, without_timestamps=True, hotwords=self.hotwords)
        return " ".join(s.text.strip() for s in segments).strip(), info

    def transcribe(self, pcm: np.ndarray, language: str | None = None) -> Transcript:
        self.load()
        t = time.perf_counter()
        pcm = np.asarray(pcm, dtype=np.float32)
        if language in LANGS:
            text, _ = self._run(pcm, language)
            return Transcript(text, language, time.perf_counter() - t)
        text, info = self._run(pcm, None)
        lang = info.language
        if lang not in LANGS:  # only Hindi and English are supported: take the more likely of the two and recognise again
            probs = dict(info.all_language_probs or [])
            hindi = probs.get("hi", 0.0) + sum(probs.get(k, 0.0) for k in _CLOSE_TO_HINDI)
            lang = "hi" if hindi >= probs.get("en", 0.0) else "en"
            text, _ = self._run(pcm, lang)
        return Transcript(text, lang, time.perf_counter() - t)


class FakeASR(ASR):
    """For tests: returns prepared transcripts in order (or one fixed transcript)."""

    name = "fake-asr"

    def __init__(self, *transcripts: Transcript):
        self.transcripts, self.calls = list(transcripts), []

    def transcribe(self, pcm, language=None) -> Transcript:
        self.calls.append((len(pcm), language))
        return self.transcripts.pop(0) if len(self.transcripts) > 1 else self.transcripts[0]
