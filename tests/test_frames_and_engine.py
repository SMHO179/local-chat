import asyncio

import numpy as np

from app.audio.engine import AudioEngine
from app.audio.frames import FramePacer, PcmConverter, make_frame, rms_level
from app.core.config import FRAME_SAMPLES, PLAYBACK_MAX_SAMPLES, SAMPLE_RATE


def _tone(n=FRAME_SAMPLES, amp=0.3):
    t = np.arange(n) / SAMPLE_RATE
    return (np.sin(2 * np.pi * 440 * t) * amp * 32767).astype(np.int16)


def test_make_frame_has_48k_mono_s16_layout():
    frame = make_frame(_tone(), pts=960)
    assert frame.sample_rate == SAMPLE_RATE
    assert frame.layout.name == "mono"
    assert frame.pts == 960
    assert frame.samples == FRAME_SAMPLES


def test_converter_round_trips_samples():
    converter = PcmConverter()
    out = converter.to_mono_s16(make_frame(_tone(), pts=0))
    assert out.dtype == np.int16
    np.testing.assert_array_equal(out, _tone())


def test_rms_level_is_zero_for_silence_and_positive_for_tone():
    assert rms_level(np.zeros(FRAME_SAMPLES, np.int16)) == 0.0
    assert 0.0 < rms_level(_tone()) <= 1.0
    assert rms_level(np.zeros(0, np.int16)) == 0.0


def test_pacer_emits_timestamps_in_20ms_steps_at_real_time():
    async def run():
        pacer = FramePacer()
        stamps = [await pacer.next_timestamp() for _ in range(4)]
        return stamps

    loop = asyncio.new_event_loop()
    import time
    start = time.monotonic()
    stamps = loop.run_until_complete(run())
    elapsed = time.monotonic() - start
    loop.close()
    assert stamps == [0, FRAME_SAMPLES, 2 * FRAME_SAMPLES, 3 * FRAME_SAMPLES]
    assert 0.055 <= elapsed <= 0.2  # three 20 ms waits, with generous scheduling slack


def test_capture_is_padded_with_silence_and_gated_by_mute_and_ptt():
    engine = AudioEngine()
    block = _tone(480).reshape(-1, 1)

    engine._on_mic(block, 480, None, None)
    engine._on_mic(block, 480, None, None)
    out = engine.take_capture(FRAME_SAMPLES)
    assert out.shape == (FRAME_SAMPLES,)
    np.testing.assert_array_equal(out[:480], block[:, 0])   # captured audio comes out in order

    assert engine.take_capture(FRAME_SAMPLES).sum() == 0     # empty buffer -> silence

    engine.set_muted(True)
    engine._on_mic(block, 480, None, None)
    assert engine.take_capture(FRAME_SAMPLES).sum() == 0
    engine.set_muted(False)

    engine.set_ptt_mode(True)
    engine._on_mic(block, 480, None, None)
    assert engine.take_capture(FRAME_SAMPLES).sum() == 0     # PTT mode, button not held
    engine.set_ptt_held(True)
    engine._on_mic(block, 480, None, None)
    assert np.any(engine.take_capture(FRAME_SAMPLES))         # held -> transmit
    engine.set_ptt_held(False)


def test_capture_backlog_is_capped_to_keep_latency_low():
    engine = AudioEngine()
    block = _tone(480).reshape(-1, 1)
    for _ in range(100):  # 1 second of audio arriving with no reader
        engine._on_mic(block, 480, None, None)
    assert engine._capture.size <= 4800  # 100 ms cap


def test_remote_audio_plays_out_and_levels_report_it():
    engine = AudioEngine()
    assert engine.levels() == (0.0, 0.0)
    engine.play_remote(make_frame(_tone(), pts=0))
    _, remote = engine.levels()
    assert remote > 0.0

    outdata = np.zeros((480, 1), dtype=np.int16)
    engine._on_speaker(outdata, 480, None, None)
    assert np.any(outdata)


def test_playback_backlog_is_capped():
    engine = AudioEngine()
    for i in range(50):
        engine.play_remote(make_frame(_tone(), pts=i * FRAME_SAMPLES))
    assert engine._playback.size <= PLAYBACK_MAX_SAMPLES


def test_outbound_track_yields_paced_frames():
    from app.audio.engine import OutboundTrack

    async def run():
        track = OutboundTrack(AudioEngine())
        frames = [await track.recv() for _ in range(3)]
        return [f.pts for f in frames], [f.samples for f in frames]

    pts, sizes = asyncio.new_event_loop().run_until_complete(run())
    assert pts == [0, FRAME_SAMPLES, 2 * FRAME_SAMPLES]
    assert sizes == [FRAME_SAMPLES] * 3
