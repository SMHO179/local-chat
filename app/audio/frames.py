"""PCM helpers shared by the audio engine and the WebRTC media tracks."""

from __future__ import annotations

import asyncio
import time
from fractions import Fraction

import av
import numpy as np

from app.core.config import FRAME_SAMPLES, SAMPLE_RATE

_MAX_LAG_S = 0.1
_LEVEL_DISPLAY_GAIN = 4.0   # scales typical speech into the visible part of the meter


def make_frame(samples: np.ndarray, pts: int) -> av.AudioFrame:
    """Wrap 48 kHz mono int16 samples in an AudioFrame for aiortc."""
    frame = av.AudioFrame.from_ndarray(samples.reshape(1, -1), format="s16", layout="mono")
    frame.sample_rate = SAMPLE_RATE
    frame.pts = pts
    frame.time_base = Fraction(1, SAMPLE_RATE)
    return frame


class PcmConverter:
    """Converts received WebRTC audio frames to 48 kHz mono int16 samples."""

    def __init__(self) -> None:
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

    def to_mono_s16(self, frame: av.AudioFrame) -> np.ndarray:
        parts = [f.to_ndarray().reshape(-1) for f in self._resampler.resample(frame)]
        return np.concatenate(parts).astype(np.int16) if parts else np.zeros(0, dtype=np.int16)


class FramePacer:
    """Makes a track emit one frame per 20 ms of real time."""

    def __init__(self) -> None:
        self._start: float | None = None
        self._timestamp = 0

    async def next_timestamp(self) -> int:
        """Wait until the next frame is due and return its timestamp in samples."""
        if self._start is None:
            self._start = time.monotonic()
            return 0
        self._timestamp += FRAME_SAMPLES
        wait = self._start + self._timestamp / SAMPLE_RATE - time.monotonic()
        if wait < -_MAX_LAG_S:
            # Fell far behind (e.g. the machine was suspended): resynchronise instead of bursting.
            self._start = time.monotonic() - self._timestamp / SAMPLE_RATE
        elif wait > 0:
            await asyncio.sleep(wait)
        return self._timestamp


def rms_level(samples: np.ndarray) -> float:
    """Loudness of a block of int16 samples scaled to 0.0-1.0 for display."""
    if samples.size == 0:
        return 0.0
    x = samples.astype(np.float32) / 32768.0
    return min(1.0, float(np.sqrt(np.mean(x * x))) * _LEVEL_DISPLAY_GAIN)
