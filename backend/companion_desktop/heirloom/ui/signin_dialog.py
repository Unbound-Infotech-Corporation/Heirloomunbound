"""Cream sign-in card — one click Sign in with Google.

Opens Google in the browser. We never see that password.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import api
from ..google_signin import finish_pair_flow, open_browser, start_pair_flow


class SignInDialog(QWidget):
    """Cream window with a big Sign in with Google button."""

    signed_in = Signal()
    want_keyboard = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("signin_card")
        self.setWindowTitle("Sign in with Google")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.resize(460, 340)
        self._busy = False
        self.setStyleSheet(
            "QWidget#signin_card { background: #f4e8c8; border: 5px solid #c45c38;"
            " border-radius: 28px; }"
            "QWidget#signin_card QLabel { color: #3a2418; background: transparent; }"
            "QWidget#signin_card QPushButton { background: #fffdf6; color: #3a2418;"
            " border: 3px solid #3a2418; border-radius: 14px; padding: 14px 16px;"
            " font-weight: 800; font-size: 16px; }"
            "QWidget#signin_card QPushButton:hover { background: #fff3c4; }"
            "QWidget#signin_card QPushButton:disabled { color: #8a7060;"
            " background: #f3ead8; border-color: #c4b49a; }"
            "QWidget#signin_card QPushButton#primary { background: #c45c38;"
            " color: #fff8e4; font-size: 18px; min-height: 52px; }"
            "QWidget#signin_card QPushButton#primary:hover { background: #a94c2e;"
            " color: #fff8e4; }"
        )
        col = QVBoxLayout(self)
        col.setContentsMargins(28, 24, 28, 24)
        col.setSpacing(12)
        top = QHBoxLayout()
        title = QLabel("Sign in with Google")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 24px; font-weight: 700; color: #3a2418;")
        top.addWidget(title, 1)
        close = QPushButton("×")
        close.setFixedSize(32, 32)
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(lambda _checked=False: self.close())
        top.addWidget(close)
        col.addLayout(top)
        blurb = QLabel(
            "Tap the button. A Google page opens in your browser. "
            "Sign in there. Then this computer can use the whole house — "
            "your twin, look at the screen, mail, and Unbound Keyboard. "
            "Heirloom never sees that password."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("font-size: 13px; color: #5a3a28;")
        col.addWidget(blurb)
        self.note = QLabel("Tap Sign in with Google.")
        self.note.setWordWrap(True)
        self.note.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.note.setStyleSheet("font-size: 12px; color: #5a3a28;")
        col.addWidget(self.note)
        self.btn = QPushButton("Sign in with Google")
        self.btn.setObjectName("primary")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setDefault(True)
        self.btn.clicked.connect(lambda _checked=False: self.start_google())
        col.addWidget(self.btn)
        self.btn_spell = QPushButton("Just fix spelling for now")
        self.btn_spell.setCursor(Qt.PointingHandCursor)
        self.btn_spell.clicked.connect(lambda _checked=False: self.want_keyboard.emit())
        col.addWidget(self.btn_spell)

    def start_google(self) -> None:
        """One click: open Google, then pair this computer."""
        if self._busy:
            return
        self._busy = True
        self.btn.setEnabled(False)
        catcher, url, house = start_pair_flow()
        opened = open_browser(url)
        if opened:
            self.note.setText(
                "A Google page should have opened. Sign in there. "
                "Come back here when it says you’re signed in. We never see that password."
            )
        else:
            self._busy = False
            self.btn.setEnabled(True)
            self.note.setText(
                "Couldn’t open the browser. Copy this into Chrome or Edge:\n" + url
            )
        api.run_async(lambda: finish_pair_flow(catcher, house), self._ok, self._err)

    def closeEvent(self, ev) -> None:  # noqa: N802
        self._busy = False
        self.btn.setEnabled(True)
        super().closeEvent(ev)

    def _ok(self, _data: object) -> None:
        self._busy = False
        self.btn.setEnabled(True)
        self.note.setText("This computer is signed in. Talk to your twin in the big window.")
        self.signed_in.emit()

    def _err(self, msg: str) -> None:
        self._busy = False
        self.btn.setEnabled(True)
        self.note.setText(msg or "Couldn't sign in. Tap Sign in with Google again.")
