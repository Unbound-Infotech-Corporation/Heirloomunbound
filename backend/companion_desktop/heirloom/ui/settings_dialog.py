"""Settings dialog — Sound + Vault + Local AI tabs.

Opened from the titlebar gear button. Uses a QTabWidget so the vault settings
stay put and new areas (Sound, Local AI, and later Themes) get their own tabs.

Sound tab:
    * Which microphone (PortAudio / sounddevice names)
    * Where the twin's voice comes out (Qt audio outputs)
    * How loud the twin talks

Local AI tab:
    * Five subsystems: chat / tts / stt / image / embeddings
    * Each has: enable / base URL / api key / model / test button
    * "Test" hits the URL directly (never sends the Heirloom device token
      out to a local endpoint).
    * Save posts the whole config back to /api/providers on the cloud so it
      follows the user across desktop installs.

The dialog stays modal + minimal-chrome so it feels like a serious PC app,
not a settings-explosion.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import api, config
from ..audio import list_input_devices, list_output_devices
from ..maintenance import Maintenance
from ..vault import Vault, vault_root
from . import PALETTE, QSS


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n} B"


def _label(text: str) -> QLabel:
    """Small overline label. Used for form field captions."""
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {PALETTE['text_muted']}; letter-spacing: 2px;"
        " font-size: 10px; text-transform: uppercase;"
    )
    return lbl


def list_speaker_names() -> list[str]:
    """Speakers/headphones Qt can actually play through."""
    return list_output_devices()


def _fill_device_combo(combo: QComboBox, names: list[str], saved: str, usual: str) -> None:
    combo.clear()
    combo.addItem(usual, "")
    seen = {""}
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        combo.addItem(name, name)
    wanted = (saved or "").strip()
    if wanted and wanted not in seen:
        combo.addItem(wanted, wanted)
    idx = 0
    if wanted:
        for i in range(combo.count()):
            if combo.itemData(i) == wanted:
                idx = i
                break
    combo.setCurrentIndex(idx)


# ------------------------------------------------------------------
# Sound — microphone, speakers, how loud the twin talks
# ------------------------------------------------------------------
class SoundTab(QWidget):
    """Pick the microphone and where the twin's voice comes out."""

    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings = config.load_settings()
        self._build()
        self._refresh_devices()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        overline = QLabel("SOUND")
        overline.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 2px; font-size: 10px;"
        )
        title = QLabel("Hear and be heard")
        title.setStyleSheet(
            f"color: {PALETTE['text_primary']};"
            " font-family: 'Cormorant Garamond', serif; font-size: 22px;"
        )
        sub = QLabel(
            "Pick the microphone you talk into, and the speakers or headphones "
            "where the twin should talk back. Leave them on “the usual one” if "
            "you only have one of each."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {PALETTE['text_secondary']}; font-size: 12px;")
        root.addWidget(overline)
        root.addWidget(title)
        root.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)

        self.mic_combo = QComboBox()
        self.mic_combo.setMinimumHeight(36)
        form.addRow(_label("Which microphone"), self.mic_combo)

        self.speaker_combo = QComboBox()
        self.speaker_combo.setMinimumHeight(36)
        form.addRow(_label("Where the twin's voice comes out"), self.speaker_combo)

        # Twin playback volume — matters on Windows where a QAudioOutput
        # session gets stuck at ~1% in the Mixer unless we set it explicitly.
        # Slider is 5-100 (never 0) because 0 causes the stuck-slider bug.
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(5, 100)
        try:
            _cur_vol = int(round(float(self._settings.get("twin_playback_volume", 1.0)) * 100))
        except (TypeError, ValueError):
            _cur_vol = 100
        self.volume_slider.setValue(max(5, min(100, _cur_vol)))
        self.volume_label = QLabel(f"{self.volume_slider.value()}%")
        self.volume_label.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 11px; min-width: 36px;"
        )
        self.volume_slider.valueChanged.connect(
            lambda v: self.volume_label.setText(f"{v}%")
        )
        vol_row = QWidget()
        vol_layout = QHBoxLayout(vol_row)
        vol_layout.setContentsMargins(0, 0, 0, 0)
        vol_layout.setSpacing(8)
        vol_layout.addWidget(self.volume_slider, 1)
        vol_layout.addWidget(self.volume_label)
        form.addRow(_label("How loud the twin talks"), vol_row)

        root.addLayout(form)

        hint = QLabel(
            "If you plug in headphones or a USB microphone, click Look again. "
            "Windows Mixer often shows this app at 1 and will not let you drag "
            "it — we push it up when the twin talks, then you can move it."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 12px;")
        root.addWidget(hint)

        actions = QHBoxLayout()
        look = QPushButton("Look again")
        look.setToolTip("Refresh the list of microphones and speakers")
        look.clicked.connect(self._refresh_devices)
        actions.addWidget(look)

        save_btn = QPushButton("Save sound settings")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_changes)
        actions.addWidget(save_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self.status_lbl = QLabel(" ")
        self.status_lbl.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 11px;")
        root.addWidget(self.status_lbl)
        root.addStretch(1)

    def _refresh_devices(self) -> None:
        s = config.load_settings()
        self._settings = s
        _fill_device_combo(
            self.mic_combo,
            list_input_devices(),
            str(s.get("mic_device") or ""),
            "The usual microphone",
        )
        _fill_device_combo(
            self.speaker_combo,
            list_speaker_names(),
            str(s.get("speaker_device") or ""),
            "The usual speakers",
        )
        n_mics = max(0, self.mic_combo.count() - 1)
        n_out = max(0, self.speaker_combo.count() - 1)
        if n_mics == 0 and n_out == 0:
            self.status_lbl.setText("Couldn't see any sound devices yet. Try Look again.")
        else:
            self.status_lbl.setText(" ")

    def _save_changes(self) -> None:
        s = config.load_settings()
        mic = self.mic_combo.currentData()
        speaker = self.speaker_combo.currentData()
        s["mic_device"] = mic if isinstance(mic, str) else ""
        s["speaker_device"] = speaker if isinstance(speaker, str) else ""
        s["twin_playback_volume"] = max(0.05, self.volume_slider.value() / 100.0)
        config.save_settings(s)
        self._settings = s
        self.status_lbl.setText("saved ✓")
        self.changed.emit()


# ------------------------------------------------------------------
# Local AI — provider rows
# ------------------------------------------------------------------
# Human-readable descriptions of each subsystem. Kept short — the settings
# tab is already dense.
_SUBSYSTEMS = [
    ("chat", "Chat / Twin brain",
     "The LLM your twin thinks with. Try Ollama (qwen2.5, llama3.3) or LM Studio.",
     "http://127.0.0.1:11434/v1", "llama3.3", "openai_compat"),
    ("tts", "Voice (Text → Speech)",
     "Local voice synth for the twin's replies. Try Kokoro-FastAPI or XTTS-v2.",
     "http://127.0.0.1:8880/v1", "kokoro-en", "openai_compat"),
    ("stt", "Transcription (Speech → Text)",
     "Turn your voice into text. Try Whisper.cpp server or Faster-Whisper.",
     "http://127.0.0.1:9000/v1", "whisper-large-v3", "openai_compat"),
    ("image", "Image generation",
     "Photo-to-Story, avatar frames, photo restoration. ComfyUI recommended.",
     "http://127.0.0.1:8188", "sdxl", "comfyui"),
    ("embeddings", "Memory search (embeddings)",
     "Semantic search over your archive. Try Ollama with nomic-embed-text.",
     "http://127.0.0.1:11434/v1", "nomic-embed-text", "openai_compat"),
]

# The "how to install" hint shown once at the top of the Local AI tab.
_LOCAL_AI_HINT = (
    "Local AI runs on YOUR PC — nothing leaves the machine. Install one of "
    "Pinokio, Ollama, or LM Studio, launch a model server, then paste the URL below."
)


class ProviderRow(QFrame):
    """One expandable row per subsystem. Enable checkbox on the outside,
    URL/key/model/test buttons inside. Collapsed by default when disabled."""

    def __init__(self, key: str, title: str, description: str,
                 example_url: str, example_model: str, provider_type: str,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.key = key
        self._provider_type = provider_type
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            f"background: {PALETTE['bg_surface']};"
            f" border: 1px solid {PALETTE['border']};"
            f" border-radius: 6px;"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        # Header row: checkbox + title + status
        head = QHBoxLayout()
        head.setSpacing(10)
        self.enable = QCheckBox()
        self.enable.setChecked(False)
        head.addWidget(self.enable)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {PALETTE['text_primary']}; font-size: 14px; font-weight: 500;"
        )
        head.addWidget(title_lbl)
        head.addStretch(1)

        self.status_lbl = QLabel("not tested")
        self.status_lbl.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 10px; letter-spacing: 1px;"
        )
        head.addWidget(self.status_lbl)
        v.addLayout(head)

        desc = QLabel(description)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {PALETTE['text_secondary']}; font-size: 12px;")
        v.addWidget(desc)

        # Form
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(example_url)
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("api key (optional — most local runtimes leave blank)")
        self.key_input.setEchoMode(QLineEdit.Password)
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText(example_model)

        form = QFormLayout()
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignLeft)
        form.addRow(_label("base url"), self.url_input)
        form.addRow(_label("api key"), self.key_input)
        form.addRow(_label("model"), self.model_input)
        v.addLayout(form)

        # Test button row
        test_row = QHBoxLayout()
        self.test_btn = QPushButton("Test connection")
        self.test_btn.clicked.connect(self._on_test)
        test_row.addWidget(self.test_btn)
        test_row.addStretch(1)
        v.addLayout(test_row)

    # ---------- state ----------
    def load(self, cfg: dict) -> None:
        self.enable.setChecked(bool(cfg.get("enabled", False)))
        self.url_input.setText(cfg.get("base_url", "") or "")
        # Redacted responses (post-SEC-HARD-2) send has_key=True and api_key="".
        # We show a placeholder so the user knows a key is stored without
        # re-exposing it. Re-typing overwrites; leaving blank keeps the stored value.
        stored_key = cfg.get("api_key", "") or ""
        self.key_input.setText(stored_key)
        if not stored_key and cfg.get("has_key"):
            self.key_input.setPlaceholderText("•••• stored ••••")
        else:
            self.key_input.setPlaceholderText("optional")
        self.model_input.setText(cfg.get("model", "") or "")

    def dump(self) -> dict:
        return {
            "enabled": self.enable.isChecked(),
            "base_url": self.url_input.text().strip(),
            "api_key": self.key_input.text().strip(),
            "model": self.model_input.text().strip(),
            "provider_type": self._provider_type,
        }

    # ---------- test ----------
    def _on_test(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            self._set_status("no URL to test", "error")
            return
        self._set_status("testing…", "muted")
        self.test_btn.setEnabled(False)

        # Probe endpoint depends on provider dialect
        if self._provider_type == "comfyui":
            probe = url.rstrip("/") + "/system_stats"
        else:
            # OpenAI-compat: GET /models returns 200 on any healthy server
            base = url.rstrip("/")
            if base.endswith("/v1"):
                probe = base + "/models"
            else:
                probe = base + "/v1/models"

        def _ok(res: dict) -> None:
            self.test_btn.setEnabled(True)
            if res.get("ok"):
                self._set_status(f"connected · HTTP {res.get('status')}", "ok")
            else:
                self._set_status(f"HTTP {res.get('status')}", "error")

        def _err(msg: str) -> None:
            self.test_btn.setEnabled(True)
            self._set_status("unreachable", "error")

        api.probe_local_url(
            probe, method="GET",
            api_key=self.key_input.text().strip() or None,
            on_ok=_ok, on_err=_err,
        )

    def _set_status(self, text: str, kind: str) -> None:
        color = {
            "ok": PALETTE["ok"] if "ok" in PALETTE else "#7da06f",
            "error": PALETTE.get("error", "#c0635a"),
            "muted": PALETTE["text_muted"],
        }.get(kind, PALETTE["text_muted"])
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; letter-spacing: 1px;"
        )


