"""Avatar panel — shows the user's twin.

Modes:
- "d_id"     : full talking-head MP4 played whenever the assistant speaks
- "waveform" : static portrait + animated waveform (cheap, no D-ID render cost)

The panel exposes:
- `speak(text)` — start a render and play when ready (mode-aware)
- `set_level(level)` — drive the waveform while user is recording / twin is talking
- `pop_out()` — detach the avatar to a borderless, transparent, always-on-top
  window so OBS can window-capture just the twin's face for streaming.

Pop-out mode keeps an `_BroadcastWindow` instance and mirrors playback into
it (the same QMediaPlayer drives a second QVideoWidget by reparenting).
"""
from __future__ import annotations

import math
import os
import tempfile
from typing import Optional

import requests
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import api, config
from . import PALETTE


class _Waveform(QWidget):
    """A simple amplitude-following ring that pulses at `set_level`."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._level = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self.setAutoFillBackground(False)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def _tick(self) -> None:
        # Decay so it returns to idle when not driven
        self._level *= 0.92
        self._phase = (self._phase + 0.08) % (2 * math.pi)
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        cx = rect.center().x()
        cy = rect.center().y()
        max_r = min(rect.width(), rect.height()) * 0.42
        accent = QColor(PALETTE["accent"])
        # 3 concentric rings, each modulated by phase + level
        for i in range(3):
            radius = max_r * (0.55 + 0.15 * i + 0.18 * self._level * math.sin(self._phase + i))
            alpha = int(180 - i * 50)
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), alpha))
            pen.setWidthF(1.5)
            p.setPen(pen)
            p.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))
        p.end()


class _PortraitVideo(QStackedWidget):
    """Either the user's portrait JPG, or a QVideoWidget playing D-ID output."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._portrait_url: Optional[str] = None

        self._portrait = QLabel()
        self._portrait.setAlignment(Qt.AlignCenter)
        self._portrait.setStyleSheet(
            f"background: {PALETTE['bg_elevated']}; border-radius: 4px;"
        )
        self.addWidget(self._portrait)

        self._video = QVideoWidget()
        self._video.setStyleSheet(f"background: {PALETTE['bg_base']};")
        self.addWidget(self._video)

        self.setCurrentIndex(0)

    def set_portrait_url(self, url: Optional[str]) -> None:
        if not url or url == self._portrait_url:
            return
        self._portrait_url = url
        # Fetch in a thread, set when done
        def _fetch():
            try:
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                return r.content
            except Exception:
                return b""
        api._submit(_fetch, self._on_portrait, None)  # type: ignore[attr-defined]

    def _on_portrait(self, data: bytes) -> None:
        if not data:
            return
        pm = QPixmap()
        if pm.loadFromData(data):
            scaled = pm.scaled(
                self.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self._portrait.setPixmap(scaled)
            self._portrait._raw = pm  # keep for re-scale on resize

    def show_portrait(self) -> None:
        self.setCurrentIndex(0)

    def show_video(self) -> QVideoWidget:
        self.setCurrentIndex(1)
        return self._video

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        raw = getattr(self._portrait, "_raw", None)
        if raw is not None:
            self._portrait.setPixmap(
                raw.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )


class _BroadcastWindow(QWidget):
    """Frameless, transparent-background window used for OBS window-capture.

    OBS picks this up by name ("Heirloom Twin — Broadcast"). We keep an
    internal QVideoWidget that we play the same MP4 into for parity with
    the main panel.
    """

    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Heirloom Twin — Broadcast")
        # Frameless + transparent so OBS captures only the face
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(420, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.portrait = QLabel(self)
        self.portrait.setAlignment(Qt.AlignCenter)
        self.portrait.setStyleSheet("background: transparent;")
        self.video = QVideoWidget(self)
        self.video.setStyleSheet("background: transparent;")
        self.video.hide()
        layout.addWidget(self.portrait)
        layout.addWidget(self.video)

        # Drag-to-move
        self._drag_pos = None

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            ev.accept()

    def mouseMoveEvent(self, ev):  # noqa: N802
        if self._drag_pos and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)
            ev.accept()

    def closeEvent(self, ev):  # noqa: N802
        self.closed.emit()
        super().closeEvent(ev)


class AvatarPanel(QFrame):
    """Center-stage avatar with controls."""

    status_changed = Signal(str)  # "idle" | "thinking" | "speaking"

    def __init__(self, settings: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("avatar_panel")
        self._settings = settings
        self._broadcast: Optional[_BroadcastWindow] = None
        self._tmp_video: Optional[str] = None

        # Media
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_media_error)

        # Layout
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Your twin")
        title.setProperty("class", "overline")
        title.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 2px; font-size: 10px;"
        )
        header.addWidget(title)
        header.addStretch(1)

        self.btn_mode = QPushButton("Avatar: D-ID")
        self.btn_mode.setObjectName("ghost")
        self.btn_mode.clicked.connect(self._toggle_mode)
        header.addWidget(self.btn_mode)

        self.btn_popout = QPushButton("Pop out for OBS ↗")
        self.btn_popout.setObjectName("ghost")
        self.btn_popout.clicked.connect(self.pop_out)
        header.addWidget(self.btn_popout)
        root.addLayout(header)

        # Stage
        self.portrait_video = _PortraitVideo(self)
        root.addWidget(self.portrait_video, 1)

        self.waveform = _Waveform(self)
        self.waveform.hide()
        root.addWidget(self.waveform)

        self.status_label = QLabel("idle")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 2px; font-size: 10px;"
        )
        root.addWidget(self.status_label)

        self._apply_mode()

    # ---- public ----
    def set_portrait_url(self, url: Optional[str]) -> None:
        self.portrait_video.set_portrait_url(url)
        if self._broadcast is not None:
            self.portrait_video.set_portrait_url(url)

    def set_level(self, level: float) -> None:
        self.waveform.set_level(level)

    def set_status(self, status: str) -> None:
        labels = {
            "idle": "idle",
            "thinking": "thinking…",
            "speaking": "speaking",
            "listening": "listening…",
            "rendering": "rendering twin…",
        }
        self.status_label.setText(labels.get(status, status))
        self.status_changed.emit(status)

    def speak(self, text: str) -> None:
        """Render the assistant `text` as the twin's voice + face, then play."""
        text = (text or "").strip()
        if not text:
            self.set_status("idle")
            return
        if self._settings.get("avatar_mode") == "waveform":
            # No D-ID — just emote with the waveform ring for ~2s
            self.set_status("speaking")
            QTimer.singleShot(1800, lambda: self.set_status("idle"))
            return
        self.set_status("rendering")
        api.post_async(
            "/desktop/avatar/talk",
            {"text": text[:1000]},
            on_ok=self._on_talk_started,
            on_err=lambda msg: self.set_status("idle"),
        )

    def pop_out(self) -> None:
        if self._broadcast is not None and self._broadcast.isVisible():
            self._broadcast.raise_()
            return
        if self._broadcast is None:
            self._broadcast = _BroadcastWindow(self)
            self._broadcast.closed.connect(self._on_broadcast_closed)
        # Geometry recall
        geo = self._settings.get("pop_out_geometry")
        if isinstance(geo, list) and len(geo) == 4:
            self._broadcast.setGeometry(*geo)
        # Mirror current portrait
        raw = getattr(self.portrait_video._portrait, "_raw", None)
        if raw is not None:
            self._broadcast.portrait.setPixmap(
                raw.scaled(
                    self._broadcast.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        self._broadcast.show()

    # ---- internal ----
    def _toggle_mode(self) -> None:
        new = "waveform" if self._settings.get("avatar_mode") == "d_id" else "d_id"
        self._settings["avatar_mode"] = new
        config.save_settings(self._settings)
        self._apply_mode()

    def _apply_mode(self) -> None:
        mode = self._settings.get("avatar_mode", "d_id")
        if mode == "waveform":
            self.btn_mode.setText("Avatar: Waveform")
            self.waveform.show()
        else:
            self.btn_mode.setText("Avatar: D-ID")
            self.waveform.hide()

    def _on_talk_started(self, data: dict) -> None:
        talk_id = (data or {}).get("talk_id")
        if not talk_id:
            self.set_status("idle")
            return
        self._poll_talk(talk_id, attempts=0)

    def _poll_talk(self, talk_id: str, attempts: int) -> None:
        if attempts > 40:  # ~40 * 1500ms = 60s budget
            self.set_status("idle")
            return
        api.get_async(
            f"/desktop/avatar/talk/{talk_id}",
            on_ok=lambda d: self._on_talk_poll(talk_id, d, attempts),
            on_err=lambda _msg: QTimer.singleShot(
                1500, lambda: self._poll_talk(talk_id, attempts + 1)
            ),
        )

    def _on_talk_poll(self, talk_id: str, data: dict, attempts: int) -> None:
        status = (data or {}).get("status", "")
        url = (data or {}).get("result_url")
        if status == "done" and url:
            self._play_result(url)
        elif status in ("error", "rejected"):
            self.set_status("idle")
        else:
            QTimer.singleShot(1500, lambda: self._poll_talk(talk_id, attempts + 1))

    def _play_result(self, url: str) -> None:
        self.set_status("speaking")
        # Download to a tmp file so QMediaPlayer doesn't have to stream over
        # a redirect-laden CDN — QMediaPlayer can be picky on Windows.
        def _fetch():
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                f = tempfile.NamedTemporaryFile(
                    suffix=".mp4", delete=False, prefix="heirloom_"
                )
                f.write(r.content)
                f.flush()
                f.close()
                return f.name
            except Exception as exc:
                raise RuntimeError(f"download: {exc}") from exc

        api._submit(_fetch, self._on_video_ready, lambda _m: self.set_status("idle"))  # type: ignore[attr-defined]

    def _on_video_ready(self, path: str) -> None:
        # Clean up the previous tmp
        if self._tmp_video and os.path.exists(self._tmp_video):
            try:
                os.unlink(self._tmp_video)
            except Exception:
                pass
        self._tmp_video = path
        video = self.portrait_video.show_video()
        self.player.setVideoOutput(video)
        # Mirror into broadcast window if visible
        if self._broadcast is not None and self._broadcast.isVisible():
            # Qt only supports one video sink per player — swap on every pop
            self.player.setVideoOutput(self._broadcast.video)
            self._broadcast.video.show()
            self._broadcast.portrait.hide()
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.EndOfMedia:
            self.set_status("idle")
            self.portrait_video.show_portrait()
            if self._broadcast is not None and self._broadcast.isVisible():
                self._broadcast.video.hide()
                self._broadcast.portrait.show()

    def _on_media_error(self, _err, _msg: str = "") -> None:
        self.set_status("idle")
        self.portrait_video.show_portrait()

    def _on_broadcast_closed(self) -> None:
        if self._broadcast is not None:
            self._settings["pop_out_geometry"] = [
                self._broadcast.x(),
                self._broadcast.y(),
                self._broadcast.width(),
                self._broadcast.height(),
            ]
            config.save_settings(self._settings)
