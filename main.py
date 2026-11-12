"""local-chat: a private one-to-one voice call between two computers on the same network."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from app.audio.engine import AudioEngine
from app.core.call_controller import CallController
from app.ui.main_window import MainWindow
from app.ui.styles import APP_STYLESHEET


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("local-chat")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    audio = AudioEngine()
    controller = CallController(audio)
    window = MainWindow(controller, audio)
    app.aboutToQuit.connect(controller.shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
