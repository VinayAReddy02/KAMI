"""Audio helpers (C3). The OGG/Opus round trip through ffmpeg needs the optional package imageio-ffmpeg
(requirements-citizen.txt); it is checked by scripts/check_round6.py where that package is installed, not here, so that
the test suite has no skipped test other than the Docker-dependent ones."""
import numpy as np

from kami.citizen.audio import RATE, resample


def test_resample_keeps_duration_and_scale():
    tone = (np.sin(np.arange(22050) * 0.05) * 16000).astype(np.int16)  # one second at 22.05 kHz
    out = resample(tone, 22050)
    assert out.dtype == np.float32 and len(out) == RATE and 0.4 < float(np.abs(out).max()) < 0.6
    same = resample(np.zeros(160, np.float32), RATE)
    assert len(same) == 160 and len(resample(np.zeros(0, np.int16), 22050)) == 0
