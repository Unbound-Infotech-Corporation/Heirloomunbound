"""Stay-on-top vendor sign-up coach for first-run setup.

Opens official vendor pages (sign-up, inbox, API keys) and pauses with
copy/paste instructions. The human clicks Create account / I'm not a robot
/ Verify. Heirloom never drives vendor DOM or solves captchas.
"""
from __future__ import annotations

import webbrowser
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import api
from . import PALETTE, QSS


class VendorCoachWindow(QDialog):
    def __init__(
        self,
        handoffs: list[dict],
        email: str = "",
        parent: Optional[QWidget] = None,
        on_saved: Optional[Callable[[], None]] = None,
    ):
        super().__init__(parent)
        self.setStyleSheet(QSS)
        self.setWindowTitle("Heirloom · Vendor guide")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setModal(False)
        self.resize(400, 460)
        self._queue = [h for h in (handoffs or []) if h and not h.get("already_saved")]
        self._email = (email or "").strip().lower()
        self._on_saved = on_saved
        self._svc_idx = 0
        self._step_idx = 0
        self._opened = ""
        self._build()
        self._render()
        geo = self.screen().availableGeometry() if self.screen() else None
        if geo is not None:
            self.move(geo.right() - self.width() - 28, geo.bottom() - self.height() - 48)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        self._over = QLabel("")
        self._over.setProperty("class", "overline")
        self._title = QLabel("")
        self._title.setObjectName("brand")
        self._title.setWordWrap(True)
        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setStyleSheet(f"color: {PALETTE['text_secondary']}; font-size: 13px;")
        self._bullets = QLabel("")
        self._bullets.setWordWrap(True)
        self._bullets.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 12px;")
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.Password)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._primary = QPushButton("Continue")
        self._primary.setObjectName("primary")
        self._primary.clicked.connect(self._on_primary)
        self._reopen = QPushButton("Re-open page")
        self._reopen.clicked.connect(self._reopen_page)
        self._skip = QPushButton("Skip — already verified")
        self._skip.clicked.connect(self._advance)
        row = QHBoxLayout()
        row.addWidget(self._reopen)
        row.addWidget(self._skip)
        root.addWidget(self._over)
        root.addWidget(self._title)
        root.addWidget(self._body)
        root.addWidget(self._bullets)
        root.addWidget(self._key)
        root.addWidget(self._status)
        root.addWidget(self._primary)
        root.addLayout(row)

    def _svc(self) -> Optional[dict]:
        if 0 <= self._svc_idx < len(self._queue):
            return self._queue[self._svc_idx]
        return None

    def _step(self) -> Optional[dict]:
        svc = self._svc()
        steps = (svc or {}).get("coach_steps") or []
        if 0 <= self._step_idx < len(steps):
            return steps[self._step_idx]
        return None

    def _render(self) -> None:
        if not self._queue:
            self._over.setText("CLOUD KEYS")
            self._title.setText("All vendor keys are saved")
            self._body.setText("Local Whisper and Ollama do not need these.")
            self._bullets.hide()
            self._key.hide()
            self._primary.setText("Close guide")
            self._reopen.hide()
            self._skip.hide()
            return
        svc = self._svc()
        step = self._step()
        if not svc or not step:
            self.accept()
            return
        n_svc = len(self._queue)
        n_step = len(svc.get("coach_steps") or [])
        self._over.setText(
            f"{svc.get('label')} · {self._svc_idx + 1} of {n_svc} · "
            f"step {self._step_idx + 1} of {n_step}"
        )
        self._title.setText(step.get("title") or "")
        self._body.setText(step.get("body") or "")
        bullets = step.get("bullets") or []
        self._bullets.setText("\n".join(f"• {b}" for b in bullets))
        self._bullets.setVisible(bool(bullets))
        paste = step.get("kind") == "paste"
        self._key.setVisible(paste)
        self._key.setPlaceholderText(step.get("placeholder") or "")
        self._primary.setText(step.get("cta") or "Continue")
        self._reopen.setVisible(bool(step.get("open_url")))
        self._skip.setVisible(bool(step.get("skip_cta")))
        self._skip.setText(step.get("skip_cta") or "Skip")
        self._status.setText("")
        self._maybe_open(svc, step)

    def _maybe_open(self, svc: dict, step: dict) -> None:
        key = f"{svc.get('id')}:{step.get('id')}"
        if self._opened == key:
            return
        self._opened = key
        copy = step.get("copy") or self._email
        if copy:
            QApplication.clipboard().setText(copy)
        url = step.get("open_url")
        if step.get("auto_open") and url:
            webbrowser.open(url)

    def _reopen_page(self) -> None:
        step = self._step()
        url = (step or {}).get("open_url")
        if url:
            webbrowser.open(url)

    def _on_primary(self) -> None:
        if not self._queue:
            self.accept()
            return
        step = self._step()
        if (step or {}).get("kind") == "paste":
            self._save_key()
            return
        self._advance()

    def _advance(self) -> None:
        svc = self._svc()
        steps = (svc or {}).get("coach_steps") or []
        if self._step_idx + 1 < len(steps):
            self._step_idx += 1
            self._key.clear()
            self._render()
            return
        if self._svc_idx + 1 < len(self._queue):
            self._svc_idx += 1
            self._step_idx = 0
            self._opened = ""
            self._key.clear()
            self._render()
            return
        self.accept()

    def _save_key(self) -> None:
        svc = self._svc()
        key = self._key.text().strip()
        if not svc or not key:
            self._status.setText("Paste the API key from their dashboard.")
            return
        self._primary.setEnabled(False)
        api.post_async(
            "/user-keys/verify",
            {"service": svc.get("verify_service"), "api_key": key},
            on_ok=lambda _d: self._put_key(svc, key),
            on_err=self._save_err,
        )

    def _put_key(self, svc: dict, key: str) -> None:
        api.put_async(
            svc.get("save_path") or "/",
            {"api_key": key},
            on_ok=lambda _d: self._saved_ok(svc),
            on_err=self._save_err,
        )

    def _saved_ok(self, svc: dict) -> None:
        self._primary.setEnabled(True)
        self._status.setText(f"{svc.get('label')} saved.")
        if self._on_saved:
            self._on_saved()
        self._advance()

    def _save_err(self, msg: str) -> None:
        self._primary.setEnabled(True)
        self._status.setText(msg or "Key was rejected")
