"""Heirloom Unbound Voice window — local clone engines, no Pinokio."""
from __future__ import annotations

import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from heirloom import api, models
from heirloom.local_tts import speak_test
from heirloom.models import coach_install_lines, engine_urls
from heirloom.studio_log import info as log_info

from . import PALETTE


class _SpeakJob(QThread):
    done = Signal(dict)

    def __init__(self, text: str, model_map: dict, probe: dict, has_clone: bool, parent=None):
        super().__init__(parent)
        self.text = text
        self.model_map = model_map
        self.probe = probe
        self.has_clone = has_clone

    def run(self) -> None:  # pragma: no cover
        self.done.emit(
            speak_test(self.text, model_map=self.model_map, probe=self.probe, has_voice_clone=self.has_clone)
        )


class VoiceCoachDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Local voice engines — Heirloom Unbound")
        self.setModal(True)
        self.resize(480, 360)
        self.setStyleSheet("QDialog { background: #1C1A18; color: #F2EFE9; border: 1px solid #36322E; }")
        lay = QVBoxLayout(self)
        title = QLabel("Install, then Probe")
        title.setStyleSheet("font-family: 'Cormorant Garamond', serif; font-size: 24px;")
        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText("\n".join(coach_install_lines()))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(title)
        lay.addWidget(body, 1)
        lay.addWidget(close)


class VoicePanel(QWidget):
    map_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._probe: dict = {}
        self._map: dict = {}
        self._has_clone = False
        self._job: _SpeakJob | None = None
        self._chips: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        over = QLabel("HEIRLOOM UNBOUND · VOICE")
        over.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 2px;"
        )
        title = QLabel("Local clone engines")
        title.setStyleSheet(
            f"font-family: 'Cormorant Garamond', serif; font-size: 22px; color: {PALETTE['text_primary']};"
        )
        root.addWidget(over)
        root.addWidget(title)

        chips = QHBoxLayout()
        for key, label in (
            ("voicebox", "Voicebox"),
            ("qwen3_tts", "Qwen3-TTS"),
            ("elevenlabs", "ElevenLabs"),
            ("piper", "Piper"),
        ):
            chip = QLabel(label)
            chip.setObjectName("statuschip")
            chip.setAlignment(Qt.AlignCenter)
            chip.setMinimumHeight(28)
            chip.setMinimumWidth(110)
            self._chips[key] = chip
            chips.addWidget(chip)
        chips.addStretch(1)
        root.addLayout(chips)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        for label, slot in (
            ("Probe", self.probe_now),
            ("Detect engines", self.probe_now),
            ("Test phrase", self.test_phrase),
            ("Prefer Voicebox", lambda: self.prefer("voicebox")),
            ("Prefer Qwen3", lambda: self.prefer("qwen3_tts")),
            ("Open docs / coach", self.open_coach),
            ("Open Voicebox", self.open_voicebox),
        ):
            btn = QPushButton(label)
            btn.setObjectName("toolbar")
            btn.setMinimumHeight(38)
            btn.clicked.connect(slot)
            tools.addWidget(btn)
        tools.addStretch(1)
        root.addLayout(tools)

        self.status = QLabel("Probe to see which local engines are listening.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        self.log.setPlaceholderText("Voice path…")
        root.addWidget(self.log)
        hint = QLabel(
            "Voicebox and Qwen3-TTS install standalone (MSI, Docker, or pip). "
            "Heirloom Unbound never downloads those installers. Auto prefers Voicebox when it is listening."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {PALETTE['text_muted']};")
        root.addWidget(hint)
        root.addStretch(1)
        self.probe_now()

    def apply_remote_map(self, model_map: dict) -> None:
        if isinstance(model_map, dict):
            self._map = dict(model_map)

    def set_voice_clone(self, configured: bool) -> None:
        self._has_clone = bool(configured)
        self._paint_chips()

    def _append(self, msg: str) -> None:
        if msg:
            self.log.appendPlainText(msg)

    def _paint_chips(self) -> None:
        states = {
            "voicebox": bool((self._probe.get("voicebox") or {}).get("ready")),
            "qwen3_tts": bool((self._probe.get("qwen3_tts") or {}).get("ready")),
            "elevenlabs": self._has_clone,
            "piper": bool((self._probe.get("piper") or {}).get("ready")),
        }
        for key, ready in states.items():
            chip = self._chips[key]
            chip.setProperty("ready", "true" if ready else "false")
            chip.style().unpolish(chip)
            chip.style().polish(chip)
            chip.setText(f"{chip.text().split(' · ')[0]} · {'ready' if ready else 'down'}")

    def probe_now(self) -> None:
        probe = models.full_probe()
        self._probe = probe
        self._paint_chips()
        resolved = models.resolve_tts_backend_local(self._map, probe, has_voice_clone=self._has_clone)
        self.status.setText(f"{probe.get('detail') or 'probed'} · Auto would use {resolved}")
        self._append(f"probe · resolved tts={resolved}")
        log_info("router", f"voice window resolved tts={resolved}", pick=self._map.get("tts", "auto"))
        api.post_async("/companion/runtime", {**probe, "detail": probe.get("detail") or ""}, on_ok=lambda _d: None, on_err=lambda _m: None)

    def prefer(self, backend: str) -> None:
        payload = {**self._map, "tts": backend}
        self._map = payload
        self.map_changed.emit(payload)
        api.put_async("/studio/models", {"map": payload}, on_ok=lambda _d: None, on_err=lambda m: self._append(m))
        log_info("ui", f"prefer tts={backend}")
        self._append(f"prefer {backend}")
        self.probe_now()

    def test_phrase(self) -> None:
        if self._job and self._job.isRunning():
            return
        self._append("test phrase…")
        self._job = _SpeakJob(
            "Heirloom Unbound is listening on this PC.",
            self._map,
            self._probe or models.full_probe(),
            self._has_clone,
            self,
        )
        self._job.done.connect(self._on_speak)
        self._job.start()

    def _on_speak(self, result: dict) -> None:
        line = f"test · {result.get('backend')} · {result.get('ms')}ms · {result.get('detail')}"
        self._append(line)
        self.status.setText(line)

    def open_coach(self) -> None:
        VoiceCoachDialog(self).exec()

    def open_voicebox(self) -> None:
        url = engine_urls()["voicebox_url"]
        ready = bool((self._probe.get("voicebox") or {}).get("ready"))
        if ready:
            webbrowser.open(url)
            log_info("ui", f"opened Voicebox {url}")
        else:
            self._append(f"Voicebox not listening at {url}. Install the MSI/Docker, start it, then Probe.")
            log_info("tts", f"open Voicebox skipped — not ready at {url}")