class LocalAITab(QWidget):
    """The Local AI settings tab — five providers + save button."""

    saved = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll area — five rows won't fit at 720px height
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none;")
        outer.addWidget(scroll, 1)

        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)

        overline = QLabel("LOCAL AI")
        overline.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 2px; font-size: 10px;"
        )
        v.addWidget(overline)

        title = QLabel("Run AI on your own hardware")
        title.setStyleSheet(
            f"color: {PALETTE['text_primary']};"
            " font-family: 'Cormorant Garamond', serif; font-size: 22px;"
        )
        v.addWidget(title)

        hint = QLabel(_LOCAL_AI_HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {PALETTE['text_secondary']}; font-size: 12px;"
        )
        v.addWidget(hint)

        # Suggestions bar
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for name, url in (
            ("Pinokio", "https://pinokio.co"),
            ("Ollama", "https://ollama.com"),
            ("LM Studio", "https://lmstudio.ai"),
            ("ComfyUI", "https://github.com/comfyanonymous/ComfyUI"),
        ):
            btn = QPushButton(name)
            btn.setObjectName("kbdhint")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, u=url: self._open_url(u))
            btn.setStyleSheet(
                f"color: {PALETTE['text_muted']};"
                f" background: {PALETTE['bg_surface']};"
                f" border: 1px solid {PALETTE['border']};"
                f" border-radius: 10px; padding: 3px 10px;"
                f" font-size: 10px; letter-spacing: 0.05em;"
            )
            chips.addWidget(btn)
        chips.addStretch(1)
        v.addLayout(chips)

        # Provider rows
        self.rows: dict[str, ProviderRow] = {}
        for key, title_, desc, ex_url, ex_model, ptype in _SUBSYSTEMS:
            row = ProviderRow(key, title_, desc, ex_url, ex_model, ptype)
            self.rows[key] = row
            v.addWidget(row)

        # Save button
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.status_lbl = QLabel(" ")
        self.status_lbl.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 11px;")
        save_row.addWidget(self.status_lbl)
        self.save_btn = QPushButton("Save Local AI settings")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self._save)
        save_row.addWidget(self.save_btn)
        v.addLayout(save_row)

        v.addStretch(1)
        scroll.setWidget(inner)

        # Load existing config
        self._load()

    def _open_url(self, url: str) -> None:
        try:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(url))
        except Exception:  # noqa: BLE001
            pass

    def _load(self) -> None:
        def _ok(cfg: dict) -> None:
            for key, row in self.rows.items():
                row.load(cfg.get(key, {}))
            # Cache into local settings so ConversationPanel can route to local chat
            try:
                cur = config.load_settings() or {}
                cur["providers_cache"] = cfg or {}
                config.save_settings(cur)
            except Exception:
                pass
            # Kick off auto-detect for any row still empty
            self._auto_detect_local_endpoints()

        def _err(msg: str) -> None:
            self.status_lbl.setText(f"couldn't load providers: {msg}")

        api.get_async("/providers", on_ok=_ok, on_err=_err)

    def _auto_detect_local_endpoints(self) -> None:
        """Ping the well-known local ports for Ollama, LM Studio, Pinokio and
        ComfyUI. If a row's URL is empty and a port answers, pre-fill it so
        the user just has to tick 'enabled' and hit Save.
        """
        candidates = {
            "chat":       ["http://127.0.0.1:11434", "http://127.0.0.1:1234"],  # Ollama, LM Studio
            "embeddings": ["http://127.0.0.1:11434"],                            # Ollama
            "tts":        ["http://127.0.0.1:8880"],                             # Kokoro-FastAPI
            "stt":        ["http://127.0.0.1:9000"],                             # Whisper.cpp server
            "image":      ["http://127.0.0.1:8188"],                             # ComfyUI
        }
        for key, row in self.rows.items():
            if row.url_input.text().strip():
                continue  # user already set it
            for base in candidates.get(key, []):
                self._probe_and_fill(row, base)

    def _probe_and_fill(self, row: "ProviderRow", base: str) -> None:
        """Fire-and-forget probe; on success, pre-fill the URL and mark status."""
        # Choose the endpoint per provider dialect (mirrors _on_test).
        if row._provider_type == "comfyui":
            probe = base.rstrip("/") + "/system_stats"
        else:
            probe = base.rstrip("/") + "/v1/models"

        def _ok(res: dict) -> None:
            if not res.get("ok"):
                return
            # Only fill if still empty (avoid races between multiple probes)
            if row.url_input.text().strip():
                return
            fill_url = base if row._provider_type == "comfyui" else base + "/v1"
            row.url_input.setText(fill_url)
            row._set_status("auto-detected · click enable", "ok")

        def _err(_msg: str) -> None:
            pass

        api.probe_local_url(probe, method="GET", on_ok=_ok, on_err=_err, timeout=1.5)

    def _save(self) -> None:
        payload = {key: row.dump() for key, row in self.rows.items()}
        self.save_btn.setEnabled(False)
        self.status_lbl.setText("saving…")

        def _ok(_res: dict) -> None:
            self.save_btn.setEnabled(True)
            self.status_lbl.setText("saved ✓")
            # Refresh local providers_cache so ConversationPanel routes locally on next send.
            try:
                cur = config.load_settings() or {}
                cur["providers_cache"] = payload
                config.save_settings(cur)
            except Exception:
                pass
            self.saved.emit()

        def _err(msg: str) -> None:
            self.save_btn.setEnabled(True)
            self.status_lbl.setText(f"save failed: {msg}")

        api.put_async("/providers", payload, on_ok=_ok, on_err=_err)


