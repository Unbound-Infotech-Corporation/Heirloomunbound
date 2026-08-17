"""OBS-style mixer: devices, gain, gate, mute, monitor, live listen, session volume."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from heirloom.audio import list_input_devices, list_output_devices, play_test_tone
from heirloom.mixer import MixerSession


class MixerPanel(QWidget):
    settings_changed = Signal(dict)
    live_listen_toggled = Signal(bool)

    def __init__(self, mixer: MixerSession, parent=None):
        super().__init__(parent)
        self.mixer = mixer
        self._settings: dict = {}
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        io = QGroupBox("Devices")
        io_form = QFormLayout(io)
        self.input_combo = QComboBox()
        self.output_combo = QComboBox()
        self.rate_combo = QComboBox()
        for rate in (16000, 44100, 48000):
            self.rate_combo.addItem(f"{rate} Hz", rate)
        io_form.addRow("Microphone", self.input_combo)
        io_form.addRow("Playback", self.output_combo)
        io_form.addRow("Sample rate", self.rate_combo)
        root.addWidget(io)

        mic = QGroupBox("Microphone")
        mic_form = QFormLayout(mic)
        self.gain = QSlider(Qt.Horizontal)
        self.gain.setRange(0, 200)
        self.gate = QSlider(Qt.Horizontal)
        self.gate.setRange(-80, 0)
        self.hpf = QSlider(Qt.Horizontal)
        self.hpf.setRange(0, 200)
        self.mute_in = QCheckBox("Mute input")
        self.ns = QCheckBox("Noise suppression")
        self.monitor = QCheckBox("Monitor input (headphones)")
        self.live = QCheckBox("Live listen — wake when someone enters the room")
        self.vu = QProgressBar()
        self.vu.setRange(0, 100)
        self.vu.setTextVisible(True)
        self.vu.setFormat("Input %p%")
        mic_form.addRow("Gain", self.gain)
        mic_form.addRow("Noise gate (dB)", self.gate)
        mic_form.addRow("High-pass (Hz)", self.hpf)
        mic_form.addRow(self.mute_in)
        mic_form.addRow(self.ns)
        mic_form.addRow(self.monitor)
        mic_form.addRow(self.live)
        mic_form.addRow(self.vu)
        root.addWidget(mic)

        out = QGroupBox("Heirloom output (Windows mixer session)")
        out_form = QFormLayout(out)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.mute_out = QCheckBox("Mute output")
        self.vol_label = QLabel("80%")
        row = QHBoxLayout()
        row.addWidget(self.vol)
        row.addWidget(self.vol_label)
        out_form.addRow("Session volume", row)
        out_form.addRow(self.mute_out)
        test = QPushButton("Play test tone")
        test.clicked.connect(self._test_tone)
        refresh = QPushButton("Refresh devices")
        refresh.clicked.connect(self.refresh_devices)
        btn_row = QHBoxLayout()
        btn_row.addWidget(test)
        btn_row.addWidget(refresh)
        out_form.addRow(btn_row)
        hint = QLabel(
            "Windows volume mixer lists this as Heirloom, not python.exe. "
            "Moving this slider (or the Windows mixer slider) changes only this app."
        )
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        out_form.addRow(hint)
        root.addWidget(out)
        root.addStretch(1)

        for w in (self.input_combo, self.output_combo, self.rate_combo):
            w.currentIndexChanged.connect(self._emit)
        for w in (self.gain, self.gate, self.hpf, self.vol):
            w.valueChanged.connect(self._emit)
        for w in (self.mute_in, self.ns, self.monitor, self.live, self.mute_out):
            w.toggled.connect(self._on_toggle)

        self.refresh_devices()

    def _on_toggle(self, *_):
        if self.sender() is self.live:
            self.live_listen_toggled.emit(self.live.isChecked())
        self._emit()

    def refresh_devices(self) -> None:
        self._loading = True
        cur_in = self.input_combo.currentData()
        cur_out = self.output_combo.currentData()
        self.input_combo.clear()
        self.output_combo.clear()
        self.input_combo.addItem("System default", "default")
        self.output_combo.addItem("System default", "default")
        for d in list_input_devices():
            self.input_combo.addItem(d["name"], d["id"])
        for d in list_output_devices():
            self.output_combo.addItem(d["name"], d["id"])
        self._select(self.input_combo, cur_in)
        self._select(self.output_combo, cur_out)
        self._loading = False
        self._emit()

    def _select(self, combo: QComboBox, value) -> None:
        if value is None:
            return
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def apply_settings(self, settings: dict) -> None:
        self._loading = True
        self._settings = dict(settings or {})
        self._select(self.input_combo, settings.get("input_device_id") or "default")
        self._select(self.output_combo, settings.get("output_device_id") or "default")
        rate = int(settings.get("sample_rate") or 48000)
        idx = self.rate_combo.findData(rate)
        if idx >= 0:
            self.rate_combo.setCurrentIndex(idx)
        self.gain.setValue(int(settings.get("input_gain") or 100))
        self.gate.setValue(int(settings.get("noise_gate_db") or -45))
        self.hpf.setValue(int(settings.get("high_pass_hz") or 80))
        self.mute_in.setChecked(bool(settings.get("mute_input")))
        self.ns.setChecked(bool(settings.get("noise_suppression")))
        self.monitor.setChecked(bool(settings.get("monitor_input")))
        self.live.setChecked(bool(settings.get("live_listen")))
        self.vol.setValue(int(settings.get("output_volume") or 80))
        self.vol_label.setText(f"{self.vol.value()}%")
        self.mute_out.setChecked(bool(settings.get("mute_output")))
        self._loading = False

    def collect(self) -> dict:
        return {
            **self._settings,
            "input_device_id": self.input_combo.currentData() or "default",
            "output_device_id": self.output_combo.currentData() or "default",
            "sample_rate": int(self.rate_combo.currentData() or 48000),
            "input_gain": int(self.gain.value()),
            "noise_gate_db": int(self.gate.value()),
            "high_pass_hz": int(self.hpf.value()),
            "mute_input": self.mute_in.isChecked(),
            "noise_suppression": self.ns.isChecked(),
            "monitor_input": self.monitor.isChecked(),
            "live_listen": self.live.isChecked(),
            "output_volume": int(self.vol.value()),
            "mute_output": self.mute_out.isChecked(),
        }

    def _emit(self, *_):
        if self._loading:
            return
        self.vol_label.setText(f"{self.vol.value()}%")
        payload = self.collect()
        self.mixer.set_device(payload["output_device_id"])
        self.mixer.set_volume(payload["output_volume"])
        self.mixer.set_mute(payload["mute_output"])
        self.settings_changed.emit(payload)

    def set_level(self, pct: float) -> None:
        # Recorder emits 0..1; accept either.
        value = pct * 100 if pct <= 1.0 else pct
        self.vu.setValue(max(0, min(100, int(value))))

    def _test_tone(self) -> None:
        play_test_tone(
            self.output_combo.currentData() or "default",
            self.vol.value(),
        )
