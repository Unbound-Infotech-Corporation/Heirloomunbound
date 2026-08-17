"""One-click local model provision + per-feature backend picker."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from heirloom import api, models


class _ProvisionJob(QThread):
    line = Signal(str)
    done = Signal(dict)

    def __init__(self, features: list[str] | None, parent=None):
        super().__init__(parent)
        self.features = features

    def run(self) -> None:  # pragma: no cover
        try:
            result = models.provision(self.features, progress=self.line.emit)
            self.done.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"error": str(exc), "log": [str(exc)]})


class ModelsPanel(QWidget):
    map_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._combos: dict[str, QComboBox] = {}
        self._job: _ProvisionJob | None = None
        self._map: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        probe = QGroupBox("This PC")
        probe_form = QFormLayout(probe)
        self.gpu_label = QLabel("—")
        self.ollama_label = QLabel("—")
        self.whisper_label = QLabel("—")
        self.piper_label = QLabel("—")
        for lab in (self.gpu_label, self.ollama_label, self.whisper_label, self.piper_label):
            lab.setWordWrap(True)
        probe_form.addRow("GPU", self.gpu_label)
        probe_form.addRow("Ollama", self.ollama_label)
        probe_form.addRow("Whisper", self.whisper_label)
        probe_form.addRow("Piper", self.piper_label)
        root.addWidget(probe)

        routing = QGroupBox("Feature backends")
        self.routing_form = QFormLayout(routing)
        root.addWidget(routing)

        btns = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh probe")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_provision = QPushButton("Provision models on this PC")
        self.btn_provision.setObjectName("primary")
        self.btn_provision.clicked.connect(self.provision_local)
        self.btn_queue = QPushButton("Queue from studio API")
        self.btn_queue.clicked.connect(self.queue_remote)
        btns.addWidget(self.btn_refresh)
        btns.addWidget(self.btn_provision)
        btns.addWidget(self.btn_queue)
        root.addLayout(btns)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Provision log…")
        self.log.setMaximumHeight(180)
        root.addWidget(self.log)
        hint = QLabel(
            "Provision installs faster-whisper, warms the base model, and pulls "
            "llama3.1 / llava from Ollama when that daemon is running. Cloud keys "
            "are optional fallbacks — local backends do not need a paste-keys wizard."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        probe = models.full_probe()
        self._apply_probe(probe)
        api.get_async("/studio/models", on_ok=self._on_catalog, on_err=lambda m: self._append(m))
        api.post_async(
            "/companion/runtime",
            {**probe, "detail": probe.get("detail") or ""},
            on_ok=lambda _d: None,
            on_err=lambda _m: None,
        )

    def _apply_probe(self, probe: dict) -> None:
        self.gpu_label.setText((probe.get("gpu") or {}).get("detail") or "not detected")
        self.ollama_label.setText((probe.get("ollama") or {}).get("detail") or "not running")
        self.whisper_label.setText((probe.get("whisper") or {}).get("detail") or "not installed")
        self.piper_label.setText((probe.get("piper") or {}).get("detail") or "not on PATH")

    def _on_catalog(self, data: dict) -> None:
        self._map = dict((data or {}).get("map") or {})
        companion = (data or {}).get("companion") or {}
        if companion.get("gpu") or companion.get("whisper"):
            self._apply_probe(companion)
        # Rebuild combos
        while self.routing_form.rowCount():
            self.routing_form.removeRow(0)
        self._combos.clear()
        for feat in (data or {}).get("features") or []:
            combo = QComboBox()
            for b in feat.get("backends") or []:
                mark = "" if b.get("available") else " (needs provision)"
                combo.addItem(f"{b.get('label')}{mark}", b.get("id"))
            selected = feat.get("selected")
            for i in range(combo.count()):
                if combo.itemData(i) == selected:
                    combo.setCurrentIndex(i)
                    break
            combo.currentIndexChanged.connect(self._emit_map)
            self._combos[feat["id"]] = combo
            label = QLabel(feat.get("label") or feat["id"])
            label.setToolTip(feat.get("purpose") or "")
            self.routing_form.addRow(label, combo)

    def collect_map(self) -> dict:
        return {fid: combo.currentData() for fid, combo in self._combos.items()}

    def _emit_map(self, *_):
        payload = self.collect_map()
        self._map = payload
        self.map_changed.emit(payload)
        api.put_async("/studio/models", {"map": payload}, on_ok=lambda _d: None, on_err=lambda m: self._append(m))

    def provision_local(self) -> None:
        if self._job and self._job.isRunning():
            return
        self.btn_provision.setEnabled(False)
        self._append("Starting local provision…")
        wanted = [
            fid
            for fid, backend in self.collect_map().items()
            if backend in {"auto", "local_whisper", "local_piper", "ollama"}
        ] or ["stt", "tts", "twin", "vision"]
        self._job = _ProvisionJob(wanted, self)
        self._job.line.connect(self._append)
        self._job.done.connect(self._on_provision_done)
        self._job.start()

    def queue_remote(self) -> None:
        api.post_async(
            "/studio/models/provision",
            {"features": None},
            on_ok=lambda d: self._append(d.get("hint") or "queued"),
            on_err=lambda m: self._append(m),
        )

    def _on_provision_done(self, result: dict) -> None:
        self.btn_provision.setEnabled(True)
        for line in result.get("log") or []:
            self._append(line)
        if result.get("error"):
            self._append(result["error"])
        self._apply_probe(result)
        self.refresh()

    def _append(self, msg: str) -> None:
        if not msg:
            return
        self.log.appendPlainText(str(msg))
