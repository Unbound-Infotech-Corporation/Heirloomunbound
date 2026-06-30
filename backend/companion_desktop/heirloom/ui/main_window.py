"""Main window — orchestrates avatar / conversation / sidebar / quick-capture.

Layout (3-pane QSplitter, all resizable):
   ┌─────────────────────────────────────────────────────────────────┐
   │ Titlebar: Heirloom logo · status · push-to-talk · settings · _x │
   ├──────────┬─────────────────────────────────────────┬────────────┤
   │ Memories │ Avatar panel (top)                       │  Quick    │
   │ sidebar  │ ─────────────────────────────            │  capture  │
   │          │ Conversation (bottom)                   │           │
   └──────────┴─────────────────────────────────────────┴────────────┘
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, api, audio, config
from ..maintenance import Maintenance
from ..vault import Vault
from . import PALETTE, QSS
from .avatar_panel import AvatarPanel
from .conversation import ConversationPanel
from .panels import QuickCapture, RecentMemories
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    quit_requested = Signal()

    def __init__(self):
        super().__init__()
        self._settings = config.load_settings()
        self._user: dict = {}

        self.setWindowTitle("Heirloom · your digital twin")
        self.resize(1280, 800)
        self.setMinimumSize(960, 620)
        self.setStyleSheet(QSS)

        self._build_ui()
        self._wire_signals()
        self._load_initial_data()
        self._restore_geometry()

    # ----- UI -----
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- titlebar ----
        title = QWidget()
        title.setObjectName("titlebar")
        title.setFixedHeight(54)
        title_layout = QHBoxLayout(title)
        title_layout.setContentsMargins(18, 0, 18, 0)
        brand_block = QVBoxLayout()
        overline = QLabel("HEIRLOOM · UNBOUND INFOTECH")
        overline.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 2px; font-size: 9px;"
        )
        self.user_label = QLabel("Loading…")
        self.user_label.setStyleSheet(
            f"color: {PALETTE['text_primary']};"
            " font-family: 'Cormorant Garamond', serif; font-size: 18px;"
        )
        brand_block.setSpacing(0)
        brand_block.addWidget(overline)
        brand_block.addWidget(self.user_label)
        title_layout.addLayout(brand_block)
        title_layout.addStretch(1)

        self.status_pill = QLabel("idle")
        self.status_pill.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 2px; font-size: 10px;"
            " padding: 4px 10px;"
            f" border: 1px solid {PALETTE['border']}; border-radius: 12px;"
        )
        title_layout.addWidget(self.status_pill)

        self.ptt_btn = QPushButton("Hold to talk  (Ctrl+Space)")
        self.ptt_btn.setObjectName("primary")
        self.ptt_btn.setMinimumWidth(220)
        self.ptt_btn.pressed.connect(self._ptt_start)
        self.ptt_btn.released.connect(self._ptt_stop)
        title_layout.addWidget(self.ptt_btn)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("ghost")
        self.settings_btn.setFixedWidth(36)
        self.settings_btn.setToolTip("Vault, storage tier, maintenance")
        self.settings_btn.clicked.connect(self._open_settings)
        title_layout.addWidget(self.settings_btn)

        layout.addWidget(title)

        # ---- 3-pane splitter ----
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        # left: memories sidebar
        self.memories = RecentMemories()
        self.memories.setMinimumWidth(220)
        splitter.addWidget(self.memories)

        # center: avatar over conversation (vertical splitter)
        center_split = QSplitter(Qt.Vertical)
        center_split.setHandleWidth(1)
        center_split.setChildrenCollapsible(False)
        self.avatar = AvatarPanel(self._settings)
        self.conversation = ConversationPanel(self._settings)
        center_split.addWidget(self.avatar)
        center_split.addWidget(self.conversation)
        center_split.setSizes([320, 460])
        splitter.addWidget(center_split)

        # right: quick capture
        self.quickcap = QuickCapture()
        self.quickcap.setMinimumWidth(260)
        splitter.addWidget(self.quickcap)

        splitter.setSizes([260, 760, 280])
        layout.addWidget(splitter, 1)

        # Audio recorder
        self.recorder = audio.Recorder(self)
        # Local vault — lazy init so a busted folder doesn't crash startup
        try:
            self._vault: Vault | None = Vault()
        except Exception as exc:  # noqa: BLE001
            print(f"[vault] init failed: {exc}")
            self._vault = None
        # Active conversation id for vault grouping (filled by /me load)
        self._active_conv_id = "comp_local"

    def _wire_signals(self) -> None:
        # Quick-cap refresh sidebar
        self.quickcap.saved.connect(lambda _d: self.memories.refresh())
        # Twin reply triggers avatar speak
        self.conversation.reply_received.connect(self._on_twin_reply)
        # Vault capture — every text turn (user + assistant)
        self.conversation.message_sent.connect(lambda t: self._vault_capture("user", t, "chat"))
        self.conversation.reply_received.connect(lambda t: self._vault_capture("assistant", t, "chat"))
        # Avatar status → pill
        self.avatar.status_changed.connect(self._update_status_pill)
        # Recorder
        self.recorder.level.connect(self.avatar.set_level)
        self.recorder.wav_bytes.connect(self._upload_voice)
        self.recorder.error.connect(lambda msg: self._update_status_pill(f"mic: {msg}"))
        # Hotkey
        sc = QShortcut(QKeySequence("Ctrl+Space"), self)
        sc.setContext(Qt.ApplicationShortcut)
        sc.activated.connect(self._ptt_toggle)

    def _restore_geometry(self) -> None:
        geo = self._settings.get("window_geometry")
        if isinstance(geo, list) and len(geo) == 4:
            self.setGeometry(*geo)

    def closeEvent(self, ev):  # noqa: N802
        # Persist geometry, then hide-to-tray instead of quitting
        self._settings["window_geometry"] = [
            self.x(),
            self.y(),
            self.width(),
            self.height(),
        ]
        config.save_settings(self._settings)
        ev.ignore()
        self.hide()

    def shutdown(self) -> None:
        """Called by app.aboutToQuit — runs final maintenance if scheduled."""
        sched = (self._settings.get("maintenance_schedule") or "on_quit").lower()
        if sched != "on_quit":
            return
        if self._vault is None:
            return
        # Fire-and-forget: we have ~10s before the OS kills us. Run synchronously
        # on a background thread but cap the wait.
        try:
            self._update_status_pill("end-of-day compaction…")
            m = Maintenance()
            m.run_async()
        except Exception as exc:  # noqa: BLE001
            print(f"[shutdown] maintenance failed: {exc}")

    # ----- data load -----
    def _load_initial_data(self) -> None:
        api.get_async("/desktop/me", on_ok=self._on_me, on_err=self._on_me_err)
        self.conversation.load_history()
        self.memories.refresh()

    def _on_me(self, data: dict) -> None:
        self._user = data or {}
        name = data.get("name") or data.get("email") or "Your archive"
        self.user_label.setText(f"{name}'s twin")
        self.avatar.set_portrait_url(data.get("avatar_source_url"))
        # Pull the shared companion_twin conv_id so vault rows group correctly
        api.get_async(
            "/desktop/conversation?limit=1",
            on_ok=lambda d: setattr(self, "_active_conv_id", (d or {}).get("conversation_id") or "comp_local"),
            on_err=lambda _m: None,
        )

    def _on_me_err(self, msg: str) -> None:
        self.user_label.setText("Sign in required")
        self.status_pill.setText("not authed")

    # ----- twin → avatar -----
    def _on_twin_reply(self, text: str) -> None:
        self.avatar.speak(text)

    def _update_status_pill(self, status: str) -> None:
        self.status_pill.setText(status)

    # ----- push-to-talk -----
    def _ptt_toggle(self) -> None:
        if self.recorder.is_recording():
            self._ptt_stop()
        else:
            self._ptt_start()

    def _ptt_start(self) -> None:
        if self.recorder.is_recording():
            return
        self._update_status_pill("listening…")
        self.recorder.start()

    def _ptt_stop(self) -> None:
        if not self.recorder.is_recording():
            return
        self._update_status_pill("thinking…")
        self.recorder.stop()

    def _upload_voice(self, wav: bytes) -> None:
        if not wav:
            self._update_status_pill("idle")
            return
        self._pending_voice_audio = wav  # stashed for vault capture after reply
        files = {"audio": ("ptt.wav", wav, "audio/wav")}
        api.post_multipart_async(
            "/companion/voice",
            files=files,
            data={"save_to_archive": "false"},
            on_ok=self._on_voice_reply,
            on_err=lambda msg: self._update_status_pill(f"voice err: {msg[:40]}"),
        )

    def _on_voice_reply(self, data: dict) -> None:
        user_text = (data or {}).get("user_text", "")
        reply = (data or {}).get("reply", "")
        wav = getattr(self, "_pending_voice_audio", None)
        self._pending_voice_audio = None
        if user_text:
            self.conversation.append("user", user_text)
            # Capture voice turn WITH audio bytes so Full tier keeps the recording
            self._vault_capture("user", user_text, "voice", audio_bytes=wav)
        if reply:
            self.conversation.append("assistant", reply)
            self._vault_capture("assistant", reply, "voice")
            self.avatar.speak(reply)
        self.memories.refresh()

    # ----- vault -----
    def _vault_capture(
        self,
        role: str,
        text: str,
        kind: str = "chat",
        audio_bytes: bytes | None = None,
    ) -> None:
        if self._vault is None or not text:
            return
        try:
            self._vault.append_turn(
                self._active_conv_id, role, text, kind=kind, audio_bytes=audio_bytes
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[vault] append failed: {exc}")

    # ----- settings dialog -----
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        dlg.exec()


class TrayProxy:
    """Wraps QSystemTrayIcon so MainWindow can show/hide via tray actions."""

    def __init__(self, window: MainWindow):
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        self.window = window
        icon = window.style().standardIcon
        from PySide6.QtWidgets import QStyle

        self.tray = QSystemTrayIcon(window)
        self.tray.setIcon(icon(QStyle.SP_ComputerIcon))
        self.tray.setToolTip("Heirloom — your digital twin")

        menu = QMenu()
        show = QAction("Open Heirloom", menu)
        show.triggered.connect(self._show)
        ptt = QAction("Push-to-talk", menu)
        ptt.triggered.connect(window._ptt_toggle)
        popout = QAction("Pop out avatar for OBS", menu)
        popout.triggered.connect(window.avatar.pop_out)
        quit_act = QAction("Quit Heirloom", menu)
        quit_act.triggered.connect(window.quit_requested.emit)
        menu.addAction(show)
        menu.addSeparator()
        menu.addAction(ptt)
        menu.addAction(popout)
        menu.addSeparator()
        menu.addAction(quit_act)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    def _show(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _on_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason == QSystemTrayIcon.Trigger:
            if self.window.isVisible():
                self.window.hide()
            else:
                self._show()
