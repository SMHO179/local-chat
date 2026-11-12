"""Drives two real CallControllers (host and client) through the full call lifecycle.

Uses the production code paths: signaling, WebRTC, state machine and Qt signal delivery.
Audio devices are not required; if none exist the controllers keep running and report it.
"""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.audio.engine import AudioEngine
from app.core.call_controller import CallController, Phase
from app.core.room import detect_lan_ip


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def wait_until(app, predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    app.processEvents()
    return predicate()


class Recorder:
    def __init__(self, controller: CallController):
        self.phases: list[Phase] = []
        self.notices: list[tuple[str, str]] = []
        self.room: tuple[str, str] | None = None
        self.remote_names: list[str] = []
        controller.phase_changed.connect(self.phases.append)
        controller.notice.connect(lambda level, text: self.notices.append((level, text)))
        controller.room_ready.connect(lambda ip, code: setattr(self, "room", (ip, code)))
        controller.remote_name_changed.connect(self.remote_names.append)

    @property
    def last_phase(self):
        return self.phases[-1] if self.phases else None

    def has_notice(self, fragment: str) -> bool:
        return any(fragment in text for _, text in self.notices)


@pytest.mark.skipif(detect_lan_ip() == "127.0.0.1", reason="needs a LAN interface")
def test_full_call_lifecycle_between_two_controllers(qapp):
    host = CallController(AudioEngine())
    client = CallController(AudioEngine())
    host_rec, client_rec = Recorder(host), Recorder(client)
    try:
        host.start_hosting()
        assert wait_until(qapp, lambda: host_rec.last_phase is Phase.WAITING, 15), host_rec.notices
        ip, code = host_rec.room
        assert ip == detect_lan_ip() and len(code) == 6

        # Wrong code is refused and the host keeps waiting.
        client.join(ip, "ZZZZZZ")
        assert wait_until(qapp, lambda: client_rec.has_notice("Wrong room code"), 15), client_rec.notices
        assert host_rec.last_phase is Phase.WAITING

        # Correct code connects both sides.
        client.join(ip, code.lower())
        assert wait_until(qapp, lambda: host_rec.last_phase is Phase.CONNECTED
                          and client_rec.last_phase is Phase.CONNECTED, 40), (host_rec.notices, client_rec.notices)
        assert client_rec.remote_names and host_rec.remote_names
        assert host_rec.has_notice("Connected.") and client_rec.has_notice("Connected.")

        # Client hangs up: client returns to idle, host goes back to waiting for a new peer.
        client.disconnect()
        assert wait_until(qapp, lambda: client_rec.last_phase is Phase.IDLE, 15)
        assert wait_until(qapp, lambda: host_rec.last_phase is Phase.WAITING, 30), host_rec.notices
        assert host_rec.has_notice("Waiting for another connection")
    finally:
        client.shutdown()
        host.shutdown()


def test_join_validation_errors_are_raised_before_any_network_work(qapp):
    controller = CallController(AudioEngine())
    try:
        with pytest.raises(ValueError, match="IPv4"):
            controller.join("not-an-ip", "K7M2QF")
        with pytest.raises(ValueError, match="6"):
            controller.join("192.168.1.5", "K7M")
        with pytest.raises(ValueError, match="local network"):
            controller.join("8.8.8.8", "K7M2QF")
    finally:
        controller.shutdown()


def test_join_to_unreachable_host_reports_error_and_returns_to_idle(qapp):
    controller = CallController(AudioEngine())
    rec = Recorder(controller)
    try:
        controller.join("192.168.254.254", "K7M2QF")
        assert wait_until(qapp, lambda: rec.has_notice("Could not join"), 25), rec.notices
        assert rec.last_phase is Phase.IDLE
    finally:
        controller.shutdown()
