"""Start screen: create a call or join one."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.call_controller import CallController
from app.core.config import ROOM_CODE_LENGTH


class HomeScreen(QWidget):
    def __init__(self, controller: CallController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller

        brand = QLabel("local-chat")
        brand.setObjectName("brand")
        tagline = QLabel("Private voice calls between two computers on the same network.")
        tagline.setObjectName("tagline")
        tagline.setWordWrap(True)

        # Create a call
        create_card = _card()
        create_layout = QVBoxLayout(create_card)
        create_layout.addWidget(_heading("Create a call"))
        create_text = QLabel("Opens a room with a code. The other computer joins with your address and that code.")
        create_text.setObjectName("muted")
        create_text.setWordWrap(True)
        create_layout.addWidget(create_text)
        self._create_btn = QPushButton("Create Call")
        self._create_btn.setObjectName("primary")
        self._create_btn.setCursor(Qt.PointingHandCursor)
        self._create_btn.clicked.connect(self._on_create)
        create_layout.addWidget(self._create_btn)

        # Join a call
        join_card = _card()
        join_layout = QVBoxLayout(join_card)
        join_layout.addWidget(_heading("Join a call"))
        self._host_input = QLineEdit()
        self._host_input.setPlaceholderText("Host IP address, e.g. 192.168.137.1")
        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("Room code")
        self._code_input.setMaxLength(ROOM_CODE_LENGTH + 2)  # allow a separator
        self._code_input.textEdited.connect(lambda text: self._code_input.setText(text.upper()))
        self._code_input.returnPressed.connect(self._on_join)
        self._host_input.returnPressed.connect(self._on_join)
        join_layout.addWidget(self._host_input)
        join_layout.addWidget(self._code_input)
        self._join_btn = QPushButton("Join Call")
        self._join_btn.setCursor(Qt.PointingHandCursor)
        self._join_btn.clicked.connect(self._on_join)
        join_layout.addWidget(self._join_btn)

        self._notice = QLabel()
        self._notice.setObjectName("notice")
        self._notice.setWordWrap(True)
        self._notice.hide()

        footer = QLabel("Audio travels directly between the two computers, encrypted with DTLS-SRTP. "
                        "No internet connection or external server is used.")
        footer.setObjectName("muted")
        footer.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 28)
        layout.setSpacing(16)
        layout.addWidget(brand)
        layout.addWidget(tagline)
        layout.addSpacing(8)
        layout.addWidget(create_card)
        layout.addWidget(join_card)
        layout.addStretch(1)
        layout.addWidget(self._notice)
        layout.addWidget(footer)

    def show_notice(self, level: str, text: str) -> None:
        self._notice.setProperty("level", level)
        _repolish(self._notice)
        self._notice.setText(text)
        self._notice.setVisible(bool(text))

    def focus_join(self) -> None:
        self._host_input.setFocus()

    @Slot()
    def _on_create(self) -> None:
        self.show_notice("info", "")
        self._controller.start_hosting()

    @Slot()
    def _on_join(self) -> None:
        try:
            self._controller.join(self._host_input.text(), self._code_input.text())
        except ValueError as exc:
            self.show_notice("error", str(exc))
            return
        self.show_notice("info", "")


def _card() -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    return card


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("heading")
    return label


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
