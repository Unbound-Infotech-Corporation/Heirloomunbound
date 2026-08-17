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
    QMdiArea,
    QPushButton,
    QSizeGrip,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, api, audio, commands, config
from ..commands import CommandPoller
from ..maintenance import Maintenance
from ..mixer import MixerSession
from ..vault import Vault
from . import PALETTE, QSS
from .avatar_panel import AvatarPanel
from .command_palette import Command, CommandPalette
from .conversation import ConversationPanel
from .mdi import FeatureWindow
from .mica import apply as apply_mica
from .mixer_panel import MixerPanel
from .models_panel import ModelsPanel
from .panels import QuickCapture, RecentMemories
from .settings_dialog import SettingsDialog
from .titlebar import TitleBar


class MainWindow(QMainWindow):
    quit_requested = Signal()

    def __init__(self):
        super().__init__()
        self._settings = config.load_settings()
        self._user: dict = {}
        self._palette: Optional[CommandPalette] = None
        self._mica_applied = False

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

        # ---- Photoshop-style MDI workspace ----
        self.mdi = QMdiArea()
        self.mdi.setViewMode(QMdiArea.SubWindowView)
        self.mdi.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.mdi.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        card_layout.addWidget(self.mdi, 1)

        self.mixer_session = MixerSession(self)
        self.recorder = audio.Recorder(self)
        self.live = audio.LiveListen(self.recorder, self)

        self.memories = RecentMemories()
        self.avatar = AvatarPanel(self._settings)
        self.avatar.bind_mixer(self.mixer_session)
        self.conversation = ConversationPanel(self._settings)
        self.quickcap = QuickCapture()
        self.mixer_panel = MixerPanel(self.mixer_session)
        self.models_panel = ModelsPanel()

        twin_body = QWidget()
        twin_split = QSplitter(Qt.Vertical)
        twin_split.setChildrenCollapsible(False)
        twin_split.addWidget(self.avatar)
        twin_split.addWidget(self.conversation)
        twin_split.setSizes([360, 440])
        twin_lay = QVBoxLayout(twin_body)
        twin_lay.setContentsMargins(0, 0, 0, 0)
        twin_lay.addWidget(twin_split)

        self.win_twin = FeatureWindow("Twin", twin_body, parent=self.mdi)
        self.win_archive = FeatureWindow("Archive", self.memories, parent=self.mdi)
        self.win_capture = FeatureWindow("Capture", self.quickcap, parent=self.mdi)
        self.win_mixer = FeatureWindow("Mixer", self.mixer_panel, parent=self.mdi)
        self.win_models = FeatureWindow("Models", self.models_panel, parent=self.mdi)
        for w in (self.win_twin, self.win_archive, self.win_capture, self.win_mixer, self.win_models):
            self.mdi.addSubWindow(w)
            w.show()
        self.win_twin.resize(760, 620)
        self.win_archive.resize(280, 520)
        self.win_capture.resize(300, 420)
        self.win_mixer.resize(420, 640)
        self.win_models.resize(460, 560)
        self._install_window_menus()
        self.mdi.tileSubWindows()

        # ---- resize grip strip at the bottom-right ----
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch(1)
        grip = QSizeGrip(self)
        grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(grip, 0, Qt.AlignRight | Qt.AlignBottom)
        card_layout.addLayout(grip_row)

        try:
            self._vault: Vault | None = Vault()
        except Exception as exc:  # noqa: BLE001
            print(f"[vault] init failed: {exc}")
            self._vault = None
        self._active_conv_id = "comp_local"
        self._audio_settings: dict = {}
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(400)
        self._persist_timer.timeout.connect(self._persist_audio)

    def _install_window_menus(self) -> None:
        self.win_twin.rebuild_menus(
            [
                (
                    "Twin",
                    [
                        ("Speak selection / composer", self._open_palette, "Ctrl+K"),
                        ("Push-to-talk", self._ptt_toggle, "Ctrl+Space"),
                        ("---", None, ""),
                        ("Pop out avatar for OBS", self.avatar.pop_out, ""),
                        ("Toggle avatar mode", self.avatar._toggle_mode, ""),
                    ],
                ),
                (
                    "Voice",
                    [
                        ("Volume +10", lambda: self._nudge_volume(10), ""),
                        ("Volume -10", lambda: self._nudge_volume(-10), ""),
                        ("Mute output", lambda: self._set_mute_output(True), ""),
                        ("Unmute output", lambda: self._set_mute_output(False), ""),
                    ],
                ),
                (
                    "Window",
                    [
                        ("Maximize Twin", self.win_twin.showMaximized, ""),
                        ("Tile all", self.mdi.tileSubWindows, ""),
                        ("Cascade", self.mdi.cascadeSubWindows, ""),
                    ],
                ),
            ]
        )
        self.win_mixer.rebuild_menus(
            [
                (
                    "Devices",
                    [
                        ("Refresh device list", self.mixer_panel.refresh_devices, ""),
                        ("Play test tone", self.mixer_panel._test_tone, ""),
                    ],
                ),
                (
                    "Input",
                    [
                        ("Toggle mute input", lambda: self._toggle_audio_flag("mute_input"), ""),
                        ("Toggle live listen", lambda: self._toggle_audio_flag("live_listen"), ""),
                        ("Toggle monitor", lambda: self._toggle_audio_flag("monitor_input"), ""),
                    ],
                ),
                (
                    "Output",
                    [
                        ("Toggle mute output", lambda: self._toggle_audio_flag("mute_output"), ""),
                        ("Session volume 100%", lambda: self._apply_session_volume(100), ""),
                        ("Session volume 50%", lambda: self._apply_session_volume(50), ""),
                        ("Session volume 0%", lambda: self._apply_session_volume(0), ""),
                    ],
                ),
                (
                    "Sample rate",
                    [
                        ("16 kHz (voice)", lambda: self._set_sample_rate(16000), ""),
                        ("44.1 kHz", lambda: self._set_sample_rate(44100), ""),
                        ("48 kHz", lambda: self._set_sample_rate(48000), ""),
                    ],
                ),
            ]
        )
        self.win_models.rebuild_menus(
            [
                (
                    "Models",
                    [
                        ("Refresh probe", self.models_panel.refresh, ""),
                        ("Provision on this PC", self.models_panel.provision_local, ""),
                        ("Queue provision from studio", self.models_panel.queue_remote, ""),
                    ],
                ),
                (
                    "Backends",
                    [
                        ("Set all to Auto", lambda: self.models_panel.map_changed.emit({}), ""),
                    ],
                ),
            ]
        )
        self.win_archive.rebuild_menus(
            [
                (
                    "Archive",
                    [
                        ("Refresh", self.memories.refresh, ""),
                        ("Compact vault now", lambda: Maintenance().run_async(), ""),
                    ],
                )
            ]
        )
        self.win_capture.rebuild_menus(
            [
                (
                    "Capture",
                    [
                        ("Focus capture", lambda: self.win_capture.showNormal() or self.win_capture.raise_(), ""),
                    ],
                )
            ]
        )

    def _nudge_volume(self, delta: int) -> None:
        current = int(self._audio_settings.get("output_volume") or 80)
        self._apply_session_volume(max(0, min(100, current + delta)))

    def _set_mute_output(self, muted: bool) -> None:
        settings = {**self.mixer_panel.collect(), "mute_output": muted}
        self.mixer_panel.apply_settings(settings)
        self._on_mixer_changed(settings)

    def _toggle_audio_flag(self, key: str) -> None:
        settings = self.mixer_panel.collect()
        settings[key] = not bool(settings.get(key))
        self.mixer_panel.apply_settings(settings)
        self._on_mixer_changed(settings)

    def _set_sample_rate(self, rate: int) -> None:
        settings = {**self.mixer_panel.collect(), "sample_rate": rate}
        self.mixer_panel.apply_settings(settings)
        self._on_mixer_changed(settings)

    def _apply_session_volume(self, level: int) -> None:
        settings = {**self.mixer_panel.collect(), "output_volume": int(level)}
        self.mixer_panel.apply_settings(settings)
        self._on_mixer_changed(settings)

    def _wire_signals(self) -> None:
        # Quick-cap refresh sidebar
        self.quickcap.saved.connect(lambda _d: self.memories.refresh())
        # Twin reply triggers avatar speak
        self.conversation.reply_received.connect(self._on_twin_reply)
        # Vault capture — every text turn (user + assistant)
        self.conversation.message_sent.connect(lambda t: self._vault_capture("user", t, "chat"))
        self.conversation.reply_received.connect(lambda t: self._vault_capture("assistant", t, "chat"))
        # Avatar status → titlebar pill + aura
        self.avatar.status_changed.connect(self._update_status)
        # Recorder
        self.recorder.level.connect(self.avatar.set_level)
        self.recorder.level.connect(lambda lvl: self.mixer_panel.set_level(lvl))
        self.recorder.wav_bytes.connect(self._upload_voice)
        self.recorder.error.connect(lambda msg: self._update_status(f"mic: {msg}"))
        self.live.wav_bytes.connect(self._upload_voice)
        self.live.started.connect(lambda: self._update_status("room: listening…"))
        self.live.error.connect(lambda msg: self._update_status(f"live: {msg}"))
        self.mixer_panel.settings_changed.connect(self._on_mixer_changed)
        self.mixer_panel.live_listen_toggled.connect(self._on_live_listen)

        # Global shortcuts
        for seq in ("Ctrl+K", "Ctrl+P"):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(self._open_palette)
        # Ctrl+Space: hold-to-talk (press = start, release = stop).
        # Fall back to toggle if the platform only fires activated.
        self._ptt_shortcut = QShortcut(QKeySequence("Ctrl+Space"), self)
        self._ptt_shortcut.setContext(Qt.ApplicationShortcut)
        self._ptt_shortcut.setAutoRepeat(False)
        self._ptt_shortcut.activated.connect(self._ptt_start)
        try:
            self._ptt_shortcut.activatedAmbiguously.connect(self._ptt_start)
        except Exception:  # noqa: BLE001
            pass
        # Capture key release via event filter on the app so hold-to-talk works
        from PySide6.QtWidgets import QApplication

        QApplication.instance().installEventFilter(self)

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
            # Block briefly so compaction can finish before the process exits.
            m.run()
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
        self._cmd_poller.status.connect(self._on_poller_status)
        self._cmd_poller.audio_settings.connect(self._apply_audio_settings)
        self._cmd_poller.volume_command.connect(self._apply_session_volume)
        self._cmd_poller.start()
        commands.register_volume_hook(self._apply_session_volume)
        api.get_async("/studio/audio", on_ok=lambda d: self._apply_audio_settings((d or {}).get("settings") or {}), on_err=lambda _m: None)
        # Preflight: cloned-voice status for Waveform mode
        api.get_async(
            "/desktop/voice/status",
            on_ok=self._on_voice_status,
            on_err=lambda _m: None,
        )

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
        self.titlebar.set_user_name("sign-in required")
        self._update_status("not authed")

    def _on_poller_status(self, msg: str) -> None:
        if not msg:
            return
        self._update_status(msg)

    def _on_voice_status(self, data: dict) -> None:
        configured = bool((data or {}).get("configured"))
        self._settings["voice_configured"] = configured
        config.save_settings(self._settings)
        if configured:
            name = (data or {}).get("voice_name") or "cloned voice"
            self._update_status(f"voice ready · {name}")

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
        if self.recorder.is_recording() and not self._audio_settings.get("live_listen"):
            return
        if self._audio_settings.get("live_listen"):
            self.live.set_enabled(False)
        self._update_status("listening…")
        self.recorder.start()

    def _ptt_stop(self) -> None:
        if not self.recorder.is_recording():
            return
        self._update_status("thinking…")
        self.recorder.stop()
        if self._audio_settings.get("live_listen"):
            QTimer.singleShot(400, lambda: self.live.set_enabled(True, int(self._audio_settings.get("vad_hangover_ms") or 900)))

    def _on_mixer_changed(self, settings: dict) -> None:
        self._apply_audio_settings(settings, persist=True)

    def _on_live_listen(self, enabled: bool) -> None:
        hang = int(self._audio_settings.get("vad_hangover_ms") or 900)
        self.live.set_enabled(enabled, hang)

    def _apply_audio_settings(self, settings: dict, persist: bool = False) -> None:
        if not isinstance(settings, dict):
            return
        merged = {**self._audio_settings, **settings}
        live_changed = bool(merged.get("live_listen")) != bool(self._audio_settings.get("live_listen"))
        if merged == self._audio_settings and not persist:
            return
        self._audio_settings = merged
        self.recorder.apply_settings(self._audio_settings)
        self.mixer_session.set_device(self._audio_settings.get("output_device_id") or "default")
        self.mixer_session.set_volume(int(self._audio_settings.get("output_volume") or 80))
        self.mixer_session.set_mute(bool(self._audio_settings.get("mute_output")))
        self.mixer_session.apply_to_qaudio(self.avatar.audio)
        self.mixer_panel.apply_settings(self._audio_settings)
        if live_changed or persist:
            self.live.set_enabled(
                bool(self._audio_settings.get("live_listen")),
                int(self._audio_settings.get("vad_hangover_ms") or 900),
            )
        if persist:
            self._persist_timer.start()

    def _persist_audio(self) -> None:
        api.put_async(
            "/studio/audio",
            self.mixer_panel.collect(),
            on_ok=lambda _d: None,
            on_err=lambda m: self._update_status(f"mixer save: {m[:40]}"),
        )

    def eventFilter(self, obj, event):  # noqa: N802
        """Hold-to-talk: stop recording when Ctrl or Space is released."""
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent

        if event.type() == QEvent.KeyRelease and self.recorder.is_recording():
            ke: QKeyEvent = event  # type: ignore[assignment]
            if ke.key() in (Qt.Key_Space, Qt.Key_Control):
                # Only stop if the other half of Ctrl+Space is also up
                mods = ke.modifiers()
                if not (mods & Qt.ControlModifier) or ke.key() == Qt.Key_Space:
                    self._ptt_stop()
        return super().eventFilter(obj, event)

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
        tools = (data or {}).get("tool_trace") or []
        wav = getattr(self, "_pending_voice_audio", None)
        self._pending_voice_audio = None
        if user_text:
            self.conversation.append("user", user_text)
            self._vault_capture("user", user_text, "voice", audio_bytes=wav)
        if tools:
            labels = ", ".join(
                (t.get("ui") or {}).get("label") or t.get("name") or "tool"
                for t in tools
            )
            self.conversation.append("assistant", f"⚙ {labels}")
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
            self.conversation.input.setPlainText("")
            self.conversation.append("user", q)
            self.conversation.message_sent.emit(q)
            self.conversation._busy = True  # type: ignore[attr-defined]
            api.post_async(
                "/desktop/chat",
                {"text": q},
                on_ok=lambda d: self.conversation._on_reply(d),  # type: ignore[attr-defined]
                on_err=lambda m: self.conversation._on_error(m),  # type: ignore[attr-defined]
            )

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
                id="mixer",
                label="Mixer window",
                hint="Input/output devices, gain, gate, Heirloom session volume",
                action=lambda: (self.win_mixer.show(), self.win_mixer.raise_()),
            ),
            Command(
                id="models",
                label="Models window",
                hint="Provision Whisper / Ollama on this PC",
                action=lambda: (self.win_models.show(), self.win_models.raise_()),
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
        popout = QAction("Pop out avatar for OBS", menu)
        popout.triggered.connect(window.avatar.pop_out)
        quit_act = QAction("Quit Heirloom", menu)
        quit_act.triggered.connect(window.quit_requested.emit)
        menu.addAction(show)
        menu.addAction(palette)
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
