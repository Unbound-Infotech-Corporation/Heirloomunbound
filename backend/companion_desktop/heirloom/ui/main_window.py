"""Main window — orchestrates avatar / conversation / sidebar / quick-capture.

Elite mode:
- Frameless native window on Windows 11 with Mica backdrop tint
- Custom titlebar (drag / double-click max / traffic lights)
- Command Palette (Ctrl+K) with dynamic "speak"/"capture" rows
- Ambient aura behind avatar tied to speaking state
- Micro-motion on message reveal, breathing status dot
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, api, audio, config
from ..commands import CommandPoller
from ..maintenance import Maintenance
from ..vault import Vault
from . import PALETTE, QSS
from .avatar_panel import AvatarPanel
from .command_palette import Command, CommandPalette
from .conversation import ConversationPanel
from .mica import apply as apply_mica
from .panels import QuickCapture, RecentMemories
from .settings_dialog import SettingsDialog
from .talk_window import MiniTalkWindow
from .writing_window import WritingWindow
from .titlebar import TitleBar


class MainWindow(QMainWindow):
    quit_requested = Signal()

    def __init__(self):
        super().__init__()
        self._settings = config.load_settings()
        self._user: dict = {}
        self._palette: Optional[CommandPalette] = None
        self._mica_applied = False
        self._talk: Optional[MiniTalkWindow] = None
        self._writing: Optional[WritingWindow] = None

        self.setWindowTitle("Heirloom")
        self.resize(1280, 800)
        self.setMinimumSize(960, 620)

        # Frameless + translucent so Mica shows through the empty regions
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(QSS)

        self._build_ui()
        self._wire_signals()
        self._load_initial_data()
        self._restore_geometry()

    # ----- UI -----
    def _build_ui(self) -> None:
        # Root is transparent — the "card" below is the visible surface
        root = QWidget()
        root.setObjectName("root")
        root.setAttribute(Qt.WA_StyledBackground, True)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        # Small margin gives Mica a visible bezel around the card
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        card = QWidget()
        card.setObjectName("card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        outer.addWidget(card, 1)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ---- custom titlebar ----
        self.titlebar = TitleBar(
            self,
            on_minimize=self.showMinimized,
            on_maximize=self._toggle_max,
            on_close=self.close,
        )
        self.titlebar.ptt_pressed.connect(self._ptt_start)
        self.titlebar.ptt_released.connect(self._ptt_stop)
        self.titlebar.settings_clicked.connect(self._open_settings)
        self.titlebar.palette_clicked.connect(self._open_palette)
        card_layout.addWidget(self.titlebar)

        # ---- 3-pane splitter ----
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        # left: memories sidebar
        self.memories = RecentMemories()
        self.memories.setMinimumWidth(220)
        splitter.addWidget(self.memories)

        # center: avatar over conversation
        center_split = QSplitter(Qt.Vertical)
        center_split.setHandleWidth(1)
        center_split.setChildrenCollapsible(False)
        self.avatar = AvatarPanel(self._settings)
        self.conversation = ConversationPanel(self._settings)
        center_split.addWidget(self.avatar)
        center_split.addWidget(self.conversation)
        center_split.setSizes([360, 440])
        splitter.addWidget(center_split)

        # right: quick capture
        self.quickcap = QuickCapture()
        self.quickcap.setMinimumWidth(260)
        splitter.addWidget(self.quickcap)

        splitter.setSizes([260, 760, 280])
        card_layout.addWidget(splitter, 1)

        # ---- resize grip strip at the bottom-right ----
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch(1)
        grip = QSizeGrip(self)
        grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(grip, 0, Qt.AlignRight | Qt.AlignBottom)
        card_layout.addLayout(grip_row)

        # Audio recorder
        self.recorder = audio.Recorder(self)
        # Local vault — lazy init so a busted folder doesn't crash startup
        try:
            self._vault: Vault | None = Vault()
        except Exception as exc:  # noqa: BLE001
            print(f"[vault] init failed: {exc}")
            self._vault = None
        self._active_conv_id = "comp_local"

    def _wire_signals(self) -> None:
        # Quick-cap refresh sidebar
        self.quickcap.saved.connect(lambda _d: self.memories.refresh())
        # Twin reply triggers avatar speak
        self.conversation.reply_received.connect(self._on_twin_reply)
        self.conversation.messages_changed.connect(self._sync_mini_talk)
        # Vault capture — every text turn (user + assistant)
        self.conversation.message_sent.connect(lambda t: self._vault_capture("user", t, "chat"))
        self.conversation.reply_received.connect(lambda t: self._vault_capture("assistant", t, "chat"))
        # Avatar status → titlebar pill + aura
        self.avatar.status_changed.connect(self._update_status)
        self.avatar.talk_requested.connect(self.open_mini_talk)
        # Recorder
        self.recorder.level.connect(self.avatar.set_level)
        self.recorder.wav_bytes.connect(self._upload_voice)
        self.recorder.error.connect(lambda msg: self._update_status(f"mic: {msg}"))

        # Global shortcuts
        for seq in ("Ctrl+K", "Ctrl+P"):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._open_palette)
        sc_ptt = QShortcut(QKeySequence("Ctrl+Space"), self)
        sc_ptt.setContext(Qt.ApplicationShortcut)
        sc_ptt.activated.connect(self._ptt_toggle)
        sc_write = QShortcut(QKeySequence("Ctrl+Shift+U"), self)
        sc_write.setContext(Qt.ApplicationShortcut)
        sc_write.activated.connect(self.open_writing_helper)

    def _restore_geometry(self) -> None:
        geo = self._settings.get("window_geometry")
        if isinstance(geo, list) and len(geo) == 4:
            self.setGeometry(*geo)

    # ----- native events -----
    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        # Enable Mica once — must happen after the HWND exists
        if not self._mica_applied:
            self._mica_applied = True
            result = apply_mica(self)
            if result:
                print(f"[mica] enabled ({result})")

    def changeEvent(self, ev):  # noqa: N802
        from PySide6.QtCore import QEvent

        if ev.type() == QEvent.WindowStateChange:
            self.titlebar.set_maximized(self.isMaximized())
        super().changeEvent(ev)

    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

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
        try:
            if getattr(self, "_cmd_poller", None) is not None:
                self._cmd_poller.stop()
                self._cmd_poller.wait(2000)
        except Exception:  # noqa: BLE001
            pass
        sched = (self._settings.get("maintenance_schedule") or "on_quit").lower()
        if sched != "on_quit":
            return
        if self._vault is None:
            return
        try:
            self._update_status("end-of-day compaction…")
            m = Maintenance()
            m.run_async()
        except Exception as exc:  # noqa: BLE001
            print(f"[shutdown] maintenance failed: {exc}")

    # ----- data load -----
    def _load_initial_data(self) -> None:
        api.get_async("/desktop/me", on_ok=self._on_me, on_err=self._on_me_err)
        self.conversation.load_history()
        self.memories.refresh()
        # Start listening for OS commands the Twin queues (open apps, volume,
        # screen vision, etc.). Runs in its own thread; UI never blocks.
        self._cmd_poller = CommandPoller(self)
        self._cmd_poller.ran.connect(lambda label: self._update_status(f"twin: {label}"))
        self._cmd_poller.start()

    def _on_me(self, data: dict) -> None:
        self._user = data or {}
        name = data.get("name") or data.get("email") or "your archive"
        self.titlebar.set_user_name(f"{name}'s twin")
        self.avatar.set_portrait_url(data.get("avatar_source_url"))
        api.get_async(
            "/desktop/conversation?limit=1",
            on_ok=lambda d: setattr(self, "_active_conv_id", (d or {}).get("conversation_id") or "comp_local"),
            on_err=lambda _m: None,
        )

    def _on_me_err(self, msg: str) -> None:
        self.titlebar.set_user_name("this copy isn’t signed in")
        self._update_status("download Heirloom again from your account")
        QMessageBox.warning(
            self,
            "Heirloom",
            "This copy isn’t signed in. Open Local PC in your account and tap Download again.",
        )

    # ----- twin → avatar -----
    def _on_twin_reply(self, text: str) -> None:
        self.avatar.speak(text)

    def _update_status(self, status: str) -> None:
        self.titlebar.set_status(status)
        self.avatar.set_aura_state(status)

    # ----- push-to-talk -----
    def _ptt_toggle(self) -> None:
        if self.recorder.is_recording():
            self._ptt_stop()
        else:
            self._ptt_start()

    def _ptt_start(self) -> None:
        if self.recorder.is_recording():
            return
        self._update_status("listening…")
        self.recorder.start()

    def _ptt_stop(self) -> None:
        if not self.recorder.is_recording():
            return
        self._update_status("thinking…")
        self.recorder.stop()

    def _upload_voice(self, wav: bytes) -> None:
        if not wav:
            self._update_status("idle")
            return
        self._pending_voice_audio = wav
        files = {"audio": ("ptt.wav", wav, "audio/wav")}
        api.post_multipart_async(
            "/companion/voice",
            files=files,
            data={"save_to_archive": "false"},
            on_ok=self._on_voice_reply,
            on_err=lambda msg: self._update_status(f"voice err: {msg[:40]}"),
        )

    def _on_voice_reply(self, data: dict) -> None:
        user_text = (data or {}).get("user_text", "")
        reply = (data or {}).get("reply", "")
        wav = getattr(self, "_pending_voice_audio", None)
        self._pending_voice_audio = None
        if user_text:
            self.conversation.append("user", user_text)
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

    # ----- command palette -----
    def _open_palette(self) -> None:
        if self._palette is not None and self._palette.isVisible():
            self._palette.raise_()
            return
        cmds = self._build_commands()
        self._palette = CommandPalette(self, cmds)
        self._palette.show()

    def _build_commands(self):
        # Dynamic rows (consume the palette query)
        def speak_query(q: str):
            if not q:
                return
            self.conversation.send_text(q)

        def capture_query(q: str):
            if not q:
                return
            api.post_async(
                "/desktop/capture",
                {"title": None, "content": q, "type": "note", "tags": []},
                on_ok=lambda _d: self.memories.refresh(),
                on_err=lambda m: self._update_status(f"save err: {m[:40]}"),
            )

        # Static commands
        return [
            Command(
                id="speak",
                label="Speak to twin",
                hint="Send the current text as a message to your twin",
                dynamic=True,
                action=speak_query,
            ),
            Command(
                id="capture",
                label="Capture",
                hint="Save the current text as a quick note",
                dynamic=True,
                action=capture_query,
            ),
            Command(
                id="ptt",
                label="Push-to-talk",
                hint="Start listening from your microphone",
                shortcut="ctrl · space",
                action=self._ptt_toggle,
            ),
            Command(
                id="minitalk",
                label="Talk in a small window",
                hint="Just you and your twin — hide the big window",
                action=self.open_mini_talk,
            ),
            Command(
                id="unboundkb",
                label="Unbound Keyboard",
                hint="Fix spelling and overused words — not a spy on every key",
                shortcut="ctrl · shift · U",
                action=self.open_writing_helper,
            ),
            Command(
                id="lookscreen",
                label="Look at my screen",
                hint="The twin looks at this computer and helps — games, writing, movies",
                action=lambda: self.conversation.send_text(
                    "Look at my screen and help me with whatever is on it."
                ),
            ),
            Command(
                id="popout",
                label="Pop out avatar for OBS",
                hint="Detach the twin as a transparent always-on-top window",
                action=self.avatar.pop_out,
            ),
            Command(
                id="mode",
                label="Toggle avatar mode",
                hint="Switch between talking-head video and waveform",
                action=self.avatar._toggle_mode,  # type: ignore[attr-defined]
            ),
            Command(
                id="compact",
                label="Compact vault now",
                hint="Run end-of-day memory compaction",
                action=lambda: Maintenance().run_async(),
            ),
            Command(
                id="settings",
                label="Open settings",
                hint="Vault, storage tier, maintenance schedule",
                shortcut="···",
                action=self._open_settings,
            ),
            Command(
                id="focus_input",
                label="Focus conversation composer",
                hint="Jump to the message box",
                action=lambda: self.conversation.input.setFocus(),
            ),
            Command(
                id="quit",
                label="Quit Heirloom",
                hint="Close the app entirely (bypasses tray)",
                action=self.quit_requested.emit,
            ),
        ]

    def open_writing_helper(self) -> None:
        """Always-on-top Unbound Keyboard card. Does not hide the full window."""
        if self._writing is None:
            self._writing = WritingWindow()
            self._writing.closed.connect(self._persist_writing_geo)
        geo = self._settings.get("writing_geometry")
        if isinstance(geo, list) and len(geo) == 4:
            self._writing.setGeometry(*geo)
        self._writing.show()
        self._writing.raise_()
        self._writing.activateWindow()

    def _persist_writing_geo(self) -> None:
        if self._writing is None:
            return
        self._settings["writing_geometry"] = [
            self._writing.x(),
            self._writing.y(),
            self._writing.width(),
            self._writing.height(),
        ]
        config.save_settings(self._settings)

    def open_mini_talk(self) -> None:
        """Hide the full window and talk to the twin in a small always-on-top card."""
        if self._talk is None:
            self._talk = MiniTalkWindow()
            self._talk.send_requested.connect(self.conversation.send_text)
            self._talk.ptt_pressed.connect(self._ptt_start)
            self._talk.ptt_released.connect(self._ptt_stop)
            self._talk.restore_full.connect(self.restore_from_mini_talk)
            self._talk.closed.connect(self._on_mini_talk_closed)
            self.avatar.attach_talk_window(self._talk)
            self.avatar.status_changed.connect(self._talk.set_status)
        geo = self._settings.get("mini_talk_geometry")
        if isinstance(geo, list) and len(geo) == 4:
            self._talk.setGeometry(*geo)
        self._sync_mini_talk()
        self._talk.set_status(self.titlebar.pill_label.text() or "idle")
        self._talk.show()
        self._talk.raise_()
        self._talk.activateWindow()
        self.avatar.attach_talk_window(self._talk)
        self.hide()

    def restore_from_mini_talk(self) -> None:
        """Bring the full Heirloom window back; hide the compact talk card."""
        self._persist_mini_talk_geo()
        if self._talk is not None:
            self._talk.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.avatar._route_video_output()  # type: ignore[attr-defined]

    def _on_mini_talk_closed(self) -> None:
        self._persist_mini_talk_geo()
        self.avatar._route_video_output()  # type: ignore[attr-defined]

    def _persist_mini_talk_geo(self) -> None:
        if self._talk is None:
            return
        self._settings["mini_talk_geometry"] = [
            self._talk.x(),
            self._talk.y(),
            self._talk.width(),
            self._talk.height(),
        ]
        config.save_settings(self._settings)

    def _sync_mini_talk(self) -> None:
        if self._talk is None:
            return
        self._talk.set_messages(self.conversation.recent_messages(8))
        self._talk.set_busy(self.conversation.is_busy)


class TrayProxy:
    """Wraps QSystemTrayIcon so MainWindow can show/hide via tray actions."""

    def __init__(self, window: MainWindow):
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QStyle

        self.window = window
        icon = window.style().standardIcon

        self.tray = QSystemTrayIcon(window)
        self.tray.setIcon(icon(QStyle.SP_ComputerIcon))
        self.tray.setToolTip("Heirloom — your digital twin")

        menu = QMenu()
        menu.setStyleSheet(window.styleSheet())
        show = QAction("Open Heirloom", menu)
        show.triggered.connect(self._show)
        palette = QAction("Command palette  (Ctrl+K)", menu)
        palette.triggered.connect(window._open_palette)
        ptt = QAction("Push-to-talk", menu)
        ptt.triggered.connect(window._ptt_toggle)
        minitalk = QAction("Talk in a small window", menu)
        minitalk.triggered.connect(window.open_mini_talk)
        write = QAction("Unbound Keyboard", menu)
        write.triggered.connect(window.open_writing_helper)
        popout = QAction("Pop out avatar for OBS", menu)
        popout.triggered.connect(window.avatar.pop_out)
        quit_act = QAction("Quit Heirloom", menu)
        quit_act.triggered.connect(window.quit_requested.emit)
        menu.addAction(show)
        menu.addAction(palette)
        menu.addSeparator()
        menu.addAction(ptt)
        menu.addAction(minitalk)
        menu.addAction(write)
        menu.addAction(popout)
        menu.addSeparator()
        menu.addAction(quit_act)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    def _show(self) -> None:
        if self.window._talk is not None and self.window._talk.isVisible():
            self.window.restore_from_mini_talk()
            return
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _on_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason == QSystemTrayIcon.Trigger:
            if self.window._talk is not None and self.window._talk.isVisible():
                self.window.restore_from_mini_talk()
            elif self.window.isVisible():
                self.window.hide()
            else:
                self._show()
