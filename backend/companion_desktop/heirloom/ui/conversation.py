"""Conversation thread — bubble or flat per user preference.

Uses a QScrollArea + vertically-stacked QFrames. Each message is rendered
either as a coloured bubble (right-aligned for user) or a vertical-rule
"flat" block (Slack-style).
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import api, config
from . import PALETTE


class _Message(QFrame):
    def __init__(self, role: str, text: str, bubbles: bool, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.role = role
        # Object name drives the QSS style (bubble_* or flat_*)
        if bubbles:
            self.setObjectName(f"bubble_{role}")
        else:
            self.setObjectName(f"flat_{role}")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        inner = QVBoxLayout()
        inner.setContentsMargins(14, 10, 14, 12)
        inner.setSpacing(4)

        role_lbl = QLabel("YOU" if role == "user" else "TWIN")
        role_lbl.setObjectName("role")
        inner.addWidget(role_lbl)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet(f"color: {PALETTE['text_primary']}; font-size: 14px; line-height: 1.5;")
        inner.addWidget(body)

        # Wrap inner in a max-width container so bubbles don't span the whole panel
        wrap = QFrame()
        wrap.setObjectName(self.objectName())
        wrap.setLayout(inner)
        wrap.setMaximumWidth(620)
        wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        if bubbles and role == "user":
            outer.addStretch(1)
            outer.addWidget(wrap)
        elif bubbles:
            outer.addWidget(wrap)
            outer.addStretch(1)
        else:
            outer.addWidget(wrap)
            outer.addStretch(1)


class ConversationPanel(QWidget):
    """Scrollable thread + composer."""

    message_sent = Signal(str)   # raw user text right after submit
    reply_received = Signal(str)  # assistant text after API returns
    messages_changed = Signal()  # transcript updated (chat, voice, history)

    def __init__(self, settings: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._settings = settings
        self._messages: List[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(18, 12, 18, 8)
        title = QLabel("Conversation")
        title.setObjectName("brand")
        title.setStyleSheet(
            f"color: {PALETTE['text_primary']}; font-size: 18px;"
            " font-family: 'Cormorant Garamond', serif;"
        )
        header.addWidget(title)
        header.addStretch(1)

        self.btn_style = QPushButton(
            "Bubbles" if settings.get("bubble_style", True) else "Flat"
        )
        self.btn_style.setObjectName("ghost")
        self.btn_style.clicked.connect(self._toggle_style)
        header.addWidget(self.btn_style)
        root.addLayout(header)

        # Scroll list
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self._thread_host = QWidget()
        self._thread_layout = QVBoxLayout(self._thread_host)
        self._thread_layout.setContentsMargins(18, 6, 18, 6)
        self._thread_layout.setSpacing(10)
        self._thread_layout.addStretch(1)
        self.scroll.setWidget(self._thread_host)
        root.addWidget(self.scroll, 1)

        # Composer
        composer = QHBoxLayout()
        composer.setContentsMargins(18, 8, 18, 14)
        composer.setSpacing(8)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Say something to your twin… (Enter to send, Shift+Enter newline)")
        self.input.setFixedHeight(72)
        composer.addWidget(self.input, 1)

        send = QPushButton("Send")
        send.setObjectName("primary")
        send.clicked.connect(self._on_send)
        composer.addWidget(send)
        root.addLayout(composer)

        # Enter-to-send (Shift+Enter for newline)
        self.input.installEventFilter(self)
        self._busy = False

    # ---- public API ----
    def load_history(self) -> None:
        api.get_async(
            "/desktop/conversation?limit=80",
            on_ok=self._on_history,
            on_err=lambda _m: None,
        )

    def append(self, role: str, text: str) -> None:
        msg = {"role": role, "content": text}
        self._messages.append(msg)
        self._add_widget(msg)
        self.messages_changed.emit()

    def recent_messages(self, limit: int = 8) -> List[dict]:
        if limit < 1:
            return []
        return list(self._messages[-limit:])

    @property
    def is_busy(self) -> bool:
        return bool(self._busy)

    def send_text(self, text: str) -> None:
        """Send a user turn from the composer or the small talk window."""
        if self._busy:
            return
        text = (text or "").strip()
        if not text:
            return
        self.input.clear()
        self._busy = True
        self.append("user", text)
        self.message_sent.emit(text)
        if self._local_chat_active():
            self._send_via_local_chat(text)
            return
        api.post_async(
            "/desktop/chat",
            {"text": text},
            on_ok=self._on_reply,
            on_err=self._on_error,
        )

    # ---- internal ----
    def _on_history(self, data: dict) -> None:
        self._messages = [
            m for m in (data or {}).get("messages", []) if m.get("content")
        ]
        # Rebuild
        while self._thread_layout.count() > 1:
            item = self._thread_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for m in self._messages:
            self._add_widget(m)
        self.messages_changed.emit()

    def _add_widget(self, msg: dict) -> None:
        bubbles = bool(self._settings.get("bubble_style", True))
        role = msg.get("role", "assistant")
        widget = _Message(role, msg.get("content", ""), bubbles)
        # Insert before the trailing stretch
        self._thread_layout.insertWidget(self._thread_layout.count() - 1, widget)
        # Fade-in reveal — 240ms opacity ease-out
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
        eff.setOpacity(0.0)
        anim = QPropertyAnimation(eff, b"opacity", widget)
        anim.setDuration(240)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        widget._reveal_anim = anim  # keep reference
        # Scroll to bottom on next tick
        bar = self.scroll.verticalScrollBar()
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _toggle_style(self) -> None:
        new = not bool(self._settings.get("bubble_style", True))
        self._settings["bubble_style"] = new
        config.save_settings(self._settings)
        self.btn_style.setText("Bubbles" if new else "Flat")
        # Rebuild
        self._on_history({"messages": self._messages})

    def _on_send(self) -> None:
        self.send_text(self.input.toPlainText())

    # -------- Local chat (Ollama / LM Studio / OpenAI-compat) --------
    def _local_chat_active(self) -> bool:
        cfg = (self._settings or {}).get("providers_cache") or {}
        chat_cfg = cfg.get("chat") or {}
        return bool(chat_cfg.get("enabled") and (chat_cfg.get("base_url") or "").strip())

    def _send_via_local_chat(self, text: str) -> None:
        """Fire an OpenAI-compat chat.completions POST at 127.0.0.1 directly.

        We never send the Heirloom device token to a local endpoint. The reply
        arrives on _on_reply just like the cloud path so the UI is unchanged.
        """
        chat_cfg = ((self._settings or {}).get("providers_cache") or {}).get("chat") or {}
        base = (chat_cfg.get("base_url") or "").rstrip("/")
        api_key = (chat_cfg.get("api_key") or "").strip()
        model = (chat_cfg.get("model") or "").strip() or "llama3.3"
        url = base + "/chat/completions" if base.endswith("/v1") else base + "/v1/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are the user's digital twin — warm, first-person, concise."},
                *[{"role": m.get("role", "user"), "content": m.get("content", "")}
                  for m in self._messages[-10:] if m.get("role") in ("user", "assistant")],
                {"role": "user", "content": text},
            ],
            "temperature": 0.7,
            "max_tokens": 512,
        }

        def _ok(res: dict) -> None:
            try:
                reply = (res.get("data") or {}).get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            except Exception:
                reply = ""
            if not reply:
                self._on_error("local chat returned no reply — is the model loaded?")
                return
            self._on_reply({"reply": reply})

        def _err(msg: str) -> None:
            self._on_error(f"local chat unreachable ({msg}) — falling back to cloud")
            # Auto-fallback to cloud so the user isn't blocked.
            self._busy = True
            api.post_async(
                "/desktop/chat", {"text": text},
                on_ok=self._on_reply, on_err=self._on_error,
            )

        api.probe_local_url(url, method="POST", payload=payload,
                            api_key=api_key or None, on_ok=_ok, on_err=_err,
                            timeout=45.0)

    def _on_reply(self, data: dict) -> None:
        self._busy = False
        reply = (data or {}).get("reply", "")
        if reply:
            self.append("assistant", reply)
            self.reply_received.emit(reply)
        else:
            self.messages_changed.emit()

    def _on_error(self, msg: str) -> None:
        self._busy = False
        self.append("assistant", f"(network error: {msg})")

    def eventFilter(self, watched, event):  # noqa: N802
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent

        if watched is self.input and event.type() == QEvent.KeyPress:
            ke: QKeyEvent = event  # type: ignore[assignment]
            if ke.key() in (Qt.Key_Return, Qt.Key_Enter) and not (ke.modifiers() & Qt.ShiftModifier):
                self._on_send()
                return True
        return super().eventFilter(watched, event)
