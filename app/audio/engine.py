"""Audio capture, playback and the outbound WebRTC track.

The engine keeps a small PCM buffer for capture and playback. Capture runs on the
PortAudio callback thread; the outbound track drains it from the asyncio thread.
Playback is fed by the WebRTC track and consumed by the speaker callback.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import av
import numpy as np
import sounddevice as sd
from aiortc import MediaStreamTrack

from app.audio.frames import FramePacer, PcmConverter, make_frame, rms_level
from app.core.config import (
    CAPTURE_MAX_SAMPLES,
    FRAME_SAMPLES,
    MIC_BLOCK_SAMPLES,
    PLAYBACK_MAX_SAMPLES,
    SAMPLE_RATE,
)

log = logging.getLogger(__name__)


class AudioDeviceError(RuntimeError):
    """A microphone or speaker could not be opened."""


@dataclass(frozen=True, slots=True)
class AudioDevice:
    index: int
    name: str
    is_default: bool = False
    host_api: str = ""


def _hostapis() -> dict[int, dict]:
    try:
        return {item["index"]: item for item in sd.query_hostapis()}
    except Exception:
        return {}


def _wasapi_index(hostapis: dict[int, dict]) -> int | None:
    for index, api in hostapis.items():
        if "wasapi" in str(api.get("name", "")).lower():
            return index
    return None


def list_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Return (microphones, speakers), preferring the low-latency WASAPI API."""
    try:
        infos = sd.query_devices()
        hostapis = _hostapis()
    except Exception as exc:
        raise AudioDeviceError(
            "The audio system is not available. Check that a microphone and "
            "speaker are connected."
        ) from exc

    wasapi = _wasapi_index(hostapis)
    default_in = (
        hostapis[wasapi].get("default_input_device", -1) if wasapi is not None else -1
    )
    default_out = (
        hostapis[wasapi].get("default_output_device", -1) if wasapi is not None else -1
    )
    fallback_in, fallback_out = sd.default.device
    use_default_in = default_in if wasapi is not None else fallback_in
    use_default_out = default_out if wasapi is not None else fallback_out

    inputs: list[AudioDevice] = []
    outputs: list[AudioDevice] = []
    for index, info in enumerate(infos):
        if wasapi is not None and info["hostapi"] != wasapi:
            continue
        name = str(info["name"]).strip() or f"Audio device {index}"
        api_name = str(hostapis.get(info["hostapi"], {}).get("name", ""))
        if info["max_input_channels"] > 0:
            inputs.append(AudioDevice(index, name, index == use_default_in, api_name))
        if info["max_output_channels"] > 0:
            outputs.append(AudioDevice(index, name, index == use_default_out, api_name))

    if not inputs and not outputs:
        # Non-Windows systems or a WASAPI-free setup: list everything.
        for index, info in enumerate(infos):
            name = str(info["name"]).strip() or f"Audio device {index}"
            api_name = str(hostapis.get(info["hostapi"], {}).get("name", ""))
            if info["max_input_channels"] > 0:
                inputs.append(AudioDevice(index, name, index == fallback_in, api_name))
            if info["max_output_channels"] > 0:
                outputs.append(AudioDevice(index, name, index == fallback_out, api_name))

    inputs.sort(key=lambda item: (not item.is_default, item.name.lower()))
    outputs.sort(key=lambda item: (not item.is_default, item.name.lower()))
    return inputs, outputs


def _default_device(inputs: bool) -> int | None:
    devices = list_devices()[0 if inputs else 1]
    if not devices:
        return None
    for device in devices:
        if device.is_default:
            return device.index
    return devices[0].index


def _extra_settings(index: int) -> sd.WasapiSettings | None:
    """Let WASAPI convert sample formats/rates for maximum device compatibility."""
    try:
        info = sd.query_devices(index)
        api = sd.query_hostapis(info["hostapi"])
        if "wasapi" in str(api.get("name", "")).lower():
            return sd.WasapiSettings(exclusive=False, auto_convert=True)
    except Exception:
        pass
    return None


