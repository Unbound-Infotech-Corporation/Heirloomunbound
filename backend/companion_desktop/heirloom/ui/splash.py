"""700 ms serif boot fade — the alien "whisper" before the main window.

No spinner, no logo splash — just a still Cormorant "Heirloom" wordmark
with a hairline gradient beneath it, tinted onto Mica if the OS supports it.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from . import PALETTE


class _Hairline(QWidget):
    """A 1-px hairline that fades to transparent at both ends."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setFixedWidth(220)

    def paintEvent(self, _ev):  # noqa: N802
        from PySide6.QtGui import QLinearGradient

        p = QPainter(self)
        w = self.width()
        grad = QLinearGradient(0, 0, w, 0)
        c = QColor(PALETTE["accent"])
        end = QColor(c)
        end.setAlpha(0)
        grad.setColorAt(0.0, end)
        grad.setColorAt(0.5, c)
        grad.setColorAt(1.0, end)
        p.fillRect(self.rect(), grad)
        p.end()


class Splash(QWidget):
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.SplashScreen
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(520, 260)

        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(14)
        wrap.addStretch(1)

        title = QLabel("Heirloom")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"color: {PALETTE['text_primary']}; font-family:'Cormorant Garamond','Garamond',serif;"
            " font-size: 46px; font-weight: 400; letter-spacing: 2px;"
        )
        wrap.addWidget(title)

        hair = _Hairline()
        wrap.addWidget(hair, 0, Qt.AlignHCenter)

        sub = QLabel("YOUR TWIN IS WAKING")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-family:'JetBrains Mono','Consolas',monospace;"
            " font-size: 9px; letter-spacing: 5px;"
        )
        wrap.addWidget(sub)
        wrap.addStretch(1)

        # Solid card behind everything so the wordmark reads
        self.card = QWidget(self)
        self.card.lower()
        self.card.setGeometry(0, 0, 520, 260)
        self.card.setStyleSheet(
            f"background: {PALETTE['bg_base']}; border: 1px solid {PALETTE['border']};"
            " border-radius: 10px;"
        )

        # Fade in + hold + fade out schedule
        self._eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._eff)
        self._eff.setOpacity(0.0)

    def start(self) -> None:
        # Center on screen
        try:
            from PySide6.QtWidgets import QApplication

            screen = QApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                self.move(
                    geo.center().x() - self.width() // 2,
                    geo.center().y() - self.height() // 2,
                )
        except Exception:  # noqa: BLE001
            pass
        self.show()
        self.raise_()
        # Fade in 220ms, hold 380ms, fade out 200ms → ~800ms total
        anim = QPropertyAnimation(self._eff, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._anim_in = anim
        QTimer.singleShot(600, self._fade_out)

    def _fade_out(self) -> None:
        anim = QPropertyAnimation(self._eff, b"opacity", self)
        anim.setDuration(200)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self._done)
        anim.start()
        self._anim_out = anim

    def _done(self) -> None:
        self.finished.emit()
        self.close()
