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
        if self._busy:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.append("user", text)
        self.message_sent.emit(text)
        self._busy = True
        api.post_async(
            "/desktop/chat",
            {"text": text},
            on_ok=self._on_reply,
            on_err=self._on_error,
        )

    def _on_reply(self, data: dict) -> None:
        self._busy = False
        reply = (data or {}).get("reply", "")
        tools = (data or {}).get("tool_trace") or []
        action = (data or {}).get("action")
        if tools:
            labels = ", ".join(
                (t.get("ui") or {}).get("label") or t.get("name") or "tool"
                for t in tools
            )
            self.append("assistant", f"⚙ {labels}")
        if action and action.get("kind") == "music":
            q = action.get("query") or ""
            provider = action.get("provider_name") or action.get("provider") or "music"
            self.append("assistant", f"♪ {q} · {provider}")
        if reply:
            self.append("assistant", reply)
            self.reply_received.emit(reply)

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
