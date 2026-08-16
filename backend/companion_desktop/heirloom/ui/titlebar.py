"""Frameless custom titlebar — the first thing a user sees.

Three regions, left→right:
  • Brand block (Cormorant serif "Heirloom" · monospace user name)
  • Center: breathing status pill (dot animates on idle, brightens on
    speaking, glows amber on thinking)
  • Right: hold-to-talk pill, settings glyph, min / max / close

The whole strip is a drag handle. Double-click toggles maximize.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import PALETTE


class BreathingDot(QWidget):
    """A single 8-px dot that breathes — alpha ramps 0.35→1.0 on a sine wave."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._phase = 0.0
        self._intensity = 1.0  # 0..1 target
        self._color = QColor(PALETTE["accent"])
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)  # 25 fps

    def set_mode(self, mode: str) -> None:
        # mode ∈ {"idle","thinking","speaking","listening","error"}
        m = (mode or "").lower()
        if "error" in m or "err" in m or "not authed" in m:
            self._color = QColor(PALETTE["error"])
            self._intensity = 1.0
            return
        if "think" in m or "render" in m:
            self._color = QColor("#e6c084")  # warm amber
            self._intensity = 0.95
            return
        if "speak" in m:
            self._color = QColor(PALETTE["accent"])
            self._intensity = 1.0
            return
        if "listen" in m:
            self._color = QColor("#8fb4c7")  # cool blue-grey
            self._intensity = 0.9
            return
        # idle / anything else
        self._color = QColor(PALETTE["accent"])
        self._intensity = 0.55

    def _tick(self) -> None:
        self._phase = (self._phase + 0.12) % (2 * math.pi)
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        breath = (math.sin(self._phase) * 0.35) + 0.65
        alpha = int(255 * min(1.0, breath * self._intensity))
        c = QColor(self._color)
        c.setAlpha(alpha)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.drawEllipse(r)
        # subtle outer ring for depth
        ring = QColor(self._color)
        ring.setAlpha(int(alpha * 0.35))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ring, 0.8))
        p.drawEllipse(self.rect().adjusted(0, 0, -1, -1))
        p.end()


