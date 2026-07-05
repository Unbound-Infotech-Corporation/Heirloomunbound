"""Ambient aura — the radial glow behind the avatar.

State-driven intensity:
  idle       → 0.30, slow breath at 0.5 Hz
  listening  → 0.65, cool-blue tint, sharper pulses
  thinking   → 0.55, warm-amber tint, medium breath
  speaking   → 0.95, accent rose-gold, driven by external `set_level`
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import PALETTE


class Aura(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._phase = 0.0
        self._breath_rate = 0.03  # radians per tick @ 30fps
        self._intensity = 0.30
        self._target = 0.30
        self._level = 0.0  # 0..1 from waveform, used in speaking mode
        self._color = QColor(PALETTE["accent"])
        self._state = "idle"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_state(self, state: str) -> None:
        s = (state or "").lower()
        self._state = s
        if "speak" in s:
            self._color = QColor(PALETTE["accent"])
            self._target = 0.95
            self._breath_rate = 0.08
        elif "listen" in s:
            self._color = QColor("#8fb4c7")  # cool
            self._target = 0.60
            self._breath_rate = 0.14
        elif "think" in s or "render" in s:
            self._color = QColor("#e6c084")  # warm amber
            self._target = 0.55
            self._breath_rate = 0.06
        elif "err" in s or "not authed" in s:
            self._color = QColor(PALETTE["error"])
            self._target = 0.35
            self._breath_rate = 0.02
        else:
            self._color = QColor(PALETTE["accent"])
            self._target = 0.30
            self._breath_rate = 0.03

    def set_level(self, level: float) -> None:
        # Only impacts speaking state
        self._level = max(0.0, min(1.0, level))

    def _tick(self) -> None:
        # Ease intensity toward target
        self._intensity += (self._target - self._intensity) * 0.08
        self._phase = (self._phase + self._breath_rate) % (2 * math.pi)
        self.update()

    def paintEvent(self, _ev):  # noqa: N802
        w, h = self.width(), self.height()
        if w < 8 or h < 8:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Breathing envelope
        env = (math.sin(self._phase) * 0.35) + 0.65
        # In speaking state, external level dominates
        if "speak" in self._state:
            env = 0.5 + self._level * 0.5

        base_alpha = int(180 * self._intensity * env)
        # Draw 2 concentric radial gradients — closer=warmer/tighter, outer=diffuse
        cx = w / 2
        cy = h / 2
        max_r = max(w, h) * 0.72

        # Inner tight glow
        g1 = QRadialGradient(QPointF(cx, cy), max_r * 0.55)
        inner = QColor(self._color)
        inner.setAlpha(min(255, int(base_alpha * 1.25)))
        outer = QColor(self._color)
        outer.setAlpha(0)
        g1.setColorAt(0.0, inner)
        g1.setColorAt(1.0, outer)
        p.setBrush(g1)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), max_r * 0.55, max_r * 0.55)

        # Outer diffuse halo
        g2 = QRadialGradient(QPointF(cx, cy), max_r)
        mid = QColor(self._color)
        mid.setAlpha(min(255, int(base_alpha * 0.55)))
        g2.setColorAt(0.0, mid)
        g2.setColorAt(1.0, outer)
        p.setBrush(g2)
        p.drawEllipse(QPointF(cx, cy), max_r, max_r)

        p.end()
