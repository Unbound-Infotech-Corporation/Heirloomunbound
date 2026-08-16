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
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from .. import api, config
from ..commands import _looks_secret_writing, clipboard_get, clipboard_set, paste_keys
from ..google_signin import finish_pair_flow, open_browser, start_pair_flow
from ..writing_local import proofread_local

# Cream card of its own. The rest of the desktop app uses a dark theme
# (pale text on glass). That theme makes chips and buttons vanish here.
WRITING_QSS = """
    QWidget { color: #3a2418; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
    QLabel { color: #3a2418; background: transparent; }
    QPushButton {
        color: #3a2418;
        background: #fffdf6;
        border: 3px solid #3a2418;
        border-radius: 12px;
        padding: 8px 12px;
        font-weight: 800;
        min-height: 28px;
    }
    QPushButton:hover { background: #fff3c4; }
    QPushButton:pressed { background: #f0c040; }
    QPushButton:disabled { color: #8a7060; background: #f3ead8; border-color: #c4b49a; }
    QPushButton#chip {
        background: #f0c040;
        color: #3a2418;
        border: 3px solid #3a2418;
        border-radius: 18px;
        padding: 6px 14px;
        font-weight: 800;
        min-height: 26px;
    }
    QPushButton#chip:hover { background: #ffd95a; }
    QPushButton#primary {
        background: #c45c38;
        color: #fff8e4;
        border: 3px solid #3a2418;
    }
    QPushButton#primary:hover { background: #a94c2e; color: #fff8e4; }
    QPlainTextEdit, QLineEdit {
        background: #fff8e4;
        color: #3a2418;
        border: 3px solid #3a2418;
        border-radius: 12px;
        padding: 8px;
        selection-background-color: #f0c040;
        selection-color: #3a2418;
    }
    QScrollArea { background: transparent; border: none; }
"""

CHIP_STYLE = (
    "QPushButton { background: #f0c040; color: #3a2418; border: 3px solid #3a2418;"
    " border-radius: 18px; padding: 6px 14px; font-weight: 800; }"
    "QPushButton:hover { background: #ffd95a; }"
)


def _house_is_paired() -> bool:
    """True when this copy was downloaded from Local PC with a house token."""
    token = (config.DEVICE_TOKEN or "").strip()
    return bool(token) and not token.startswith("__")


def _house_url_is_ready() -> bool:
    url = (config.BACKEND_URL or "").strip()
    return url.startswith("http") and "localhost" not in url and not url.startswith("__")


def _login_error_text(msg: str) -> str:
    """Plain talk when the live website cannot send a slip yet."""
    blob = (msg or "").lower()
    if any(s in blob for s in ("404", "not found", "405")):
        return (
            "The Heirloom website this copy reached cannot send a sign-in note yet. "
            "Nothing was put in your mail. Spelling still works here without signing in."
        )
    if any(
        s in blob
        for s in (
            "connection",
            "refused",
            "timed out",
            "timeout",
            "localhost",
            "failed to establish",
            "max retries",
            "newconnectionerror",
            "nameresolution",
            "not known",
        )
    ):
        return (
            "This copy could not reach Heirloom, so no slip was sent. "
            "Paste the Heirloom page from your browser (https://…), then tap Send a sign-in note again. "
            "Or skip sign-in — spelling still works."
        )
    if "503" in blob or "couldn't send the note" in blob:
        return (
            "Couldn't send the note. Check spam in a minute, or skip sign-in — spelling still works."
        )
    return (msg or "Couldn't send the note.") + " Spelling still works without signing in."