# ------------------------------------------------------------------
# Vault tab — extracted from the old flat dialog. Behavior unchanged.
# ------------------------------------------------------------------
class VaultTab(QWidget):
    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings = config.load_settings()
        self._maint = Maintenance(self)
        self._maint.progress.connect(self._on_progress)
        self._maint.completed.connect(self._on_completed)
        self._maint.finished.connect(self._on_finished)
        self._maint.error.connect(self._on_error)
        self._build()
        self._refresh_storage()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        overline = QLabel("LOCAL VAULT")
        overline.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 2px; font-size: 10px;"
        )
        title = QLabel("Your archive, on your disk")
        title.setStyleSheet(
            f"color: {PALETTE['text_primary']};"
            " font-family: 'Cormorant Garamond', serif; font-size: 22px;"
        )
        sub = QLabel(
            "Everything you say to your twin is captured here first. Once a day "
            "(or on demand), a compaction job extracts the durable bits and "
            "uploads them to your twin's permanent knowledge."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {PALETTE['text_secondary']}; font-size: 12px;")
        root.addWidget(overline)
        root.addWidget(title)
        root.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)

        folder_row = QHBoxLayout()
        self.folder_input = QLineEdit(str(vault_root()))
        self.folder_input.setReadOnly(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_folder)
        folder_row.addWidget(self.folder_input, 1)
        folder_row.addWidget(browse)
        folder_wrap = QWidget()
        folder_wrap.setLayout(folder_row)
        form.addRow(_label("Vault folder"), folder_wrap)

        self.tier = QComboBox()
        self.tier.addItem("Full · keep every turn + audio forever", "full")
        self.tier.addItem("Partial · keep audio 30 days, transcripts forever (recommended)", "partial")
        self.tier.addItem("Lite · keep only daily summaries + extracted facts", "lite")
        current_tier = self._settings.get("storage_tier", "partial")
        for i in range(self.tier.count()):
            if self.tier.itemData(i) == current_tier:
                self.tier.setCurrentIndex(i)
                break
        form.addRow(_label("Storage tier"), self.tier)

        self.schedule = QComboBox()
        self.schedule.addItem("At quit (recommended)", "on_quit")
        self.schedule.addItem("Daily at 3 AM (background)", "midnight")
        self.schedule.addItem("Manual only", "manual")
        cur_sched = self._settings.get("maintenance_schedule", "on_quit")
        for i in range(self.schedule.count()):
            if self.schedule.itemData(i) == cur_sched:
                self.schedule.setCurrentIndex(i)
                break
        form.addRow(_label("Maintenance schedule"), self.schedule)

        root.addLayout(form)

        usage_box = QFrame()
        usage_box.setStyleSheet(
            f"background: {PALETTE['bg_surface']}; border: 1px solid {PALETTE['border']};"
            " border-radius: 4px;"
        )
        ub = QVBoxLayout(usage_box)
        ub.setContentsMargins(14, 12, 14, 12)
        ub.setSpacing(6)
        self.usage_label = QLabel("…")
        self.usage_label.setStyleSheet(f"color: {PALETTE['text_primary']}; font-size: 13px;")
        self.usage_bar = QProgressBar()
        self.usage_bar.setMaximum(100)
        self.usage_bar.setFixedHeight(6)
        self.usage_bar.setTextVisible(False)
        self.usage_bar.setStyleSheet(
            f"QProgressBar {{ background: {PALETTE['bg_base']}; border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {PALETTE['accent']}; border-radius: 3px; }}"
        )
        self.last_compaction_label = QLabel("Last compaction: never")
        self.last_compaction_label.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 11px;"
        )
        ub.addWidget(self.usage_label)
        ub.addWidget(self.usage_bar)
        ub.addWidget(self.last_compaction_label)
        root.addWidget(usage_box)

        actions = QHBoxLayout()
        self.run_btn = QPushButton("Run maintenance now")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(self._run_now)
        actions.addWidget(self.run_btn)

        save_btn = QPushButton("Save changes")
        save_btn.clicked.connect(self._save_changes)
        actions.addWidget(save_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Maintenance log will appear here…")
        self.log.setMinimumHeight(120)
        self.log.setStyleSheet(
            f"background: {PALETTE['bg_base']}; border: 1px solid {PALETTE['border']};"
            " border-radius: 3px; font-family: 'IBM Plex Mono', Consolas, monospace;"
            " font-size: 11px;"
        )
        root.addWidget(self.log, 1)

    def _pick_folder(self) -> None:
        new = QFileDialog.getExistingDirectory(
            self, "Pick your vault folder", str(vault_root())
        )
        if new:
            self.folder_input.setText(new)

    def _save_changes(self) -> None:
        s = config.load_settings()
        s["vault_folder"] = self.folder_input.text().strip() or None
        s["storage_tier"] = self.tier.currentData()
        s["maintenance_schedule"] = self.schedule.currentData()
        config.save_settings(s)
        self._settings = s
        self.log.appendPlainText("Settings saved.")
        self._refresh_storage()
        self.changed.emit()

    def _run_now(self) -> None:
        self.run_btn.setEnabled(False)
        self.log.appendPlainText("Starting maintenance…")
        self._save_changes()
        self._maint.run_async()

    def _on_progress(self, msg: str) -> None:
        self.log.appendPlainText(f"·  {msg}")

    def _on_completed(self, payload: dict) -> None:
        self.log.appendPlainText(
            f"{payload['date']} — {payload['turns_seen']} turns → "
            f"{payload['facts_uploaded']} new facts learned "
            f"({payload['facts_skipped']} already known)"
        )

    def _on_finished(self, done: int, failed: int) -> None:
        self.log.appendPlainText(f"Done. {done} day(s) compacted, {failed} failed.")
        self.run_btn.setEnabled(True)
        s = config.load_settings()
        from datetime import datetime, timezone
        s["last_maintenance_at"] = datetime.now(timezone.utc).isoformat()
        config.save_settings(s)
        self._refresh_storage()

    def _on_error(self, msg: str) -> None:
        self.log.appendPlainText(f"Error: {msg}")
        self.run_btn.setEnabled(True)

    def _refresh_storage(self) -> None:
        try:
            v = Vault()
            usage = v.storage_usage()
        except Exception as exc:  # noqa: BLE001
            self.usage_label.setText(f"Vault unavailable: {exc}")
            return
        self.usage_label.setText(
            f"{_human_bytes(usage['bytes'])} across {usage['files']} files · "
            f"{usage['turns']} turns · {usage['compactions']} compactions"
        )
        pct = min(100, int(usage["bytes"] / (1024 * 1024 * 10)))
        self.usage_bar.setValue(pct)
        last = v.last_compaction()
        if last:
            self.last_compaction_label.setText(
                f"Last compaction: {last['date']} ({last['turns_seen']} turns, "
                f"{last['facts_extracted']} facts learned)"
            )
        else:
            self.last_compaction_label.setText("Last compaction: never")

        def _on_status(d):
            facts_v = (d or {}).get("facts_from_vault", 0)
            total = (d or {}).get("total_facts", 0)
            self.last_compaction_label.setText(
                self.last_compaction_label.text()
                + f"  ·  cloud has {facts_v}/{total} facts about you"
            )
        api.get_async("/vault/status", on_ok=_on_status, on_err=lambda _m: None)


# ------------------------------------------------------------------
# Main dialog with tabs
# ------------------------------------------------------------------
class SettingsDialog(QDialog):
    """Modal settings dialog. Emits `changed` if the vault tab saved anything."""

    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet(QSS)
        self.setWindowTitle("Heirloom · Settings")
        self.setModal(True)
        self.resize(700, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: none; background: transparent; }}"
            f"QTabBar::tab {{"
            f"  color: {PALETTE['text_muted']}; padding: 10px 22px;"
            f"  background: transparent; border: none;"
            f"  border-bottom: 2px solid transparent;"
            f"  font-size: 12px; letter-spacing: 1px; text-transform: uppercase;"
            f"}}"
            f"QTabBar::tab:selected {{"
            f"  color: {PALETTE['accent']};"
            f"  border-bottom: 2px solid {PALETTE['accent']};"
            f"}}"
            f"QTabBar::tab:hover:!selected {{ color: {PALETTE['text_primary']}; }}"
        )

        self.sound_tab = SoundTab()
        self.sound_tab.changed.connect(self.changed.emit)
        tabs.addTab(self.sound_tab, "Sound")

        self.vault_tab = VaultTab()
        self.vault_tab.changed.connect(self.changed.emit)
        tabs.addTab(self.vault_tab, "Vault")

        self.local_ai_tab = LocalAITab()
        self.local_ai_tab.saved.connect(self.changed.emit)
        tabs.addTab(self.local_ai_tab, "Local AI")

        root.addWidget(tabs, 1)

        # Footer close button
        footer = QHBoxLayout()
        footer.setContentsMargins(20, 12, 20, 16)
        footer.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)
