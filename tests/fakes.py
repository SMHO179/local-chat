"""Stand-ins for the sound card, used by tests that need a real call without audio hardware."""

from __future__ import annotations

import numpy as np
from aiortc.mediastreams import AudioStreamTrack

from app.audio.frames import FramePacer, PcmConverter, make_frame
from app.core.config import FRAME_SAMPLES, SAMPLE_RATE


class ToneTrack(AudioStreamTrack):
    """Sends a sine tone at real-time pace."""

    def __init__(self, freq: float = 440.0, amplitude: float = 0.3) -> None:
        super().__init__()
        self._pacer = FramePacer()
        self._freq = freq
        self._amplitude = amplitude
        self._phase = 0

    async def recv(self):
        pts = await self._pacer.next_timestamp()
        t = (np.arange(FRAME_SAMPLES) + self._phase) / SAMPLE_RATE
        self._phase += FRAME_SAMPLES
        samples = (np.sin(2 * np.pi * self._freq * t) * self._amplitude * 32767).astype(np.int16)
        return make_frame(samples, pts)


class FakeAudio:
    """Implements the AudioEndpoint interface: sends a tone and records everything received."""

    def __init__(self, freq: float = 440.0) -> None:
        self._converter = PcmConverter()
        self._freq = freq
        self.received: list[np.ndarray] = []

    def new_outbound_track(self) -> ToneTrack:
        return ToneTrack(freq=self._freq)

    def play_remote(self, frame) -> None:
        self.received.append(self._converter.to_mono_s16(frame))

    def received_rms(self) -> float:
        if not self.received:
            return 0.0
        x = np.concatenate(self.received).astype(np.float32) / 32768.0
        return float(np.sqrt(np.mean(x * x))) if x.size else 0.0

    def dominant_hz(self) -> float:
        """Frequency with the most energy in what was received (0 if nothing arrived)."""
        if not self.received:
            return 0.0
        x = np.concatenate(self.received).astype(np.float32)
        if x.size < SAMPLE_RATE // 10:
            return 0.0
        spectrum = np.abs(np.fft.rfft(x * np.hanning(x.size)))
        spectrum[: int(50 * x.size / SAMPLE_RATE)] = 0   # ignore DC/rumble
        return float(np.argmax(spectrum) * SAMPLE_RATE / x.size)