class WritingWindow(QWidget):
    """Movable cream card for Unbound Keyboard on Windows. Not a keylogger."""

    closed = Signal()
    signed_in = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("writing_window")
        self.setWindowTitle("Unbound Keyboard")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(WRITING_QSS)
        self.resize(420, 620)
        self.setMinimumSize(340, 420)

        self._drag_pos = None
        self._pin_front = False
        self._busy = False
        self._issues: list[dict[str, Any]] = []
        self._ignored: set[str] = set()
        self._last_corrected = ""
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
            "QWidget#card QLabel { color: #3a2418; background: transparent; }"
            "QWidget#card QPlainTextEdit, QWidget#card QLineEdit {"
            " background: #fff8e4; color: #3a2418;"
            " border: 4px solid #3a2418; border-radius: 18px; padding: 8px;"
            " selection-background-color: #f0c040; selection-color: #3a2418; }"
            "QWidget#card QPushButton {"
            " background: #fffdf6; color: #3a2418; border: 3px solid #3a2418;"
            " border-radius: 12px; padding: 8px 10px; font-weight: 800; }"
            "QWidget#card QPushButton:hover { background: #fff3c4; }"
            "QWidget#card QPushButton:disabled { color: #8a7060; background: #f3ead8;"
            " border-color: #c4b49a; }"
            "QWidget#card QPushButton#chip {"
            " background: #f0c040; color: #3a2418; border: 3px solid #3a2418;"
            " border-radius: 18px; padding: 6px 14px; }"
            "QWidget#card QPushButton#chip:hover { background: #ffd95a; }"
            "QWidget#card QPushButton#primary {"
            " background: #c45c38; color: #fff8e4; border: 3px solid #3a2418; }"
            "QWidget#card QPushButton#primary:hover { background: #a94c2e; color: #fff8e4; }"
        )
        root.addWidget(card, 1)
        col = QVBoxLayout(card)
        col.setContentsMargins(16, 10, 16, 12)
        col.setSpacing(8)

        col.addWidget(self._build_titlebar())
        kicker = QLabel("Unbound Keyboard  ·  drag the top bar to move")
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
        col.addWidget(self._build_sign_in())

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
        self.btn_fix = QPushButton("Fix spelling")
        self.btn_fix.setObjectName("primary")
        self.btn_fix.clicked.connect(self._fix_spelling)
        self.btn_leave = QPushButton("Leave it")
        self.btn_leave.clicked.connect(self._leave_it)
        self.btn_polish = QPushButton("Make it sound like me")
        self.btn_polish.setObjectName("primary")
        self.btn_polish.clicked.connect(self._polish)
        row.addWidget(self.btn_check)
        row.addWidget(self.btn_fix)
        row.addWidget(self.btn_leave)
        row.addWidget(self.btn_polish)
        col.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_clip = QPushButton("Use clipboard")
        self.btn_clip.clicked.connect(self._from_clipboard)
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.clicked.connect(self._copy)
        self.btn_paste = QPushButton("Put this where I was typing")
        self.btn_paste.setObjectName("primary")
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
        bar.setCursor(Qt.SizeAllCursor)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Unbound Keyboard  ·  drag here")
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.btn_pin = QPushButton("Stay in front")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setCursor(Qt.ArrowCursor)
        self.btn_pin.clicked.connect(self._toggle_pin)
        close = QPushButton("×")
        close.setFixedSize(28, 28)
        close.setCursor(Qt.ArrowCursor)
        close.clicked.connect(self.close)
        row.addWidget(title)
        row.addStretch(1)
        row.addWidget(self.btn_pin)
        row.addWidget(close)
        bar.mousePressEvent = self._bar_press  # type: ignore[method-assign]
        bar.mouseMoveEvent = self._bar_move  # type: ignore[method-assign]
        bar.mouseReleaseEvent = self._bar_release  # type: ignore[method-assign]
        return bar

    def _build_sign_in(self) -> QWidget:
        box = QWidget()
        box.setObjectName("signin")
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 8)
        col.setSpacing(6)
        hint = QLabel(
            "This copy isn’t signed in. Tap Sign in with Google — "
            "Heirloom never sees that password. Then this computer can talk to your twin. "
            "A slip is a short Heirloom email after you tap "
            "Send a sign-in note — look for “Your Unbound Keyboard sign-in slip”. "
            "It starts with ml_. Check spam. If nothing arrives, the website could not "
            "send it. Skip sign-in and keep writing; spelling still works. "
            "We never ask for a Google or Windows password. "
            "The website box is the Heirloom page in your browser (https://…) — "
            "not a street address."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 12px; color: #5a3a28;")
        col.addWidget(hint)
        self.btn_google = QPushButton("Sign in with Google")
        self.btn_google.setObjectName("primary")
        self.btn_google.clicked.connect(lambda _checked=False: self._google_sign_in())
        col.addWidget(self.btn_google)
        self.email_in = QLineEdit()
        self.email_in.setPlaceholderText("Your email")
        col.addWidget(self.email_in)
        self.house_in = QLineEdit()
        self.house_in.setPlaceholderText("Heirloom website (https://…) — not a street address")
        url = (config.BACKEND_URL or "").strip()
        if url and "localhost" not in url and not url.startswith("__"):
            self.house_in.setText(url)
            self.house_in.hide()
        col.addWidget(self.house_in)
        self.btn_send_login = QPushButton("Send a sign-in note")
        self.btn_send_login.clicked.connect(self._send_sign_in)
        col.addWidget(self.btn_send_login)
        self.code_in = QLineEdit()
        self.code_in.setPlaceholderText("Paste the slip from your mail")
        col.addWidget(self.code_in)
        self.btn_finish_login = QPushButton("Sign in")
        self.btn_finish_login.setObjectName("primary")
        self.btn_finish_login.clicked.connect(self._finish_sign_in)
        col.addWidget(self.btn_finish_login)
        self._sign_in_box = box
        box.setVisible(not _house_is_paired())
        return box

    def _toggle_pin(self, checked: bool) -> None:
        self._pin_front = bool(checked)
        flags = Qt.Window | Qt.FramelessWindowHint
        if self._pin_front:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.btn_pin.setText("In front" if self._pin_front else "Stay in front")

    def _bar_press(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _bar_move(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def _bar_release(self, event) -> None:  # noqa: N802
        self._drag_pos = None
        event.accept()

    def _google_sign_in(self) -> None:
        self._apply_house_url()
        self._set_busy(True)
        catcher, url, house = start_pair_flow(config.BACKEND_URL)
        opened = open_browser(url)
        if opened:
            self.note.setText(
                "A Google page should have opened. Sign in there. We never see that password."
            )
        else:
            self.note.setText("Couldn’t open the browser. Paste this into Chrome or Edge:\n" + url)
        api.run_async(
            lambda: finish_pair_flow(catcher, house),
            lambda data: self._on_signed_in(data if isinstance(data, dict) else {}),
            self._on_login_err,
        )

    def _apply_house_url(self) -> None:
        typed = (self.house_in.text() or "").strip().rstrip("/")
        if typed.startswith("http"):
            config.BACKEND_URL = typed

    def _send_sign_in(self) -> None:
        self._apply_house_url()
        email = (self.email_in.text() or "").strip()
        if "@" not in email:
            self.note.setText("Type the email you use for Heirloom.")
            return
        if not _house_url_is_ready():
            self.note.setText(
                "Paste the Heirloom website from your browser first (https://…). "
                "If you don’t have that, skip sign-in — spelling still works here. "
                "No slip is sitting in your mail until the website can send one."
            )
            return
        self._set_busy(True)
        api.post_async(
            "/auth/desktop-login",
            {"email": email},
            on_ok=lambda data: self._on_send_ok(data if isinstance(data, dict) else {}),
            on_err=lambda msg: self._on_login_err(msg),
        )

    def _on_send_ok(self, data: dict) -> None:
        self._set_busy(False)
        self.note.setText(str(data.get("note") or "Check your mail. Paste the slip below."))
        self.code_in.setFocus()

    def _finish_sign_in(self) -> None:
        self._apply_house_url()
        code = (self.code_in.text() or "").strip()
        if "ml_" not in code:
            self.note.setText("Paste the whole slip from your mail. It starts with ml_.")
            return
        self._set_busy(True)
        api.post_async(
            "/auth/desktop-login/finish",
            {"code": code},
            on_ok=lambda data: self._on_signed_in(data if isinstance(data, dict) else {}),
            on_err=lambda msg: self._on_login_err(msg),
        )

    def _on_signed_in(self, data: dict) -> None:
        self._set_busy(False)
        token = str(data.get("device_token") or "").strip()
        house = str(data.get("house_url") or "").strip() or (self.house_in.text() or "").strip()
        if not token:
            self.note.setText("That slip didn’t pair this computer. Send a new note.")
            return
        config.persist_login(token, house)
        self._sign_in_box.setVisible(False)
        self.note.setText(str(data.get("note") or "This computer is signed in."))
        self.code_in.clear()
        self.signed_in.emit()

    def _on_login_err(self, msg: str) -> None:
        self._set_busy(False)
        self.note.setText(_login_error_text(msg))

    def mousePressEvent(self, event):  # noqa: N802
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)

    def _on_text(self) -> None:
        if not self._text().strip():
            self._ignored.clear()
        self._debounce.start()

    def _text(self) -> str:
        return self.editor.toPlainText()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_check.setEnabled(not busy)
        self.btn_fix.setEnabled(not busy)
        self.btn_leave.setEnabled(not busy)
        self.btn_polish.setEnabled(not busy)
        if hasattr(self, "btn_send_login"):
            self.btn_send_login.setEnabled(not busy)
            self.btn_finish_login.setEnabled(not busy)
        if hasattr(self, "btn_google"):
            self.btn_google.setEnabled(not busy)

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

    def _issue_key(self, issue: dict[str, Any]) -> str:
        return f"{issue.get('kind') or ''}:{str(issue.get('text') or '').lower()}"

    def _render_issues(self, issues: list[dict[str, Any]]) -> None:
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._issues = [i for i in (issues or []) if self._issue_key(i) not in self._ignored]
        for idx, issue in enumerate(self._issues[:8]):
            raw = str(issue.get("text") or "fix")
            sug = (issue.get("suggestions") or [None])[0]
            label = f"{raw} → {sug}" if sug else raw
            btn = QPushButton(label[:28])
            btn.setObjectName("chip")
            btn.setStyleSheet(CHIP_STYLE)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(str(issue.get("note") or label))
            btn.clicked.connect(lambda _=False, i=idx: self._apply_issue(i))
            self.chips_layout.addWidget(btn)
        self.chips_layout.addStretch(1)

    def _fix_spelling(self) -> None:
        if not self._last_corrected:
            return
        self.editor.setPlainText(self._last_corrected)
        self._render_issues([])
        self.note.setText("Looks clean. Keep going.")

    def _leave_it(self) -> None:
        for issue in self._issues:
            self._ignored.add(self._issue_key(issue))
        self._render_issues([])
        self.note.setText("Okay — I won't nag about those.")

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
            self._last_corrected = ""
            self._render_issues([])
            return
        self.note.setText(str(body.get("style_note") or "Looks clean. Keep going."))
        self._last_corrected = str(body.get("corrected") or "")
        self._render_issues(list(body.get("issues") or []))

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
            self._last_corrected = polished
        self.note.setText(str(body.get("note") or "Rewritten so it still sounds like you."))
        self._render_issues(list(body.get("issues") or []))

    def _on_err(self, msg: str) -> None:
        self._set_busy(False)
        self.note.setText(msg or "Couldn't reach the house.")
