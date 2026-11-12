"""Main window: switches between the start screen and the call screen."""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QMainWindow, QStackedWidget

from app.audio.engine import AudioEngine
from app.core.call_controller import CallController, Phase
from app.ui.call_screen import CallScreen
from app.ui.home_screen import HomeScreen


class MainWindow(QMainWindow):
    def __init__(self, controller: CallController, audio: AudioEngine) -> None:
        super().__init__()
        self.setWindowTitle("local-chat")
        self.resize(640, 720)
        self.setMinimumSize(560, 640)

        self._home = HomeScreen(controller)
        self._call = CallScreen(controller, audio)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._home)
        self._stack.addWidget(self._call)
        self.setCentralWidget(self._stack)

        controller.phase_changed.connect(self._on_phase)
        controller.notice.connect(self._on_notice)
        controller.room_ready.connect(self._call.set_room)
        controller.remote_name_changed.connect(self._call.set_remote_name)
        controller.quality_changed.connect(self._call.set_quality)

    @Slot(object)
    def _on_phase(self, phase: Phase) -> None:
        if phase is Phase.IDLE:
            self._stack.setCurrentWidget(self._home)
            return
        if self._stack.currentWidget() is not self._call:
            self._call.refresh_devices()
            self._stack.setCurrentWidget(self._call)
            self._call.setFocus()
        self._call.set_phase(phase)

    @Slot(str, str)
    def _on_notice(self, level: str, text: str) -> None:
        if self._stack.currentWidget() is self._home:
            self._home.show_notice(level, text)
        else:
            self._call.show_notice(level, text)
