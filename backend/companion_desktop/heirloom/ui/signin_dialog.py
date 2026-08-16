"""Cream sign-in card on the full Heirloom window.

Continue with Google in the browser. We never see that password.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from .. import api, config
from ..google_signin import pair_this_computer


class SignInDialog(QWidget):
    """Dim overlay with a cream card. Lives on the big Heirloom window."""

    signed_in = Signal()
    want_keyboard = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("signin_scrim")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#signin_scrim { background: rgba(18, 17, 16, 200); }"
            "QWidget#signin_card { background: #f4e8c8; border: 5px solid #c45c38;"
            " border-radius: 28px; }"
            "QWidget#signin_card QLabel { color: #3a2418; background: transparent; }"
            "QWidget#signin_card QPushButton { background: #fffdf6; color: #3a2418;"
            " border: 3px solid #3a2418; border-radius: 14px; padding: 12px 16px;"
            " font-weight: 800; }"
            "QWidget#signin_card QPushButton:hover { background: #fff3c4; }"
            "QWidget#signin_card QPushButton:disabled { color: #8a7060;"
            " background: #f3ead8; border-color: #c4b49a; }"
            "QWidget#signin_card QPushButton#primary { background: #c45c38;"
            " color: #fff8e4; }"
            "QWidget#signin_card QPushButton#primary:hover { background: #a94c2e;"
            " color: #fff8e4; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 48, 24, 24)
        outer.addStretch(1)

        card = QWidget()
        card.setObjectName("signin_card")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setMaximumWidth(480)
        col = QVBoxLayout(card)
        col.setContentsMargins(28, 24, 28, 24)
        col.setSpacing(12)
        title = QLabel("Sign in to use the whole house")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #3a2418;")
        col.addWidget(title)
        blurb = QLabel(
            "This is the full Heirloom app — your twin, look at the screen, mail, "
            "and Unbound Keyboard. Tap Continue with Google. A browser opens. "
            "Sign in there. Heirloom never sees that password."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("font-size: 13px; color: #5a3a28;")
        col.addWidget(blurb)
        self.note = QLabel("Tap the button. A browser window should open.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("font-size: 12px; color: #5a3a28;")
        col.addWidget(self.note)
        self.btn = QPushButton("Continue with Google")
        self.btn.setObjectName("primary")
        self.btn.clicked.connect(self._google)
        col.addWidget(self.btn)
        self.btn_spell = QPushButton("Just fix spelling for now")
        self.btn_spell.clicked.connect(self.want_keyboard.emit)
        col.addWidget(self.btn_spell)

        outer.addWidget(card, 0, Qt.AlignHCenter)
        outer.addStretch(1)

    def _google(self) -> None:
        self.btn.setEnabled(False)
        self.note.setText(
            "A browser should open. Sign in with Google there. Come back here when it says you’re signed in."
        )
        api.run_async(lambda: pair_this_computer(config.BACKEND_URL), self._ok, self._err)

    def _ok(self, _data: object) -> None:
        self.btn.setEnabled(True)
        self.note.setText("This computer is signed in. Talk to your twin in this window.")
        self.signed_in.emit()

    def _err(self, msg: str) -> None:
        self.btn.setEnabled(True)
        self.note.setText(msg or "Couldn't sign in. Tap Continue with Google again.")
