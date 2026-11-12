"""WebRTC peer connection: offer/answer, audio media, connection state and link quality.

aiortc negotiates DTLS-SRTP for every connection, so the audio is encrypted end to end.
No STUN or TURN servers are configured: the peers connect over host candidates on the LAN.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack

from app.core.config import STATS_INTERVAL_S

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Quality:
    label: str                   # "Good", "Fair", "Poor" or "Measuring"
    rtt_ms: float | None
    loss_pct: float | None


class AudioEndpoint(Protocol):
    """What a PeerSession needs from the local audio engine."""

    def new_outbound_track(self) -> MediaStreamTrack: ...

    def play_remote(self, frame) -> None: ...


def classify_quality(rtt_ms: float, loss_pct: float) -> str:
    if rtt_ms < 150 and loss_pct < 2:
        return "Good"
    if rtt_ms < 300 and loss_pct < 5:
        return "Fair"
    return "Poor"


def quality_from_report(report) -> Quality:
    """Build a Quality from aiortc's stats report (remote-inbound RTP entries)."""
    rtts: list[float] = []
    losses: list[int] = []
    for stat in report.values():
        if getattr(stat, "type", "") != "remote-inbound-rtp":
            continue
        rtt = getattr(stat, "roundTripTime", None)
        if rtt is not None:
            rtts.append(rtt)
        # RTCP reports fraction lost as an 8-bit value (0-255).
        loss = getattr(stat, "fractionLost", None)
        if loss is not None:
            losses.append(loss)
    if not rtts:
        return Quality("Measuring", None, None)
    rtt_ms = max(rtts) * 1000.0
    loss_pct = (max(losses) / 256.0 * 100.0) if losses else 0.0
    return Quality(classify_quality(rtt_ms, loss_pct), rtt_ms, loss_pct)


class PeerSession:
    def __init__(
        self,
        audio: AudioEndpoint,
        on_quality: Callable[[Quality], None],
        on_state: Callable[[str], None],
    ) -> None:
        self._audio = audio
        self._on_quality = on_quality
        self._on_state = on_state
        self._pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self._pc.addTrack(audio.new_outbound_track())
        self._pc.on("connectionstatechange", self._handle_state)
        self._pc.on("track", self._handle_track)
        self._connected = asyncio.Event()
        self._dead = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    async def create_offer(self) -> str:
        await self._pc.setLocalDescription(await self._pc.createOffer())
        return self._pc.localDescription.sdp

    async def accept_offer(self, sdp: str) -> str:
        await self._pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
        await self._pc.setLocalDescription(await self._pc.createAnswer())
        return self._pc.localDescription.sdp

    async def apply_answer(self, sdp: str) -> None:
        await self._pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="answer"))

    async def wait_connected(self, timeout: float) -> bool:
        connected = asyncio.ensure_future(self._connected.wait())
        dead = asyncio.ensure_future(self._dead.wait())
        try:
            await asyncio.wait({connected, dead}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            connected.cancel()
            dead.cancel()
        return self._connected.is_set()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in list(self._tasks):
            task.cancel()
        await self._pc.close()

    # ----- aiortc event handlers (run on the network loop) ------------------

    def _handle_state(self) -> None:
        state = self._pc.connectionState
        log.info("peer connection state: %s", state)
        if state == "connected":
            self._connected.set()
            self._spawn(self._stats_loop())
        elif state in ("failed", "closed"):
            self._dead.set()
        if not self._closed:
            self._on_state(state)

    def _handle_track(self, track: MediaStreamTrack) -> None:
        if track.kind == "audio":
            self._spawn(self._pump(track))

    async def _pump(self, track: MediaStreamTrack) -> None:
        try:
            while True:
                frame = await track.recv()
                self._audio.play_remote(frame)
        except MediaStreamError:
            pass
        except Exception:
            log.exception("remote audio stopped unexpectedly")

    async def _stats_loop(self) -> None:
        while True:
            await asyncio.sleep(STATS_INTERVAL_S)
            try:
                report = await self._pc.getStats()
            except Exception:
                log.debug("stats unavailable", exc_info=True)
                return
            self._on_quality(quality_from_report(report))

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
