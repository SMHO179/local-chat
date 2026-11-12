"""Call lifecycle: hosting, joining, audio devices and status reporting.

asyncio runs in a private worker thread. The UI calls the public methods from the Qt thread
and receives results through Qt signals, which are delivered on the UI thread.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
from enum import Enum

from PySide6.QtCore import QObject, Signal

from app.audio.engine import AudioDeviceError, AudioEngine
from app.core.config import CONNECT_TIMEOUT_S, JOIN_TIMEOUT_S, SIGNAL_PORT
from app.core.room import detect_lan_ip, generate_room_code, normalize_room_code, parse_host_ip, sign_sdp, verify_sdp
from app.networking.peer import PeerSession, Quality
from app.networking.signaling import JoinReply, JoinRequest, SignalingError, SignalingServer, send_join

log = logging.getLogger(__name__)

_DEAD_STATES = ("failed", "closed")


class Phase(Enum):
    IDLE = "idle"
    WAITING = "waiting"          # host: room open, waiting for the other computer
    CONNECTING = "connecting"
    CONNECTED = "connected"


class CallController(QObject):
    phase_changed = Signal(object)        # Phase
    notice = Signal(str, str)             # level: "info" | "warning" | "error"; text
    room_ready = Signal(str, str)         # LAN IP, room code
    remote_name_changed = Signal(str)
    quality_changed = Signal(object)      # Quality, or None when there is no connection

    def __init__(self, audio: AudioEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._audio = audio
        self._phase = Phase.IDLE
        self._role: str | None = None          # "host" | "client" while a call is active
        self._code: str | None = None
        self._peer: PeerSession | None = None
        self._server: SignalingServer | None = None
        self.selected_microphone: int | None = None
        self.selected_speaker: int | None = None

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="local-chat-network", daemon=True)
        self._thread.start()

    # ----- called from the UI thread ----------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    def start_hosting(self) -> None:
        self._submit(self._host())

    def join(self, host_ip: str, code: str) -> None:
        """Validate the inputs (raises ValueError with a user-facing message), then join."""
        ip = parse_host_ip(host_ip)
        room = normalize_room_code(code)
        self._submit(self._client(ip, room))

    def disconnect(self) -> None:
        self._submit(self._leave())

    def set_muted(self, muted: bool) -> None:
        self._audio.set_muted(muted)

    def set_ptt_mode(self, enabled: bool) -> None:
        self._audio.set_ptt_mode(enabled)

    def set_ptt_held(self, held: bool) -> None:
        self._audio.set_ptt_held(held)

    def select_microphone(self, device: int | None) -> None:
        self.selected_microphone = device
        if self._role is not None:
            self._submit(self._reopen_microphone())

    def select_speaker(self, device: int | None) -> None:
        self.selected_speaker = device
        if self._role is not None:
            self._submit(self._reopen_speaker())

    def shutdown(self) -> None:
        if not self._thread.is_alive():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._leave(), self._loop).result(timeout=3)
        except Exception:
            log.warning("call did not end cleanly on shutdown", exc_info=True)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3)

    # ----- network thread ----------------------------------------------------

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
        self._loop.close()

    def _submit(self, coro) -> None:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.add_done_callback(self._on_task_done)

    def _on_task_done(self, future) -> None:
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:
            log.error("network task failed", exc_info=exc)
            self._say("error", "Something went wrong. Check the log for details.")

    def _say(self, level: str, text: str) -> None:
        log.info("[%s] %s", level, text)
        self.notice.emit(level, text)

    def _set_phase(self, phase: Phase) -> None:
        self._phase = phase
        self.phase_changed.emit(phase)

    def _new_peer(self) -> PeerSession:
        peer: PeerSession | None = None

        def on_state(state: str) -> None:
            if state in _DEAD_STATES and peer is not None:
                asyncio.ensure_future(self._peer_lost(peer))

        peer = PeerSession(self._audio, on_quality=self._on_quality, on_state=on_state)
        return peer

    def _on_quality(self, quality: Quality) -> None:
        self.quality_changed.emit(quality)

    # ----- hosting -----------------------------------------------------------

    async def _host(self) -> None:
        if self._role is not None:
            return
        lan_ip = detect_lan_ip()
        code = generate_room_code()
        self._role, self._code = "host", code
        self._open_audio()
        self._server = SignalingServer(
            bind_ip=lan_ip,
            port=SIGNAL_PORT,
            code=code,
            handler=self._on_join,
            host_name=socket.gethostname(),
            on_lockout=self._on_lockout,
        )
        try:
            await self._server.start()
        except SignalingError as exc:
            await self._reset_to_idle("error", str(exc))
            return
        if lan_ip == "127.0.0.1":
            self._say("warning", "No local network adapter was found. Only this computer can join.")
        self._set_phase(Phase.WAITING)
        self.room_ready.emit(lan_ip, code)

    async def _on_join(self, request: JoinRequest) -> JoinReply:
        peer = self._new_peer()
        self._peer = peer
        try:
            answer_sdp = await peer.accept_offer(request.sdp)
        except Exception:
            await self._close_peer()
            raise
        self._set_phase(Phase.CONNECTING)
        self.remote_name_changed.emit(request.peer_name)
        asyncio.ensure_future(self._watch_connection(peer))
        return JoinReply(
            sdp=answer_sdp,
            mac=sign_sdp(self._code, "answer", answer_sdp),
            host_name=socket.gethostname(),
        )

    def _on_lockout(self) -> None:
        asyncio.ensure_future(self._reset_to_idle(
            "warning", "Too many wrong room codes were entered, so the room was closed. Create a new call."
        ))

    # ----- joining -----------------------------------------------------------

    async def _client(self, host_ip: str, code: str) -> None:
        if self._role is not None:
            return
        self._role, self._code = "client", code
        self._open_audio()
        self._set_phase(Phase.CONNECTING)
        peer = self._new_peer()
        self._peer = peer
        try:
            offer_sdp = await peer.create_offer()
            reply = await send_join(
                host_ip, SIGNAL_PORT, code, offer_sdp,
                sign_sdp(code, "offer", offer_sdp), socket.gethostname(), JOIN_TIMEOUT_S,
            )
            if not verify_sdp(code, "answer", reply.sdp, reply.mac):
                raise SignalingError("The host's reply did not pass verification. Check the room code.")
            await peer.apply_answer(reply.sdp)
        except SignalingError as exc:
            await self._reset_to_idle("error", f"Could not join: {exc}")
            return
        except Exception:
            log.exception("join failed")
            await self._reset_to_idle("error", "Could not join the call.")
            return
        self.remote_name_changed.emit(reply.host_name)
        asyncio.ensure_future(self._watch_connection(peer))

    # ----- connection lifecycle ----------------------------------------------

    async def _watch_connection(self, peer: PeerSession) -> None:
        if await peer.wait_connected(CONNECT_TIMEOUT_S):
            if peer is self._peer:
                self._set_phase(Phase.CONNECTED)
                self._say("info", "Connected.")
            return
        if peer is self._peer:
            await self._peer_lost(
                peer,
                "Could not connect directly. Make sure both computers are on the same network "
                "and that the firewall allows local-chat.",
            )

    async def _peer_lost(self, peer: PeerSession, reason: str | None = None) -> None:
        if peer is not self._peer:
            return
        if reason is None:
            reason = "The connection was lost."
        await self._close_peer()
        if self._role == "host" and self._server is not None:
            self._server.release_slot()
            self._set_phase(Phase.WAITING)
            self._say("warning", f"{reason} Waiting for another connection.")
        else:
            await self._reset_to_idle("warning", reason)

    async def _close_peer(self) -> None:
        peer, self._peer = self._peer, None
        if peer is not None:
            await peer.close()
        self.remote_name_changed.emit("")
        self.quality_changed.emit(None)

    async def _leave(self) -> None:
        if self._role is None:
            return
        await self._reset_to_idle("info", "Call ended.")

    async def _reset_to_idle(self, level: str, text: str) -> None:
        await self._close_peer()
        if self._server is not None:
            await self._server.stop()
            self._server = None
        self._audio.close_streams()
        self._role = None
        self._code = None
        self._set_phase(Phase.IDLE)
        self._say(level, text)

    # ----- audio devices -----------------------------------------------------

    def _open_audio(self) -> None:
        try:
            self._audio.open_input(self.selected_microphone)
        except AudioDeviceError as exc:
            self._say("warning", f"Microphone unavailable ({exc}). You can still listen.")
        try:
            self._audio.open_output(self.selected_speaker)
        except AudioDeviceError as exc:
            self._say("warning", f"Speaker unavailable ({exc}). You can still talk.")

    async def _reopen_microphone(self) -> None:
        try:
            self._audio.open_input(self.selected_microphone)
        except AudioDeviceError as exc:
            self._say("warning", f"Microphone unavailable ({exc}).")

    async def _reopen_speaker(self) -> None:
        try:
            self._audio.open_output(self.selected_speaker)
        except AudioDeviceError as exc:
            self._say("warning", f"Speaker unavailable ({exc}).")
