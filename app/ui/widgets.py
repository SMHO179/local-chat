"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.ui.styles import ACCENT, BORDER, GOOD


class LevelMeter(QWidget):
    """Horizontal audio level bar with a quick attack and a slower release."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self.setMinimumHeight(10)
        self.setMaximumHeight(10)

    def set_level(self, level: float) -> None:
        self._value = max(level, self._value * 0.85)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.setBrush(QColor("#0b0f15"))
        painter.drawRoundedRect(rect, 5, 5)
        width = rect.width() * max(0.0, min(1.0, self._value))
        if width >= 1:
            fill = QRectF(rect.left(), rect.top(), width, rect.height())
            gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
            gradient.setColorAt(0.0, QColor(ACCENT))
            gradient.setColorAt(1.0, QColor(GOOD))
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(fill, 5, 5)
        painter.end()
