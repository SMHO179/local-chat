"""Call screen: connection state, participant, audio controls and device selection."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.audio.engine import AudioDevice, AudioDeviceError, AudioEngine, list_devices
from app.core.call_controller import CallController, Phase
from app.networking.peer import Quality
from app.ui.widgets import LevelMeter

_PHASE_TEXT = {
    Phase.IDLE: ("Not connected", "idle"),
    Phase.WAITING: ("Waiting for the other computer", "waiting"),
    Phase.CONNECTING: ("Connecting", "connecting"),
    Phase.CONNECTED: ("Connected", "connected"),
}


class CallScreen(QWidget):
    def __init__(self, controller: CallController, audio: AudioEngine, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._audio = audio
        self._muted = False
        self._ptt_on = False
        self._ptt_held = False
        self._phase = Phase.IDLE
        self._remote_name = ""
        self.setFocusPolicy(Qt.StrongFocus)

        # Header
        self._dot = QLabel("●")
        self._dot.setObjectName("dot")
        self._status = QLabel()
        self._status.setObjectName("heading")
        self._quality = QLabel()
        self._quality.setObjectName("quality")
        header = QHBoxLayout()
        header.addWidget(self._dot)
        header.addWidget(self._status)
        header.addStretch(1)
        header.addWidget(self._quality)

        # Room details (host only, while waiting)
        self._room_card = _card()
        room_grid = QGridLayout(self._room_card)
        room_grid.setContentsMargins(20, 16, 20, 16)
        room_grid.addWidget(_muted_label("Your address on this network"), 0, 0)
        room_grid.addWidget(_muted_label("Room code"), 0, 1)
        self._ip_value = QLabel("—")
        self._ip_value.setObjectName("value")
        self._code_value = QLabel("—")
        self._code_value.setObjectName("code")
        self._code_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        room_grid.addWidget(self._ip_value, 1, 0)
        room_grid.addWidget(self._code_value, 1, 1)
        hint = _muted_label("The other computer enters this address and room code on its Join Call screen.")
        hint.setWordWrap(True)
        room_grid.addWidget(hint, 2, 0, 1, 2)

        # Participant
        self._peer_card = _card()
        peer_layout = QHBoxLayout(self._peer_card)
        peer_layout.setContentsMargins(20, 16, 20, 16)
        self._avatar = QLabel("?")
        self._avatar.setObjectName("avatar")
        self._avatar.setAlignment(Qt.AlignCenter)
        names = QVBoxLayout()
        self._peer_name = QLabel("No one yet")
        self._peer_name.setObjectName("value")
        self._peer_sub = _muted_label("")
        names.addWidget(self._peer_name)
        names.addWidget(self._peer_sub)
        peer_layout.addWidget(self._avatar)
        peer_layout.addSpacing(12)
        peer_layout.addLayout(names, 1)

        # Audio activity
        self._meter_card = _card()
        meters = QGridLayout(self._meter_card)
        meters.setContentsMargins(20, 16, 20, 16)
        meters.setHorizontalSpacing(14)
        meters.setVerticalSpacing(10)
        self._mic_meter = LevelMeter()
        self._remote_meter = LevelMeter()
        meters.addWidget(_muted_label("You"), 0, 0)
        meters.addWidget(self._mic_meter, 0, 1)
        meters.addWidget(_muted_label("Them"), 1, 0)
        meters.addWidget(self._remote_meter, 1, 1)
        self._mic_status = QLabel()
        self._mic_status.setObjectName("value")
        meters.addWidget(self._mic_status, 2, 0, 1, 2)

        # Controls
        self._mute_btn = QPushButton("Mute")
        self._mute_btn.setObjectName("toggle")
        self._mute_btn.setCheckable(True)
        self._ptt_check = QCheckBox("Push-to-talk mode")
        self._ptt_btn = QPushButton("Hold to talk")
        self._ptt_btn.setObjectName("ptt")
        self._ptt_btn.setEnabled(False)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setObjectName("danger")
        for widget in (self._mute_btn, self._ptt_btn, self._ptt_check, self._disconnect_btn):
            widget.setFocusPolicy(Qt.NoFocus)  # keeps Space free for push-to-talk
        controls = QHBoxLayout()
        controls.addWidget(self._mute_btn)
        controls.addWidget(self._ptt_btn)
        controls.addStretch(1)
        controls.addWidget(self._disconnect_btn)
        ptt_row = QHBoxLayout()
        ptt_row.addWidget(self._ptt_check)
        ptt_row.addStretch(1)

        # Devices
        self._mic_combo = QComboBox()
        self._speaker_combo = QComboBox()
        for combo in (self._mic_combo, self._speaker_combo):
            combo.setFocusPolicy(Qt.NoFocus)
        devices = QGridLayout()
        devices.setHorizontalSpacing(12)
        devices.addWidget(_muted_label("Microphone"), 0, 0)
        devices.addWidget(_muted_label("Speaker"), 0, 1)
        devices.addWidget(self._mic_combo, 1, 0)
        devices.addWidget(self._speaker_combo, 1, 1)

        self._notice = QLabel()
        self._notice.setObjectName("notice")
        self._notice.setWordWrap(True)
        self._notice.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 28)
        layout.setSpacing(14)
        layout.addLayout(header)
        layout.addWidget(self._room_card)
        layout.addWidget(self._peer_card)
        layout.addWidget(self._meter_card)
        layout.addLayout(ptt_row)
        layout.addLayout(controls)
        layout.addStretch(1)
        layout.addLayout(devices)
        layout.addWidget(self._notice)

        self._mute_btn.toggled.connect(self._on_mute)
        self._ptt_check.toggled.connect(self._on_ptt_mode)
        self._ptt_btn.pressed.connect(lambda: self._set_ptt_held(True))
        self._ptt_btn.released.connect(lambda: self._set_ptt_held(False))
        self._disconnect_btn.clicked.connect(self._controller.disconnect)
        self._mic_combo.activated.connect(self._on_mic_selected)
        self._speaker_combo.activated.connect(self._on_speaker_selected)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.set_phase(Phase.IDLE)

    # ----- state from the controller ----------------------------------------

    @Slot(object)
    def set_phase(self, phase: Phase) -> None:
        self._phase = phase
        text, state = _PHASE_TEXT[phase]
        self._status.setText(text)
        self._dot.setProperty("state", state)
        _repolish(self._dot)
        self._room_card.setVisible(phase is Phase.WAITING)
        self._peer_sub.setText({
            Phase.CONNECTED: "Live audio",
            Phase.CONNECTING: "Setting up the connection",
        }.get(phase, ""))
        self._update_peer_name()
        if phase is Phase.IDLE:
            self._quality.setText("")

    @Slot(str, str)
    def set_room(self, ip: str, code: str) -> None:
        self._ip_value.setText(ip)
        self._code_value.setText(code)

    @Slot(str)
    def set_remote_name(self, name: str) -> None:
        self._remote_name = name
        self._update_peer_name()

    @Slot(object)
    def set_quality(self, quality: Quality | None) -> None:
        if quality is None:
            self._quality.setText("")
            return
        loss = f"{quality.loss_pct:.1f}% loss" if quality.loss_pct is not None else ""
        rtt = f"{quality.rtt_ms:.0f} ms" if quality.rtt_ms is not None else ""
        parts = [part for part in (quality.label, rtt, loss) if part]
        self._quality.setText("Connection: " + " · ".join(parts))
        self._quality.setProperty("level", quality.label)
        _repolish(self._quality)

    def show_notice(self, level: str, text: str) -> None:
        self._notice.setProperty("level", level)
        _repolish(self._notice)
        self._notice.setText(text)
        self._notice.setVisible(bool(text))

    def refresh_devices(self) -> None:
        try:
            inputs, outputs = list_devices()
        except AudioDeviceError as exc:
            inputs, outputs = [], []
            self.show_notice("warning", str(exc))
        _fill_combo(self._mic_combo, inputs, self._controller.selected_microphone)
        _fill_combo(self._speaker_combo, outputs, self._controller.selected_speaker)

    # ----- user actions -----------------------------------------------------

    def _update_peer_name(self) -> None:
        if self._remote_name:
            self._peer_name.setText(self._remote_name)
            self._avatar.setText(self._remote_name[0].upper())
            return
        self._avatar.setText("?")
        self._peer_name.setText({
            Phase.WAITING: "Waiting for a participant",
            Phase.CONNECTING: "Connecting",
            Phase.CONNECTED: "Connected",
        }.get(self._phase, "No one yet"))

    @Slot(bool)
    def _on_mute(self, muted: bool) -> None:
        self._muted = muted
        self._mute_btn.setText("Unmute" if muted else "Mute")
        self._controller.set_muted(muted)
        self._update_mic_status()

    @Slot(bool)
    def _on_ptt_mode(self, enabled: bool) -> None:
        self._ptt_on = enabled
        self._ptt_btn.setEnabled(enabled)
        if not enabled:
            self._set_ptt_held(False)
        self._controller.set_ptt_mode(enabled)
        self._update_mic_status()

    def _set_ptt_held(self, held: bool) -> None:
        if held and not self._ptt_on:
            return
        self._ptt_held = held
        self._controller.set_ptt_held(held)
        self._update_mic_status()

    @Slot(int)
    def _on_mic_selected(self, _row: int) -> None:
        self._controller.select_microphone(self._mic_combo.currentData())
        self._update_mic_status()

    @Slot(int)
    def _on_speaker_selected(self, _row: int) -> None:
        self._controller.select_speaker(self._speaker_combo.currentData())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and self._ptt_on and not event.isAutoRepeat():
            self._set_ptt_held(True)
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and self._ptt_on and not event.isAutoRepeat():
            self._set_ptt_held(False)
            return
        super().keyReleaseEvent(event)

    # ----- periodic refresh -------------------------------------------------

    def _tick(self) -> None:
        mic, remote = self._audio.levels()
        self._mic_meter.set_level(mic)
        self._remote_meter.set_level(remote)
        self._update_mic_status()

    def _update_mic_status(self) -> None:
        if not self._audio.input_open:
            text = "Microphone unavailable"
        elif self._muted:
            text = "Muted"
        elif self._ptt_on and not self._ptt_held:
            text = "Push-to-talk: hold the button or Space to speak"
        elif self._ptt_on:
            text = "Transmitting"
        else:
            text = "Microphone live"
        self._mic_status.setText(text)


def _fill_combo(combo: QComboBox, devices: list[AudioDevice], selected: int | None) -> None:
    combo.blockSignals(True)
    combo.clear()
    for device in devices:
        combo.addItem(device.name, device.index)
    if not devices:
        combo.addItem("No devices found")
        combo.setEnabled(False)
    else:
        combo.setEnabled(True)
        position = next((i for i, d in enumerate(devices) if d.index == selected), 0)
        combo.setCurrentIndex(position)
    combo.blockSignals(False)


def _card() -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    return card


def _muted_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    return label


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
