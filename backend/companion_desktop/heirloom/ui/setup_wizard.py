"""First-run setup (5 steps) and the optional tips card.

Cream cards, same language as Sign in with Google. No vendor names.
The wizard helps with Google, your talking picture, your microphone,
where the twin's voice comes out, and how you'll talk to it.

Tips can open every time Heirloom starts. Uncheck that, or tap
Don't show this next time, and it stays gone.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPalette, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import api, audio, config
from ..google_signin import finish_pair_flow, house_url, open_browser, start_pair_flow

# Unscoped on purpose. The main window's dark QSS (`* { color: #f5efe6 }`)
# makes pale letters on this cream card. Same trick as Unbound Keyboard.
INK = "#3a2418"
CREAM = "#f4e8c8"
PAPER = "#fff8e4"
TOMATO = "#c45c38"

CREAM_QSS = f"""
QWidget {{
    color: {INK};
    background: transparent;
    font-family: 'Segoe UI', sans-serif;
    font-size: 15px;
}}
QWidget#card {{
    background: {CREAM};
    border: 5px solid {TOMATO};
    border-radius: 28px;
}}
QLabel {{ color: {INK}; background: transparent; }}
QStackedWidget {{ background: {CREAM}; border: none; color: {INK}; }}
QPushButton {{
    background: #fffdf6;
    color: {INK};
    border: 3px solid {INK};
    border-radius: 14px;
    padding: 10px 14px;
    font-weight: 800;
    font-size: 15px;
}}
QPushButton:hover {{ background: #fff3c4; color: {INK}; }}
QPushButton:disabled {{
    color: #8a7060;
    background: #f3ead8;
    border-color: #c4b49a;
}}
QPushButton#primary {{
    background: {TOMATO};
    color: {PAPER};
    font-size: 16px;
    min-height: 44px;
}}
QPushButton#primary:hover {{ background: #a94c2e; color: {PAPER}; }}
QPushButton#ghost {{
    border: none;
    background: transparent;
    color: #5a3a28;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton#ghost:hover {{ background: #fff3c4; color: {INK}; }}
