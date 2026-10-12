"""Audio conversion for voice notes: Telegram OGG/Opus <-> 16 kHz mono PCM, through the ffmpeg binary that comes with
the `imageio-ffmpeg` pip package (no system install). Audio goes through pipes only: nothing is written to disk."""
from __future__ import annotations

import subprocess

import numpy as np

RATE = 16000
TIMEOUT_S = 30


class AudioError(Exception):
    pass


class FfmpegAudio:
    def __init__(self):
        try:
            import imageio_ffmpeg
        except ImportError:
            raise AudioError("imageio-ffmpeg is not installed (pip install -r requirements-citizen.txt)") from None
        self._exe = imageio_ffmpeg.get_ffmpeg_exe()

    def _run(self, args: list[str], data: bytes) -> bytes:
        try:
            p = subprocess.run([self._exe, "-hide_banner", "-loglevel", "error", *args], input=data, capture_output=True, timeout=TIMEOUT_S)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise AudioError(f"ffmpeg did not finish ({type(e).__name__})") from None
        if p.returncode != 0 or not p.stdout:
            raise AudioError("ffmpeg could not convert the audio")
        return p.stdout

    def ogg_to_pcm(self, ogg: bytes) -> np.ndarray:
        """Any audio ffmpeg can read (Telegram sends OGG/Opus) -> float32 samples in [-1, 1], 16 kHz mono."""
        raw = self._run(["-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"], ogg)
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0

    def pcm_to_ogg(self, pcm: np.ndarray, rate: int) -> bytes:
        """Samples (float in [-1, 1] or int16) at `rate` Hz mono -> OGG/Opus, the format of a Telegram voice note."""
        a = np.asarray(pcm)
        if a.dtype != np.int16:
            a = (np.clip(a.astype(np.float32), -1.0, 1.0) * 32767.0).astype(np.int16)
        return self._run(["-f", "s16le", "-ar", str(int(rate)), "-ac", "1", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "32k", "-ar", "48000",
                          "-f", "ogg", "pipe:1"], a.astype("<i2").tobytes())


def resample(pcm: np.ndarray, rate: int, to: int = RATE) -> np.ndarray:
    """Linear resampling to float32 mono (enough for feeding synthetic speech back into the recogniser)."""
    a = np.asarray(pcm)
    a = a.astype(np.float32) / 32768.0 if a.dtype == np.int16 else a.astype(np.float32)
    if rate == to or len(a) == 0:
        return a
    n = int(round(len(a) * to / rate))
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)