class AudioEngine:
    """Owns the microphone/speaker streams and the outbound audio track."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._input_stream: sd.InputStream | None = None
        self._output_stream: sd.OutputStream | None = None
        self._input_rate = SAMPLE_RATE
        self._output_rate = SAMPLE_RATE
        self._input_resampler: av.AudioResampler | None = None
        self._playback_resampler: av.AudioResampler | None = None
        self._converter = PcmConverter()

        self._capture = np.zeros(0, dtype=np.int16)
        self._playback = np.zeros(0, dtype=np.int16)
        self._mic_level = 0.0
        self._remote_level = 0.0

        self._muted = False
        self._ptt_mode = False
        self._ptt_held = False

    # -- state -------------------------------------------------------------
    @property
    def input_open(self) -> bool:
        return self._input_stream is not None

    @property
    def output_open(self) -> bool:
        return self._output_stream is not None

    def _transmitting(self) -> bool:
        return not self._muted and (not self._ptt_mode or self._ptt_held)

    def levels(self) -> tuple[float, float]:
        with self._lock:
            mic, remote = self._mic_level, self._remote_level
            self._mic_level *= 0.9
            self._remote_level *= 0.9
        return mic, remote

    # -- capture -----------------------------------------------------------
    def open_input(self, device: int | None = None) -> None:
        index = _default_device(True) if device is None else device
        if index is None:
            raise AudioDeviceError("No microphone was found.")
        self.close_input()
        try:
            info = sd.query_devices(index, "input")
        except Exception as exc:
            raise AudioDeviceError("The selected microphone is not available.") from exc

        default_rate = int(info["default_samplerate"] or SAMPLE_RATE)
        extra = _extra_settings(index)
        stream = None
        rate = SAMPLE_RATE
        for attempt in (SAMPLE_RATE, default_rate):
            blocksize = max(1, (attempt * 10) // 1000)
            try:
                stream = sd.InputStream(
                    device=index,
                    channels=1,
                    samplerate=attempt,
                    blocksize=blocksize,
                    dtype="int16",
                    latency="low",
                    callback=self._on_mic,
                    extra_settings=extra,
                )
                stream.start()
                rate = attempt
                break
            except Exception as exc:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                    stream = None
                last_error = exc
        else:
            raise AudioDeviceError(
                "Could not open the microphone. It may be in use by another "
                "application or blocked by Windows privacy settings."
            ) from last_error

        with self._lock:
            self._input_stream = stream
            self._input_rate = rate
            self._input_resampler = (
                av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
                if rate != SAMPLE_RATE
                else None
            )
            self._capture = np.zeros(0, dtype=np.int16)
            self._mic_level = 0.0
        log.info("Microphone opened: %s (%s Hz)", info.get("name"), rate)

    def close_input(self) -> None:
        stream, self._input_stream = self._input_stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._capture = np.zeros(0, dtype=np.int16)
            self._mic_level = 0.0

    def _on_mic(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            log.debug("Microphone status: %s", status)
        try:
            samples = np.asarray(indata)
            if samples.ndim > 1:
                samples = samples[:, 0]
            samples = np.ascontiguousarray(samples, dtype=np.int16)
            if samples.size == 0:
                return
            if self._input_resampler is not None:
                frame = av.AudioFrame.from_ndarray(
                    samples.reshape(1, -1), format="s16", layout="mono"
                )
                frame.sample_rate = self._input_rate
                parts = [
                    out.to_ndarray().reshape(-1)
                    for out in self._input_resampler.resample(frame)
                ]
                if not parts:
                    return
                samples = np.concatenate(parts).astype(np.int16)
            level = rms_level(samples)
            with self._lock:
                self._mic_level = max(level, self._mic_level)
                self._capture = np.concatenate((self._capture, samples))
                if self._capture.size > CAPTURE_MAX_SAMPLES:
                    self._capture = self._capture[-CAPTURE_MAX_SAMPLES:]
        except Exception:
            log.exception("Microphone callback failed")

    def take_capture(self, count: int = FRAME_SAMPLES) -> np.ndarray:
        """Take the next block for WebRTC, padded with silence when needed."""
        with self._lock:
            if not self._transmitting():
                self._capture = np.zeros(0, dtype=np.int16)
                return np.zeros(count, dtype=np.int16)
            if self._capture.size >= count:
                block = self._capture[:count]
                self._capture = self._capture[count:]
            else:
                block = self._capture
                self._capture = np.zeros(0, dtype=np.int16)
            if block.size < count:
                block = np.concatenate(
                    (block, np.zeros(count - block.size, dtype=np.int16))
                )
            return block

    # -- playback ----------------------------------------------------------
    def open_output(self, device: int | None = None) -> None:
        index = _default_device(False) if device is None else device
        if index is None:
            raise AudioDeviceError("No speaker was found.")
        self.close_output()
        try:
            info = sd.query_devices(index, "output")
        except Exception as exc:
            raise AudioDeviceError("The selected speaker is not available.") from exc

        default_rate = int(info["default_samplerate"] or SAMPLE_RATE)
        extra = _extra_settings(index)
        stream = None
        rate = SAMPLE_RATE
        for attempt in (SAMPLE_RATE, default_rate):
            blocksize = max(1, (attempt * 10) // 1000)
            try:
                stream = sd.OutputStream(
                    device=index,
                    channels=1,
                    samplerate=attempt,
                    blocksize=blocksize,
                    dtype="int16",
                    latency="low",
                    callback=self._on_speaker,
                    extra_settings=extra,
                )
                stream.start()
                rate = attempt
                break
            except Exception as exc:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                    stream = None
                last_error = exc
        else:
            raise AudioDeviceError(
                "Could not open the speaker. It may be in use by another application."
            ) from last_error

        with self._lock:
            self._output_stream = stream
            self._output_rate = rate
            self._playback_resampler = (
                av.AudioResampler(format="s16", layout="mono", rate=rate)
                if rate != SAMPLE_RATE
                else None
            )
            self._playback = np.zeros(0, dtype=np.int16)
            self._remote_level = 0.0
        log.info("Speaker opened: %s (%s Hz)", info.get("name"), rate)

    def close_output(self) -> None:
        stream, self._output_stream = self._output_stream, None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._playback = np.zeros(0, dtype=np.int16)
            self._remote_level = 0.0

    def close_streams(self) -> None:
        self.close_input()
        self.close_output()

    def play_remote(self, frame: av.AudioFrame) -> None:
        samples = self._converter.to_mono_s16(frame)
        if samples.size == 0:
            return
        level = rms_level(samples)
        with self._lock:
            self._remote_level = max(level, self._remote_level)
            output_rate = self._output_rate
            resampler = self._playback_resampler
        if output_rate != SAMPLE_RATE and resampler is not None:
            source = make_frame(samples, pts=0)
            parts = [
                out.to_ndarray().reshape(-1)
                for out in resampler.resample(source)
            ]
            if parts:
                samples = np.concatenate(parts).astype(np.int16)
        with self._lock:
            self._playback = np.concatenate((self._playback, samples))
            limit = int(self._output_rate * 0.12)
            if limit <= 0:
                limit = PLAYBACK_MAX_SAMPLES
            if self._playback.size > limit:
                self._playback = self._playback[-limit:]

    def _on_speaker(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        with self._lock:
            available = min(frames, self._playback.size)
            block = np.zeros(frames, dtype=np.int16)
            if available:
                block[:available] = self._playback[:available]
                self._playback = self._playback[available:]
        if outdata.ndim > 1:
            outdata[:, 0] = block
        else:
            outdata[:] = block

    # -- controls ----------------------------------------------------------
    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._discard_capture()

    def set_ptt_mode(self, enabled: bool) -> None:
        self._ptt_mode = bool(enabled)
        if not enabled:
            self._ptt_held = False
        self._discard_capture()

    def set_ptt_held(self, held: bool) -> None:
        self._ptt_held = bool(held)
        self._discard_capture()

    def _discard_capture(self) -> None:
        with self._lock:
            self._capture = np.zeros(0, dtype=np.int16)

    def new_outbound_track(self) -> "OutboundTrack":
        return OutboundTrack(self)


class OutboundTrack(MediaStreamTrack):
    """48 kHz mono Opus-ready track fed by the microphone buffer."""

    kind = "audio"

    def __init__(self, engine: AudioEngine) -> None:
        super().__init__()
        self._engine = engine
        self._pacer = FramePacer()

    async def recv(self) -> av.AudioFrame:
        pts = await self._pacer.next_timestamp()
        samples = self._engine.take_capture(FRAME_SAMPLES)
        return make_frame(samples, pts)
