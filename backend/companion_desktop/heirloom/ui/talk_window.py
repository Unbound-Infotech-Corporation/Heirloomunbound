"""Compact always-on-top talk window — just you and your twin.

This is the grandmother-simple companion to the full Heirloom window:
face on top, a short transcript, a message box, and hold-to-speak.
Tasks still go through the same twin chat as the big window.

This is NOT the OBS broadcast pop-out (that stays face-only, no chat).
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QRegion
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# Cream card of its own. The main window's dark QSS paints pale letters
# that vanish on this cream talk window.
TALK_QSS = """
    QWidget { color: #3a2418; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
    QLabel { color: #3a2418; background: transparent; }
    QPushButton {
        color: #3a2418;
        background: #fffdf6;
        border: 3px solid #3a2418;
        border-radius: 12px;
        padding: 6px 10px;
        font-weight: 800;
    }
    QPushButton:hover { background: #fff3c4; }
    QPushButton:pressed { background: #f0c040; }
    QPushButton#primary {
        background: #e24a3a;
        color: #fff8e8;
        border: 4px solid #3a2418;
    }
    QPlainTextEdit {
        background: #fff8e4;
        color: #3a2418;
        border: 4px solid #3a2418;
        border-radius: 18px;
        padding: 8px;
        selection-background-color: #f0c040;
        selection-color: #3a2418;
        font-size: 16px;
        font-weight: 600;
    }
    QScrollArea { background: transparent; border: none; }
"""


class MiniTalkWindow(QWidget):
    """Small always-on-top window for talking to the twin and assigning tasks."""

    closed = Signal()
    restore_full = Signal()
    send_requested = Signal(str)
    ptt_pressed = Signal()
    ptt_released = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("talk_window")
        self.setWindowTitle("Your twin")
        self.setWindowFlags(
            Qt.Window
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(TALK_QSS)
        self.resize(380, 580)
        self.setMinimumSize(320, 480)

        self._drag_pos = None
        self._busy = False
        self._raw_portrait: Optional[QPixmap] = None

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
            "QWidget#card QPlainTextEdit { background: #fff8e4; color: #3a2418;"
            " border: 4px solid #3a2418; border-radius: 18px; padding: 8px;"
            " font-size: 16px; font-weight: 600; }"
        )
        root.addWidget(card, 1)
        col = QVBoxLayout(card)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        col.addWidget(self._build_titlebar())
        col.addWidget(self._build_face(), 2)
        col.addWidget(self._build_transcript(), 3)
        col.addWidget(self._build_composer())

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 4, 4)
        grip_row.addStretch(1)
        grip = QSizeGrip(self)
        grip.setStyleSheet("background: transparent;")
        grip_row.addWidget(grip, 0, Qt.AlignRight | Qt.AlignBottom)
        col.addLayout(grip_row)

    def _build_titlebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("titlebar")
        bar.setFixedHeight(52)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 6, 8, 6)
        row.setSpacing(8)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(0)
        overline = QLabel("YOUR TWIN")
        overline.setStyleSheet(
            "color: #c0392b; letter-spacing: 2px;"
            " font-family: 'Segoe UI','Inter',sans-serif;"
            " font-size: 9px; font-weight: 700;"
        )
        hint = QLabel("Just you and your twin")
        hint.setStyleSheet(
            "color: #3a2418; font-family:'Segoe UI','Inter',sans-serif;"
            " font-size: 15px; font-weight: 700;"
        )
        titles.addWidget(overline)
        titles.addWidget(hint)
        row.addLayout(titles, 1)

        self.status_label = QLabel("idle")
        self.status_label.setStyleSheet(
            "color: #5c4030; letter-spacing: 1px; font-size: 10px; font-weight: 700;"
        )
        row.addWidget(self.status_label)

        full = QPushButton("Full window")
        full.setObjectName("ghost")
        full.setToolTip("Show the whole Heirloom window again")
        full.clicked.connect(self.restore_full.emit)
        row.addWidget(full)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("titleicon")
        close_btn.setFixedSize(28, 28)
        close_btn.setToolTip("Hide this window — Heirloom stays in the tray")
        close_btn.clicked.connect(self.close)
        row.addWidget(close_btn)
        return bar

    def _build_face(self) -> QWidget:
        ring = QWidget()
        ring.setObjectName("porthole")
        ring.setAttribute(Qt.WA_StyledBackground, True)
        ring.setMinimumHeight(200)
        ring.setStyleSheet(
            "QWidget#porthole { background: #e24a3a; border: 8px solid #f0c040;"
            " border-radius: 999px; }"
        )
        wrap = QVBoxLayout(ring)
        wrap.setContentsMargins(14, 14, 14, 14)

        stage = QStackedWidget()
        stage.setMinimumHeight(160)
        stage.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.portrait = QLabel()
        self.portrait.setAlignment(Qt.AlignCenter)
        self.portrait.setText("Your twin")
        self.portrait.setStyleSheet("background: #2a1810; color: #f4e8c8; border-radius: 999px;")
        stage.addWidget(self.portrait)

        self.video = QVideoWidget()
        self.video.setStyleSheet("background: #2a1810;")
        stage.addWidget(self.video)

        wrap.addWidget(stage)
        self._face = stage
        self._face.setCurrentIndex(0)
        self._porthole = ring
        return ring

    def _build_transcript(self) -> QWidget:
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        host = QWidget()
        self._thread = QVBoxLayout(host)
        self._thread.setContentsMargins(14, 8, 14, 8)
        self._thread.setSpacing(8)
        self._thread.addStretch(1)
        self.scroll.setWidget(host)
        return self.scroll

    def _build_composer(self) -> QWidget:
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(12, 6, 12, 10)
        col.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Tell your twin what to do…")
        self.input.setFixedHeight(56)
        self.input.installEventFilter(self)
        row.addWidget(self.input, 1)

        send = QPushButton("Send")
        send.setObjectName("primary")
        send.setFixedSize(72, 72)
        send.setStyleSheet(
            "QPushButton { background: #e24a3a; color: #fff8e8; border: 4px solid #3a2418;"
            " border-radius: 36px; font-weight: 700; font-size: 12px; }"
            "QPushButton:pressed { background: #c0392b; }"
        )
        send.clicked.connect(self._on_send)
        self._send_btn = send
        row.addWidget(send)
        col.addLayout(row)

        ptt_row = QHBoxLayout()
        ptt_row.addStretch(1)
        ptt = QPushButton("hold to speak")
        ptt.setObjectName("ptt")
        ptt.setCursor(Qt.PointingHandCursor)
        ptt.setFixedSize(112, 112)
        ptt.setStyleSheet(
            "QPushButton#ptt { background: #e24a3a; color: #fff8e8; border: 5px solid #3a2418;"
            " border-radius: 56px; font-size: 12px; font-weight: 700; padding: 8px; }"
            "QPushButton#ptt:pressed { background: #c0392b; }"
        )
        ptt.setToolTip("Hold and talk. Let go when you're done. (Ctrl+Space also works.)")
        ptt.pressed.connect(self.ptt_pressed.emit)
        ptt.released.connect(self.ptt_released.emit)
        ptt_row.addWidget(ptt)
        ptt_row.addStretch(1)
        col.addLayout(ptt_row)

        look = QPushButton("Look at my screen")
        look.setObjectName("ghost")
        look.setCursor(Qt.PointingHandCursor)
        look.setStyleSheet(
            "QPushButton { background: #f0c040; color: #3a2418; border: 4px solid #3a2418;"
            " border-radius: 24px; font-weight: 700; padding: 12px 16px; }"
            "QPushButton:pressed { background: #d4a628; }"
        )
        look.setToolTip("The twin looks at this computer and helps — games, writing, movies. The picture is deleted after.")
        look.clicked.connect(self._on_look_at_screen)
        col.addWidget(look)
        return wrap

    def _on_look_at_screen(self) -> None:
        if self._busy:
            return
        self.send_requested.emit(
            "Look at my screen and help me with whatever is on it."
        )

    # ---- public API (AvatarPanel + MainWindow) ----
    def set_portrait(self, pixmap: QPixmap) -> None:
        if pixmap is None or pixmap.isNull():
            return
        self._raw_portrait = pixmap
        self.portrait.setText("")
        self.portrait.setPixmap(
            pixmap.scaled(self._face.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def show_video_surface(self) -> QVideoWidget:
        self._face.setCurrentIndex(1)
        return self.video

    def show_portrait_surface(self) -> None:
        self._face.setCurrentIndex(0)

    def set_status(self, status: str) -> None:
        labels = {
            "idle": "idle",
            "thinking": "thinking…",
            "speaking": "speaking",
            "listening": "listening…",
            "rendering": "getting the face ready…",
            "listening…": "listening…",
            "thinking…": "thinking…",
        }
        self.status_label.setText(labels.get(status, status))

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._send_btn.setEnabled(not self._busy)
        self.input.setEnabled(not self._busy)

    def set_messages(self, messages: List[dict]) -> None:
        while self._thread.count() > 1:
            item = self._thread.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for msg in messages[-8:]:
            role = msg.get("role", "assistant")
            text = (msg.get("content") or "").strip()
            if not text:
                continue
            you = role == "user"
            who = "YOU SAID" if you else "TWIN"
            card = QFrame()
            card.setAttribute(Qt.WA_StyledBackground, True)
            if you:
                card.setStyleSheet(
                    "QFrame { background: #c45c38; border: 2px solid #3a2418;"
                    " border-radius: 14px; }"
                )
            else:
                card.setStyleSheet(
                    "QFrame { background: #fff8e4; border: 2px solid #3a2418;"
                    " border-radius: 14px; }"
                )
            col = QVBoxLayout(card)
            col.setContentsMargins(10, 8, 10, 10)
            col.setSpacing(2)
            kicker = QLabel(who)
            kicker.setStyleSheet(
                ("color: #fff8e4;" if you else "color: #c45c38;")
                + " font-size: 10px; letter-spacing: 2px; font-weight: 800;"
                " background: transparent;"
            )
            body = QLabel(text)
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body.setStyleSheet(
                ("color: #fff8e4;" if you else "color: #3a2418;")
                + " font-size: 16px; line-height: 1.4; font-weight: 700;"
                " background: transparent;"
            )
            col.addWidget(kicker)
            col.addWidget(body)
            self._thread.insertWidget(self._thread.count() - 1, card)
        bar = self.scroll.verticalScrollBar()
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def _on_send(self) -> None:
        if self._busy:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.send_requested.emit(text)

    def eventFilter(self, watched, event):  # noqa: N802
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent

        if watched is self.input and event.type() == QEvent.KeyPress:
            ke: QKeyEvent = event  # type: ignore[assignment]
            if ke.key() in (Qt.Key_Return, Qt.Key_Enter) and not (ke.modifiers() & Qt.ShiftModifier):
                self._on_send()
                return True
        return super().eventFilter(watched, event)

    def _apply_porthole_mask(self) -> None:
        w = self._face
        side = min(max(w.width(), 1), max(w.height(), 1))
        x = max(0, (w.width() - side) // 2)
        y = max(0, (w.height() - side) // 2)
        w.setMask(QRegion(x, y, side, side, QRegion.Ellipse))

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._apply_porthole_mask()
        if self._raw_portrait is not None:
            self.portrait.setPixmap(
                self._raw_portrait.scaled(
                    self._face.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() == Qt.LeftButton and ev.position().y() <= 52:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):  # noqa: N802
        if self._drag_pos is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(ev)

    def closeEvent(self, ev):  # noqa: N802
        self.closed.emit()
        super().closeEvent(ev)
