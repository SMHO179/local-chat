"""Builds the real window offscreen and checks the screens respond correctly."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.audio.engine import AudioEngine
from app.core.call_controller import CallController, Phase


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_main_window_starts_on_home_and_shows_validation_error(app):
    from app.ui.main_window import MainWindow

    audio = AudioEngine()
    controller = CallController(audio)
    window = MainWindow(controller, audio)
    try:
        window.show()
        app.processEvents()
        assert window._stack.currentWidget() is window._home
        window._home._host_input.setText("8.8.8.8")
        window._home._code_input.setText("K7M2QF")
        window._home._on_join()
        assert window._home._notice.isVisibleTo(window._home)
        assert "local network" in window._home._notice.text()
        window._home._host_input.setText("192.168.1.5")
        window._home._code_input.setText("K7")
        window._home._on_join()
        assert "6 letters" in window._home._notice.text()
    finally:
        window.close()
        controller.shutdown()


def test_call_screen_controls_update_state(app):
    from app.ui.call_screen import CallScreen

    audio = AudioEngine()
    controller = CallController(audio)
    screen = CallScreen(controller, audio)
    try:
        screen.set_phase(Phase.WAITING)
        screen.set_room("192.168.137.1", "K7M2QF")
        assert screen._code_value.text() == "K7M2QF"
        assert not screen._room_card.isHidden()
        screen.set_phase(Phase.CONNECTING)
        screen.set_phase(Phase.CONNECTED)
        screen.set_remote_name("laptop")
        assert screen._peer_name.text() == "laptop"
        assert screen._avatar.text() == "L"

        screen._ptt_check.setChecked(True)
        assert screen._ptt_btn.isEnabled()
        if audio.input_open:
            assert "hold" in screen._mic_status.text().lower()
        else:
            assert screen._mic_status.text() == "Microphone unavailable"
        screen._mute_btn.setChecked(True)
        assert screen._mute_btn.text() == "Unmute"
        if audio.input_open:
            assert screen._mic_status.text() == "Muted"
    finally:
        controller.shutdown()
