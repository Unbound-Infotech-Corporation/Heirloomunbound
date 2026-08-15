"""Unbound Keyboard for Windows — a writing helper, not a keylogger.

Android can be a real system keyboard. Windows cannot sit inside every box
without watching every key, so this window is honest: type or paste here,
we mark spelling / grammar / overused words, then you can put the cleaned
words back where you were writing.

We never ask for a Windows password. We never read password boxes.
"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from .. import api, config
from ..commands import _looks_secret_writing, clipboard_get, clipboard_set, paste_keys
from ..writing_local import proofread_local
from . import QSS


def _house_is_paired() -> bool:
    """True when this copy was downloaded from Local PC with a house token."""
    token = (config.DEVICE_TOKEN or "").strip()
    return bool(token) and not token.startswith("__")


class WritingWindow(QWidget):
    """Always-on-top cream card for Unbound Keyboard on Windows."""

    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("writing_window")
        self.setWindowTitle("Unbound Keyboard")
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(QSS)
        self.resize(420, 560)
        self.setMinimumSize(340, 420)

        self._drag_pos = None
        self._busy = False
        self._issues: list[dict[str, Any]] = []
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(700)
        self._debounce.timeout.connect(self._check_writing)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        card = QWidget()
        card.setObjectName("card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            "QWidget#card { background: #f4e8c8; border-radius: 28px;"
            " border: 5px solid #c45c38; }"
            "QWidget#card QLabel { color: #3a2418; }"
            "QWidget#card QPlainTextEdit { background: #fff8e4; color: #3a2418;"
            " border: 4px solid #3a2418; border-radius: 18px; padding: 8px; }"
        )
        root.addWidget(card, 1)
        col = QVBoxLayout(card)
        col.setContentsMargins(16, 10, 16, 12)
        col.setSpacing(8)

        col.addWidget(self._build_titlebar())
        kicker = QLabel("Unbound Keyboard")
        kicker.setStyleSheet("font-size: 11px; letter-spacing: 0.12em; color: #8a5a3a;")
        col.addWidget(kicker)
        title = QLabel("Write here. We'll catch the slips.")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #3a2418;")
        col.addWidget(title)
        blurb = QLabel(
            "We only see what you type or paste here — not every key on the computer. "
            "Never a password box. Never a Windows password."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("font-size: 12px; color: #5a3a28;")
        col.addWidget(blurb)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Type or paste the words you want help with…")
        self.editor.textChanged.connect(self._on_text)
        col.addWidget(self.editor, 1)

        self.note = QLabel("Looks clean. Keep going.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("font-size: 12px; color: #5a3a28;")
        col.addWidget(self.note)

        self.chips = QWidget()
        self.chips_layout = QHBoxLayout(self.chips)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedHeight(48)
        scroll.setWidget(self.chips)
        col.addWidget(scroll)

        row = QHBoxLayout()
        self.btn_check = QPushButton("Check writing")
        self.btn_check.clicked.connect(self._check_writing)
        self.btn_polish = QPushButton("Make it sound like me")
        self.btn_polish.clicked.connect(self._polish)
        row.addWidget(self.btn_check)
        row.addWidget(self.btn_polish)
        col.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_clip = QPushButton("Use clipboard")
        self.btn_clip.clicked.connect(self._from_clipboard)
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.clicked.connect(self._copy)
        self.btn_paste = QPushButton("Put this where I was typing")
        self.btn_paste.clicked.connect(self._paste_back)
        row2.addWidget(self.btn_clip)
        row2.addWidget(self.btn_copy)
        col.addLayout(row2)
        col.addWidget(self.btn_paste)

        grip_row = QHBoxLayout()
        grip_row.addStretch(1)
        grip_row.addWidget(QSizeGrip(card))
        col.addLayout(grip_row)

    def _build_titlebar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Unbound Keyboard")
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        close = QPushButton("×")
        close.setFixedSize(28, 28)
        close.clicked.connect(self.close)
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(close)
        return bar

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)

    def _on_text(self) -> None:
        self._debounce.start()

    def _text(self) -> str:
        return self.editor.toPlainText()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_check.setEnabled(not busy)
        self.btn_polish.setEnabled(not busy)

    def _from_clipboard(self) -> None:
        status, out = clipboard_get()
        if status != "ok":
            self.note.setText("Couldn't read the clipboard.")
            return
        if _looks_secret_writing(out):
            self.note.setText("That looks private. I will not read a password or a card number.")
            return
        self.editor.setPlainText(out or "")

    def _copy(self) -> None:
        clipboard_set(self._text())
        self.note.setText("Copied.")

    def _paste_back(self) -> None:
        text = self._text()
        if _looks_secret_writing(text):
            self.note.setText("That looks private. I will not paste a password or a card number.")
            return
        clipboard_set(text)
        self.hide()
        QTimer.singleShot(180, self._do_paste)

    def _do_paste(self) -> None:
        paste_keys()
        self.note.setText("Put the words where you were typing.")
        self.show()
        self.raise_()

    def _render_issues(self, issues: list[dict[str, Any]]) -> None:
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._issues = issues or []
        for idx, issue in enumerate(self._issues[:8]):
            label = str(issue.get("text") or "fix")
            btn = QPushButton(label[:24])
            btn.setToolTip(str(issue.get("note") or ""))
            btn.clicked.connect(lambda _=False, i=idx: self._apply_issue(i))
            self.chips_layout.addWidget(btn)
        self.chips_layout.addStretch(1)

    def _apply_issue(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._issues):
            return
        issue = self._issues[idx]
        suggestions = issue.get("suggestions") or []
        if not suggestions:
            return
        start = int(issue.get("start") or 0)
        end = int(issue.get("end") or 0)
        blob = self._text()
        if start < 0 or end > len(blob) or start > end:
            return
        self.editor.setPlainText(blob[:start] + str(suggestions[0]) + blob[end:])

    def _check_writing(self) -> None:
        text = self._text()
        if not text.strip() or self._busy:
            return
        if _looks_secret_writing(text):
            self.note.setText("That looks private. I will not read it.")
            self._render_issues([])
            return
        if not _house_is_paired():
            self._on_proofread(proofread_local(text))
            return
        self._set_busy(True)
        api.post_async(
            "/writing/proofread",
            {"text": text},
            on_ok=self._on_proofread,
            on_err=lambda _msg: self._on_proofread(proofread_local(text)),
        )

    def _on_proofread(self, data: object) -> None:
        self._set_busy(False)
        body = data if isinstance(data, dict) else {}
        if body.get("secret"):
            self.note.setText(str(body.get("style_note") or "That looks private. I will not read it."))
            self._render_issues([])
            return
        self.note.setText(str(body.get("style_note") or "Looks clean. Keep going."))
        self._render_issues(list(body.get("issues") or []))
        corrected = str(body.get("corrected") or "")
        if corrected and corrected != self._text() and any(
            i.get("kind") in ("spelling", "grammar") for i in (body.get("issues") or [])
        ):
            # Keep their buffer; chips offer the fix. Auto-fill only if they asked Check.
            pass

    def _polish(self) -> None:
        text = self._text()
        if not text.strip() or self._busy:
            return
        if _looks_secret_writing(text):
            self.note.setText("That looks private. I will not rewrite it.")
            return
        if not _house_is_paired():
            local = proofread_local(text)
            self._on_polish(
                {
                    "secret": local.get("secret"),
                    "polished": local.get("corrected") or text,
                    "note": (
                        "Spelling is cleaned here. Pair this computer from Local PC "
                        "to make it sound like you."
                    ),
                    "issues": local.get("issues") or [],
                }
            )
            return
        self._set_busy(True)
        api.post_async(
            "/writing/polish",
            {"text": text},
            on_ok=self._on_polish,
            on_err=lambda _msg: self._on_polish(
                {
                    "secret": False,
                    "polished": proofread_local(text).get("corrected") or text,
                    "note": "Couldn't reach the house, so I cleaned spelling here.",
                    "issues": proofread_local(text).get("issues") or [],
                }
            ),
        )

    def _on_polish(self, data: object) -> None:
        self._set_busy(False)
        body = data if isinstance(data, dict) else {}
        if body.get("secret"):
            self.note.setText(str(body.get("note") or "That looks private."))
            return
        polished = str(body.get("polished") or "")
        if polished:
            self.editor.setPlainText(polished)
        self.note.setText(str(body.get("note") or "Rewritten so it still sounds like you."))
        self._render_issues(list(body.get("issues") or []))

    def _on_err(self, msg: str) -> None:
        self._set_busy(False)
        self.note.setText(msg or "Couldn't reach the house.")