QComboBox {{
    background: {PAPER};
    color: {INK};
    border: 3px solid {INK};
    border-radius: 12px;
    padding: 8px 12px;
    min-height: 36px;
    font-size: 15px;
}}
QComboBox QAbstractItemView {{
    background: {PAPER};
    color: {INK};
    selection-background-color: #f0c040;
    selection-color: {INK};
}}
QComboBox QLineEdit {{
    background: {PAPER};
    color: {INK};
}}
QSlider::groove:horizontal {{
    height: 10px;
    background: #e8d4a8;
    border: 2px solid {INK};
    border-radius: 6px;
}}
QSlider::handle:horizontal {{
    width: 22px;
    margin: -8px 0;
    background: {TOMATO};
    border: 3px solid {INK};
    border-radius: 12px;
}}
QProgressBar {{
    background: {PAPER};
    border: 3px solid {INK};
    border-radius: 10px;
    text-align: center;
    color: {INK};
    min-height: 18px;
}}
QProgressBar::chunk {{ background: {TOMATO}; border-radius: 7px; }}
QCheckBox {{
    color: {INK};
    background: transparent;
    font-size: 15px;
    font-weight: 700;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 20px;
    height: 20px;
    border: 3px solid {INK};
    border-radius: 6px;
    background: {PAPER};
}}
QCheckBox::indicator:checked {{ background: {TOMATO}; }}
QLabel#dot_on {{ color: {TOMATO}; font-size: 22px; background: transparent; }}
QLabel#dot_off {{ color: #c4b49a; font-size: 22px; background: transparent; }}
"""


def apply_cream_palette(widget: QWidget) -> None:
    """Force dark-brown ink on cream even when Windows is in dark mode."""
    ink = QColor(INK)
    cream = QColor(CREAM)
    paper = QColor(PAPER)
    pal = widget.palette()
    for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        pal.setColor(group, QPalette.Window, cream)
        pal.setColor(group, QPalette.WindowText, ink)
        pal.setColor(group, QPalette.Base, paper)
        pal.setColor(group, QPalette.AlternateBase, cream)
        pal.setColor(group, QPalette.Text, ink)
        pal.setColor(group, QPalette.Button, QColor("#fffdf6"))
        pal.setColor(group, QPalette.ButtonText, ink)
        pal.setColor(group, QPalette.BrightText, ink)
        pal.setColor(group, QPalette.PlaceholderText, QColor("#8a7060"))
        pal.setColor(group, QPalette.Highlight, QColor(TOMATO))
        pal.setColor(group, QPalette.HighlightedText, QColor(PAPER))
    widget.setPalette(pal)
    widget.setAutoFillBackground(True)


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


def _image_mime(path: str, data: bytes) -> tuple[str, str]:
    lower = (path or "").lower()
    if data.startswith(b"\x89PNG") or lower.endswith(".png"):
        return "face.png", "image/png"
    if (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP") or lower.endswith(
        ".webp"
    ):
        return "face.webp", "image/webp"
    return "face.jpg", "image/jpeg"


class SetupWizard(QWidget):
    """Five-step first-run card."""

    signed_in = Signal()
    sound_changed = Signal()
    setup_done = Signal()
    face_ready = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("setup_wizard")
        self.setWindowTitle("Welcome to Heirloom")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.resize(540, 680)
        self.setStyleSheet(CREAM_QSS)
        self._drag_pos = None
        self._busy = False
        self._index = 0
        self._finished = False
        self._mic_rec = audio.Recorder(self)
        self._mic_rec.level.connect(self._on_mic_level)
        self._mic_rec.wav_bytes.connect(self._on_mic_test_wav)
        self._mic_rec.error.connect(self._on_mic_err)
        self._build()
        self._set_step(0)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        card = QWidget()
        card.setObjectName("card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        apply_cream_palette(card)
        root.addWidget(card, 1)
        col = QVBoxLayout(card)
        col.setContentsMargins(28, 22, 28, 20)
        col.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel("Welcome to Heirloom")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 24px; font-weight: 700; color: #3a2418;")
        top.addWidget(title, 1)
        close = QPushButton("×")
        close.setFixedSize(32, 32)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(lambda _checked=False: self._skip())
        top.addWidget(close)
        col.addLayout(top)

        hi = QLabel("Hi. Five little steps and your twin is you.")
        hi.setWordWrap(True)
        hi.setStyleSheet("font-size: 14px; color: #5a3a28;")
        col.addWidget(hi)

        self.step_lbl = QLabel("Step 1 of 5")
        self.step_lbl.setStyleSheet("font-size: 13px; font-weight: 800; color: #c45c38;")
        col.addWidget(self.step_lbl)

        dots = QHBoxLayout()
        dots.setSpacing(6)
        self._dots: list[QLabel] = []
        for _ in range(5):
            dot = QLabel("●")
            dot.setObjectName("dot_off")
            self._dots.append(dot)
            dots.addWidget(dot)
        dots.addStretch(1)
        col.addLayout(dots)

        self.stack = QStackedWidget()
        apply_cream_palette(self.stack)
        self.stack.addWidget(self._page_google())
        self.stack.addWidget(self._page_face())
        self.stack.addWidget(self._page_voice())
        self.stack.addWidget(self._page_hear())
        self.stack.addWidget(self._page_how())
        col.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.clicked.connect(lambda _checked=False: self._set_step(self._index - 1))
        foot.addWidget(self.back_btn)
        skip = QPushButton("I'll look around myself")
        skip.setObjectName("ghost")
        skip.setCursor(Qt.PointingHandCursor)
        skip.clicked.connect(lambda _checked=False: self._skip())
        foot.addWidget(skip)
        foot.addStretch(1)
        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("primary")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.clicked.connect(lambda _checked=False: self._next())
        foot.addWidget(self.next_btn)
        col.addLayout(foot)

    def _cream_page(self) -> QWidget:
        page = QWidget()
        page.setAttribute(Qt.WA_StyledBackground, True)
        apply_cream_palette(page)
        return page

    def _page_google(self) -> QWidget:
        page = self._cream_page()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 8, 0, 0)
        col.setSpacing(10)
        head = QLabel("Sign in with Google")
        head.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {INK}; background: transparent;")
        col.addWidget(head)
        blurb = QLabel(
            "Tap the button. A Google page opens in your browser. "
            "Sign in there. Heirloom never sees that password."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("font-size: 14px; color: #5a3a28;")
        col.addWidget(blurb)
        self.google_note = QLabel("Tap Sign in with Google.")
        self.google_note.setWordWrap(True)
        self.google_note.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.google_note.setStyleSheet("font-size: 13px; color: #5a3a28;")
        col.addWidget(self.google_note)
        self.google_btn = QPushButton("Sign in with Google")
        self.google_btn.setObjectName("primary")
        self.google_btn.setCursor(Qt.PointingHandCursor)
        self.google_btn.clicked.connect(lambda _checked=False: self._start_google())
        col.addWidget(self.google_btn)
        col.addStretch(1)
        return page

    def _page_face(self) -> QWidget:
        page = self._cream_page()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 8, 0, 0)
        col.setSpacing(10)
        head = QLabel("Your face — the talking picture")
        head.setWordWrap(True)
        head.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {INK}; background: transparent;")
        col.addWidget(head)
        blurb = QLabel(
            "Pick a photo of you looking at the camera. That still becomes "
            "the live talking picture of you."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("font-size: 14px; color: #5a3a28;")
        col.addWidget(blurb)
        self.face_preview = QLabel("No photo yet")
        self.face_preview.setAlignment(Qt.AlignCenter)
        self.face_preview.setFixedSize(168, 168)
        self.face_preview.setStyleSheet(
            "background: #fff8e4; border: 3px solid #3a2418; border-radius: 18px;"
            " font-size: 13px; color: #8a7060;"
        )
        col.addWidget(self.face_preview, 0, Qt.AlignHCenter)
        self.face_note = QLabel("A clear front-facing photo works best.")
        self.face_note.setWordWrap(True)
        self.face_note.setStyleSheet("font-size: 13px; color: #5a3a28;")
        col.addWidget(self.face_note)
        pick = QPushButton("Pick a photo")
        pick.setObjectName("primary")
        pick.setCursor(Qt.PointingHandCursor)
        pick.clicked.connect(lambda _checked=False: self._pick_face())
        col.addWidget(pick)
        more = QPushButton("Open the page that sets up your talking picture")
        more.setCursor(Qt.PointingHandCursor)
        more.clicked.connect(lambda _checked=False: self._open_house("/avatar-studio"))
        col.addWidget(more)
        col.addStretch(1)
        return page

    def _page_voice(self) -> QWidget:
        page = self._cream_page()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 8, 0, 0)
        col.setSpacing(10)
        head = QLabel("Your voice")
        head.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {INK}; background: transparent;")
        col.addWidget(head)
        blurb = QLabel(
            "Pick the microphone you talk into. Hold the button to test it — "
            "that stays on this computer. To make the twin sound like you, "
            "open the page that clones your voice."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("font-size: 14px; color: #5a3a28;")
        col.addWidget(blurb)
        mic_lbl = QLabel("Which microphone")
        mic_lbl.setStyleSheet("font-size: 12px; font-weight: 800; color: #5a3a28;")
        col.addWidget(mic_lbl)
        self.mic_combo = QComboBox()
        apply_cream_palette(self.mic_combo)
        col.addWidget(self.mic_combo)
        self.mic_level = QProgressBar()
        self.mic_level.setRange(0, 100)
        self.mic_level.setValue(0)
        self.mic_level.setTextVisible(False)
        col.addWidget(self.mic_level)
        hold = QPushButton("Hold to test your microphone")
        hold.setCursor(Qt.PointingHandCursor)
        hold.pressed.connect(self._mic_test_start)
        hold.released.connect(self._mic_test_stop)
        col.addWidget(hold)
        self.voice_note = QLabel("Hold, say hello, let go. We do not upload that.")
        self.voice_note.setWordWrap(True)
        self.voice_note.setStyleSheet("font-size: 13px; color: #5a3a28;")
        col.addWidget(self.voice_note)
        clone = QPushButton("Open the page that clones your voice")
        clone.setCursor(Qt.PointingHandCursor)
        clone.clicked.connect(lambda _checked=False: self._open_house("/settings"))
        col.addWidget(clone)
        col.addStretch(1)
        return page

    def _page_hear(self) -> QWidget:
        page = self._cream_page()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 8, 0, 0)
        col.setSpacing(10)
        head = QLabel("Hear the twin")
        head.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {INK}; background: transparent;")
        col.addWidget(head)
        blurb = QLabel(
            "Pick the speakers or headphones where the twin should talk. "
            "Leave it on the usual one if you only have one pair."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("font-size: 14px; color: #5a3a28;")
        col.addWidget(blurb)
        sp_lbl = QLabel("Where the twin's voice comes out")
        sp_lbl.setStyleSheet("font-size: 12px; font-weight: 800; color: #5a3a28;")
        col.addWidget(sp_lbl)
        self.speaker_combo = QComboBox()
        apply_cream_palette(self.speaker_combo)
        col.addWidget(self.speaker_combo)
        vol_lbl = QLabel("How loud")
        vol_lbl.setStyleSheet("font-size: 12px; font-weight: 800; color: #5a3a28;")
        col.addWidget(vol_lbl)
        vol_row = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(5, 100)
        try:
            cur = int(round(float(config.load_settings().get("twin_playback_volume", 1.0)) * 100))
        except (TypeError, ValueError):
            cur = 100
        self.volume_slider.setValue(max(5, min(100, cur)))
        self.volume_value = QLabel(f"{self.volume_slider.value()}%")
        self.volume_value.setStyleSheet(
            f"font-size: 14px; font-weight: 800; min-width: 44px; color: {INK}; background: transparent;"
        )
        self.volume_slider.valueChanged.connect(
            lambda v: self.volume_value.setText(f"{v}%")
        )
        vol_row.addWidget(self.volume_slider, 1)
        vol_row.addWidget(self.volume_value)
        col.addLayout(vol_row)
        col.addStretch(1)
        return page

    def _page_how(self) -> QWidget:
        page = self._cream_page()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 8, 0, 0)
        col.setSpacing(10)
        head = QLabel("How you'll use it")
        head.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {INK}; background: transparent;")
        col.addWidget(head)
        blurb = QLabel(
            "Hold to speak (Ctrl+Space).\n"
            "Look at my screen — the twin peeks, then the picture is deleted.\n"
            "Unbound Keyboard (Ctrl+Shift+U) — spelling, not a spy.\n"
            "Talk in a small window — just you and your twin."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("font-size: 15px; color: #3a2418;")
        col.addWidget(blurb)
        self.tips_check = QCheckBox("Show a tips card when Heirloom opens")
        apply_cream_palette(self.tips_check)
        self.tips_check.setStyleSheet(f"color: {INK}; background: transparent; font-size: 15px; font-weight: 700;")
        self.tips_check.setChecked(
            bool(config.load_settings().get("show_tips_on_start", True))
        )
        col.addWidget(self.tips_check)
        done = QLabel("You're set. Say hi to your twin.")
        done.setWordWrap(True)
        done.setStyleSheet("font-size: 14px; color: #5a3a28;")
        col.addWidget(done)
        col.addStretch(1)
        return page

    def _set_step(self, index: int) -> None:
        self._stop_mic_test()
        if index > self._index:
            if self._index == 2:
                self._save_mic()
            if self._index == 3:
                self._save_sound()
        self._index = max(0, min(4, index))
        self.stack.setCurrentIndex(self._index)
        self.step_lbl.setText(f"Step {self._index + 1} of 5")
        self.back_btn.setVisible(self._index > 0)
        self.next_btn.setText("Finish" if self._index == 4 else "Next")
        for i, dot in enumerate(self._dots):
            dot.setObjectName("dot_on" if i <= self._index else "dot_off")
            dot.style().unpolish(dot)
            dot.style().polish(dot)
        if self._index == 0:
            self._refresh_google()
        elif self._index == 2:
            self._fill_mics()
        elif self._index == 3:
            self._fill_speakers()

    def _next(self) -> None:
        if self._index >= 4:
            self._persist_and_close(skipped=False)
            return
        self._set_step(self._index + 1)

    def _skip(self) -> None:
        self._persist_and_close(skipped=True)

    def _persist_and_close(self, *, skipped: bool) -> None:
        self._stop_mic_test()
        s = config.load_settings()
        s["show_setup_wizard"] = False
        if self._index >= 2:
            self._write_mic(s)
        if self._index >= 3:
            self._write_sound(s)
        if self._index == 4 or not skipped:
            s["show_tips_on_start"] = bool(self.tips_check.isChecked())
        config.save_settings(s)
        self._finished = True
        self.sound_changed.emit()
        self.setup_done.emit()
        self.close()

    def _refresh_google(self) -> None:
        if config.is_paired():
            self.google_btn.setEnabled(False)
            self.google_note.setText("You're signed in. Next.")
        else:
            self.google_btn.setEnabled(not self._busy)

    def _start_google(self) -> None:
        if self._busy or config.is_paired():
            return
        self._busy = True
        self.google_btn.setEnabled(False)
        catcher, url, house = start_pair_flow()
        opened = open_browser(url)
        if opened:
            self.google_note.setText(
                "A Google page should have opened. Sign in there. "
                "Come back here when it says you're signed in. We never see that password."
            )
        else:
            self._busy = False
            self.google_btn.setEnabled(True)
            self.google_note.setText(
                "Couldn't open the browser. Copy this into Chrome or Edge:\n" + url
            )
            return
        api.run_async(lambda: finish_pair_flow(catcher, house), self._google_ok, self._google_err)

    def _google_ok(self, _data: object) -> None:
        self._busy = False
        self.google_btn.setEnabled(False)
        self.google_note.setText("This computer is signed in. Next.")
        self.signed_in.emit()

    def _google_err(self, msg: str) -> None:
        self._busy = False
        self.google_btn.setEnabled(True)
        self.google_note.setText(msg or "Couldn't sign in. Tap Sign in with Google again.")

    def _pick_face(self) -> None:
        if not config.is_paired():
            self.face_note.setText("Sign in first (go back one step), then pick a photo.")
            return
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "Pick a photo of your face",
            "",
            "Pictures (*.jpg *.jpeg *.png *.webp)",
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
        except OSError:
            self.face_note.setText("Couldn't read that photo. Try another.")
            return
        if not data:
            self.face_note.setText("That file was empty. Try another photo.")
            return
        pix = QPixmap(path)
        if not pix.isNull():
            self.face_preview.setPixmap(
                pix.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        filename, mime = _image_mime(path, data)
        self.face_note.setText("Sending your photo…")
        api.post_multipart_async(
            "/desktop/avatar-photo",
            files={"file": (filename, data, mime)},
            on_ok=self._face_ok,
            on_err=self._face_err,
        )

    def _face_ok(self, data: object) -> None:
        blob = data if isinstance(data, dict) else {}
        url = str(blob.get("avatar_source_url") or blob.get("serve_url") or "").strip()
        self.face_note.setText("That's you. The talking picture will use this.")
        if url:
            self.face_ready.emit(url)

    def _face_err(self, msg: str) -> None:
        self.face_note.setText(msg or "Couldn't save that photo. Try another.")

    def _open_house(self, path: str) -> None:
        house = house_url()
        if not path.startswith("/"):
            path = "/" + path
        opened = open_browser(house + path)
        if not opened:
            note = getattr(self, "face_note", None) if path.startswith("/avatar") else getattr(
                self, "voice_note", None
            )
            if note is not None:
                note.setText("Couldn't open the browser. Copy this:\n" + house + path)

    def _fill_mics(self) -> None:
        s = config.load_settings()
        _fill_device_combo(
            self.mic_combo,
            audio.list_input_devices(),
            str(s.get("mic_device") or ""),
            "The usual microphone",
        )

    def _fill_speakers(self) -> None:
        s = config.load_settings()
        _fill_device_combo(
            self.speaker_combo,
            audio.list_output_devices(),
            str(s.get("speaker_device") or ""),
            "The usual speakers",
        )

    def _write_mic(self, s: dict) -> None:
        mic = self.mic_combo.currentData()
        s["mic_device"] = mic if isinstance(mic, str) else ""

    def _write_sound(self, s: dict) -> None:
        speaker = self.speaker_combo.currentData()
        s["speaker_device"] = speaker if isinstance(speaker, str) else ""
        s["twin_playback_volume"] = max(0.05, self.volume_slider.value() / 100.0)

    def _save_mic(self) -> None:
        s = config.load_settings()
        self._write_mic(s)
        config.save_settings(s)

    def _save_sound(self) -> None:
        s = config.load_settings()
        self._write_sound(s)
        config.save_settings(s)
        self.sound_changed.emit()

    def _mic_test_start(self) -> None:
        if self._mic_rec.is_recording():
            return
        mic = self.mic_combo.currentData()
        name = mic if isinstance(mic, str) else ""
        self.voice_note.setText("Listening… this stays on this computer.")
        self._mic_rec.start(device=name)

    def _mic_test_stop(self) -> None:
        self._stop_mic_test()

    def _stop_mic_test(self) -> None:
        if self._mic_rec.is_recording():
            self._mic_rec.stop()
        self.mic_level.setValue(0)

    def _on_mic_level(self, level: float) -> None:
        self.mic_level.setValue(int(max(0.0, min(1.0, float(level))) * 100))

    def _on_mic_test_wav(self, wav: bytes) -> None:
        if wav:
            self.voice_note.setText("Heard you. That stayed on this computer.")
        else:
            self.voice_note.setText("Didn't catch that. Hold and talk a little longer.")

    def _on_mic_err(self, msg: str) -> None:
        self.voice_note.setText(msg or "Couldn't open the microphone.")

    def mousePressEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(ev)

    def closeEvent(self, ev) -> None:  # noqa: N802
        self._stop_mic_test()
        if not self._finished:
            self._finished = True
            s = config.load_settings()
            s["show_setup_wizard"] = False
            config.save_settings(s)
            self.setup_done.emit()
        super().closeEvent(ev)


class TipsWindow(QWidget):
    """Short how-to card. Can refuse to load the next time the app starts."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("tips_card")
        self.setWindowTitle("Tips")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.resize(460, 420)
        self.setStyleSheet(CREAM_QSS)
        self._drag_pos = None
        self._saved = False
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        card = QWidget()
        card.setObjectName("card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        apply_cream_palette(card)
        root.addWidget(card, 1)
        col = QVBoxLayout(card)
        col.setContentsMargins(28, 22, 28, 20)
        col.setSpacing(12)
        top = QHBoxLayout()
        title = QLabel("Tips")
        title.setStyleSheet("font-size: 24px; font-weight: 700; color: #3a2418;")
        top.addWidget(title, 1)
        close = QPushButton("×")
        close.setFixedSize(32, 32)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(lambda _checked=False: self.close())
        top.addWidget(close)
        col.addLayout(top)
        body = QLabel(
            "Hold to speak — press Ctrl+Space, or the hold button.\n\n"
            "Look at my screen — the twin peeks at this computer, then the picture is deleted.\n\n"
            "Unbound Keyboard (Ctrl+Shift+U) — spelling and overused words, not a spy.\n\n"
            "Talk in a small window — just you and your twin.\n\n"
            "Your face and voice live in the first-run setup. Open it any time from the menu."
        )
        body.setWordWrap(True)
        body.setStyleSheet("font-size: 15px; color: #3a2418;")
        col.addWidget(body)
        self.show_check = QCheckBox("Show tips when Heirloom opens")
        apply_cream_palette(self.show_check)
        self.show_check.setStyleSheet(
            f"color: {INK}; background: transparent; font-size: 15px; font-weight: 700;"
        )
        self.show_check.setChecked(bool(config.load_settings().get("show_tips_on_start", True)))
        col.addWidget(self.show_check)
        col.addStretch(1)
        dont = QPushButton("Don't show this next time")
        dont.setCursor(Qt.PointingHandCursor)
        dont.clicked.connect(lambda _checked=False: self._dont_show_again())
        col.addWidget(dont)
        got = QPushButton("Got it")
        got.setObjectName("primary")
        got.setCursor(Qt.PointingHandCursor)
        got.clicked.connect(lambda _checked=False: self._got_it())
        col.addWidget(got)

    def _save_pref(self, show: bool) -> None:
        s = config.load_settings()
        s["show_tips_on_start"] = bool(show)
        config.save_settings(s)
        self._saved = True

    def _dont_show_again(self) -> None:
        self.show_check.setChecked(False)
        self._save_pref(False)
        self.close()

    def _got_it(self) -> None:
        self._save_pref(bool(self.show_check.isChecked()))
        self.close()

    def closeEvent(self, ev) -> None:  # noqa: N802
        if not self._saved:
            self._save_pref(bool(self.show_check.isChecked()))
        super().closeEvent(ev)

    def mousePressEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(ev)