class WindowButton(QPushButton):
    """A 46×28 min/max/close button — Windows-native metrics, our palette."""

    def __init__(self, glyph: str, *, danger: bool = False, parent=None):
        super().__init__(parent)
        self._glyph = glyph
        self._danger = danger
        self._hover = False
        self.setFixedSize(46, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet("QPushButton { border: none; background: transparent; }")

    def enterEvent(self, ev):  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(ev)

    def paintEvent(self, _ev):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._hover:
            bg = QColor("#c0635a") if self._danger else QColor(255, 255, 255, 22)
            p.fillRect(self.rect(), bg)
        pen_color = QColor("#ffffff") if (self._danger and self._hover) else QColor(PALETTE["text_secondary"])
        p.setPen(QPen(pen_color, 1.05))
        # Draw glyph as vector, not text
        r = self.rect()
        cx, cy = r.center().x(), r.center().y()
        s = 5  # half-size
        if self._glyph == "min":
            p.drawLine(cx - s, cy + 3, cx + s, cy + 3)
        elif self._glyph == "max":
            p.drawRect(cx - s, cy - s, s * 2, s * 2)
        elif self._glyph == "restore":
            # Two overlapping squares
            p.drawRect(cx - s + 2, cy - s, s * 2 - 2, s * 2 - 2)
            p.drawRect(cx - s, cy - s + 2, s * 2 - 2, s * 2 - 2)
        elif self._glyph == "close":
            p.drawLine(cx - s, cy - s, cx + s, cy + s)
            p.drawLine(cx + s, cy - s, cx - s, cy + s)
        p.end()


class TitleBar(QWidget):
    """Frameless titlebar. Emits its own signals so main_window stays clean."""

    ptt_pressed = Signal()
    ptt_released = Signal()
    settings_clicked = Signal()
    palette_clicked = Signal()
    signin_clicked = Signal()

    def __init__(
        self,
        window: QWidget,
        *,
        on_minimize: Optional[Callable] = None,
        on_maximize: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
    ):
        super().__init__(window)
        self._window = window
        self._drag_offset: Optional[QPoint] = None
        self.setObjectName("titlebar")
        self.setFixedHeight(48)
        self.setAttribute(Qt.WA_StyledBackground, True)

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 0, 0, 0)
        row.setSpacing(14)

        # --- brand block ---
        brand_col = QVBoxLayout()
        brand_col.setContentsMargins(0, 6, 0, 6)
        brand_col.setSpacing(0)
        overline = QLabel("HEIRLOOM")
        overline.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 3px;"
            " font-family: 'JetBrains Mono','Consolas','Courier New',monospace;"
            " font-size: 8px;"
        )
        self.user_label = QLabel("your archive")
        self.user_label.setStyleSheet(
            f"color: {PALETTE['text_primary']}; font-family:'Cormorant Garamond','Garamond',serif;"
            " font-size: 15px; font-weight: 500; letter-spacing: 0.2px;"
        )
        brand_col.addWidget(overline)
        brand_col.addWidget(self.user_label)
        row.addLayout(brand_col)

        row.addStretch(1)

        # --- center: status pill ---
        self.pill = QWidget()
        self.pill.setObjectName("statuspill")
        pill_row = QHBoxLayout(self.pill)
        pill_row.setContentsMargins(10, 4, 12, 4)
        pill_row.setSpacing(8)
        self.dot = BreathingDot()
        pill_row.addWidget(self.dot)
        self.pill_label = QLabel("idle")
        self.pill_label.setStyleSheet(
            f"color: {PALETTE['text_secondary']}; letter-spacing: 2px;"
            " font-family:'JetBrains Mono','Consolas','Courier New',monospace;"
            " font-size: 10px;"
        )
        pill_row.addWidget(self.pill_label)
        row.addWidget(self.pill)

        row.addStretch(1)

        # --- right: Google sign-in, command palette hint, PTT, settings, window buttons ---
        self.signin_btn = QPushButton("Sign in with Google")
        self.signin_btn.setObjectName("googlesignin")
        self.signin_btn.setCursor(Qt.PointingHandCursor)
        self.signin_btn.setMinimumHeight(32)
        self.signin_btn.setToolTip("Opens Google in your browser. We never see that password.")
        self.signin_btn.clicked.connect(lambda _checked=False: self.signin_clicked.emit())
        self.signin_btn.setVisible(False)
        row.addWidget(self.signin_btn)

        self.cmd_hint = QPushButton("⌘  ctrl · k")
        self.cmd_hint.setObjectName("kbdhint")
        self.cmd_hint.setCursor(Qt.PointingHandCursor)
        self.cmd_hint.setToolTip("Command palette")
        self.cmd_hint.clicked.connect(self.palette_clicked.emit)
        row.addWidget(self.cmd_hint)

        self.ptt_btn = QPushButton("hold to speak")
        self.ptt_btn.setObjectName("ptt")
        self.ptt_btn.setCursor(Qt.PointingHandCursor)
        self.ptt_btn.pressed.connect(self.ptt_pressed.emit)
        self.ptt_btn.released.connect(self.ptt_released.emit)
        self.ptt_btn.setToolTip("Push-to-talk (Ctrl+Space)")
        row.addWidget(self.ptt_btn)

        self.settings_btn = QPushButton("···")
        self.settings_btn.setObjectName("titleicon")
        self.settings_btn.setFixedSize(34, 28)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        self.settings_btn.setToolTip("Settings")
        row.addWidget(self.settings_btn)

        # A tiny gap before the window buttons
        row.addSpacing(6)

        self.min_btn = WindowButton("min")
        self.max_btn = WindowButton("max")
        self.close_btn = WindowButton("close", danger=True)
        if on_minimize:
            self.min_btn.clicked.connect(on_minimize)
        if on_maximize:
            self.max_btn.clicked.connect(on_maximize)
        if on_close:
            self.close_btn.clicked.connect(on_close)
        row.addWidget(self.min_btn)
        row.addWidget(self.max_btn)
        row.addWidget(self.close_btn)

    # --- public state ---
    def set_status(self, status: str) -> None:
        self.pill_label.setText(status)
        self.dot.set_mode(status)

    def set_user_name(self, name: str) -> None:
        self.user_label.setText(name)

    def set_google_visible(self, visible: bool) -> None:
        self.signin_btn.setVisible(bool(visible))

    def set_maximized(self, maximized: bool) -> None:
        self.max_btn._glyph = "restore" if maximized else "max"
        self.max_btn.update()

    # --- drag + double-click maximize ---
    def mousePressEvent(self, ev: QMouseEvent):  # noqa: N802
        if ev.button() == Qt.LeftButton and self._hit_drag_region(ev.position().toPoint()):
            self._drag_offset = ev.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent):  # noqa: N802
        if self._drag_offset is not None and (ev.buttons() & Qt.LeftButton):
            # Restoring from maximized while dragging
            if self._window.isMaximized():
                self._window.showNormal()
                # Re-center under cursor
                self._drag_offset = QPoint(self._window.width() // 2, self.height() // 2)
            self._window.move(ev.globalPosition().toPoint() - self._drag_offset)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent):  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev: QMouseEvent):  # noqa: N802
        if self._hit_drag_region(ev.position().toPoint()):
            if self._window.isMaximized():
                self._window.showNormal()
            else:
                self._window.showMaximized()
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)

    def _hit_drag_region(self, pt: QPoint) -> bool:
        # Exclude buttons on the right
        excluded = (
            self.min_btn.geometry()
            | self.max_btn.geometry()
            | self.close_btn.geometry()
            | self.settings_btn.geometry()
            | self.ptt_btn.geometry()
            | self.cmd_hint.geometry()
            | self.signin_btn.geometry()
        )
        return not excluded.contains(pt)
