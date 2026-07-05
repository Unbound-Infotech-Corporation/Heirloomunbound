"""Command palette — Ctrl+K, the tell-tale sign of a serious desktop app.

Rich mode (per user pref): the first two rows are always live actions on
whatever the user is typing:
   → speak · "<query>"     sends query to twin, plays reply
   → capture · "<query>"   saves query as a quick-cap note

Below those, static commands fuzzy-match against label + hint.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PySide6.QtCore import (
    QEvent,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import PALETTE


@dataclass
class Command:
    id: str
    label: str
    hint: str = ""
    shortcut: str = ""
    action: Callable[[], None] = field(default=lambda: None)
    dynamic: bool = False  # True for "speak" / "capture" rows that consume the query


def _fuzzy_score(needle: str, hay: str) -> float:
    """Cheap subsequence-with-boost fuzzy match. Returns 0..1."""
    if not needle:
        return 1.0
    needle = needle.lower()
    hay = hay.lower()
    if needle in hay:
        # Big boost for contiguous matches at word boundaries
        idx = hay.index(needle)
        boost = 1.0 if idx == 0 or hay[idx - 1] == " " else 0.85
        return boost - (idx / max(1, len(hay))) * 0.15
    i = 0
    score = 0.0
    for ch in hay:
        if i < len(needle) and ch == needle[i]:
            score += 1.0
            i += 1
    if i < len(needle):
        return 0.0
    return score / max(1, len(hay))


class _Row(QFrame):
    """Palette row — icon glyph, label, hint, right-side kbd hint."""

    def __init__(self, cmd: Command, query: str = "", parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self._selected = False
        self.setFixedHeight(48)
        self.setObjectName("palrow")

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 6, 14, 6)
        row.setSpacing(12)

        glyph = QLabel("›")
        glyph.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 18px;"
            " font-family:'Cormorant Garamond','Garamond',serif;"
        )
        glyph.setFixedWidth(14)
        row.addWidget(glyph)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)
        label_text = cmd.label
        if cmd.dynamic and query:
            label_text = f"{cmd.label}  ·  \"{query}\""
        self.label = QLabel(label_text)
        self.label.setStyleSheet(
            f"color: {PALETTE['text_primary']}; font-size: 13px; font-weight: 500;"
        )
        text_col.addWidget(self.label)
        if cmd.hint:
            hint = QLabel(cmd.hint)
            hint.setStyleSheet(
                f"color: {PALETTE['text_muted']}; font-size: 11px;"
            )
            text_col.addWidget(hint)
        row.addLayout(text_col, 1)

        if cmd.shortcut:
            sc = QLabel(cmd.shortcut)
            sc.setStyleSheet(
                f"color: {PALETTE['text_muted']};"
                " font-family:'JetBrains Mono','Consolas',monospace;"
                " font-size: 10px; letter-spacing: 1.5px;"
                f" padding: 3px 8px; border: 1px solid {PALETTE['border']}; border-radius: 3px;"
            )
            row.addWidget(sc)

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self.setStyleSheet(
            "QFrame#palrow { background: rgba(212,163,115,0.14);"
            f" border-left: 2px solid {PALETTE['accent']}; }}"
            if on
            else "QFrame#palrow { background: transparent; border-left: 2px solid transparent; }"
        )


class CommandPalette(QDialog):
    """Frameless, blur-backed, keyboard-first palette."""

    dismissed = Signal()

    def __init__(self, parent, commands: List[Command]):
        super().__init__(parent)
        self._all_commands = commands
        self._filtered: List[Command] = []
        self._selected_idx = 0
        self._query = ""

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Popup | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.resize(620, 440)

        # Card (rounded, dropshadow)
        self.card = QFrame(self)
        self.card.setObjectName("palcard")
        self.card.setGeometry(0, 0, 620, 440)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(60)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 12)
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # Search input
        input_wrap = QFrame()
        input_wrap.setObjectName("palinputwrap")
        iw = QHBoxLayout(input_wrap)
        iw.setContentsMargins(20, 14, 20, 14)
        iw.setSpacing(12)
        prompt = QLabel("›")
        prompt.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 22px;"
            " font-family:'Cormorant Garamond','Garamond',serif;"
        )
        iw.addWidget(prompt)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Speak to your twin, capture a thought, or run a command…")
        self.input.setObjectName("palinput")
        self.input.textChanged.connect(self._on_text)
        self.input.returnPressed.connect(self._run_selected)
        iw.addWidget(self.input, 1)
        card_layout.addWidget(input_wrap)

        # Divider
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {PALETTE['border']};")
        card_layout.addWidget(divider)

        # Results
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setObjectName("palscroll")
        self.scroll.setStyleSheet("background: transparent;")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self._results_host = QWidget()
        self._results_host.setStyleSheet("background: transparent;")
        self._results_layout = QVBoxLayout(self._results_host)
        self._results_layout.setContentsMargins(6, 6, 6, 6)
        self._results_layout.setSpacing(0)
        self._results_layout.addStretch(1)
        self.scroll.setWidget(self._results_host)
        card_layout.addWidget(self.scroll, 1)

        # Footer hint strip
        footer = QLabel(" ↑↓ to navigate    ↵ to run    esc to close ")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet(
            f"color: {PALETTE['text_muted']};"
            " font-family:'JetBrains Mono','Consolas',monospace;"
            " font-size: 10px; letter-spacing: 2px;"
            f" background: {PALETTE['bg_base']}; padding: 8px 0;"
            f" border-top: 1px solid {PALETTE['border']};"
        )
        card_layout.addWidget(footer)

        # Style everything
        self.setStyleSheet(
            f"""
            QFrame#palcard {{
                background: {PALETTE['bg_surface']};
                border: 1px solid {PALETTE['border']};
                border-radius: 10px;
            }}
            QFrame#palinputwrap {{
                background: transparent;
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
            QLineEdit#palinput {{
                background: transparent;
                border: none;
                color: {PALETTE['text_primary']};
                font-size: 17px;
                font-family: 'Inter','Segoe UI',sans-serif;
            }}
            QScrollArea#palscroll {{ background: transparent; }}
            """
        )

        # Fade in
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(150)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
        self._fade_in = anim  # keep reference

        self._recompute()

    # ---- filtering ----
    def _on_text(self, text: str) -> None:
        self._query = text
        self._recompute()

    def _recompute(self) -> None:
        # Dynamic rows first if query is non-empty
        dyn: List[Command] = []
        static: List[Command] = []
        for c in self._all_commands:
            if c.dynamic:
                dyn.append(c)
            else:
                static.append(c)

        scored = []
        q = self._query.strip()
        if q:
            # Show dynamic rows first (they consume the query)
            for c in dyn:
                scored.append((1.5, c))
            # Then fuzzy-matched static
            for c in static:
                s = max(_fuzzy_score(q, c.label), _fuzzy_score(q, c.hint) * 0.7)
                if s > 0:
                    scored.append((s, c))
            scored.sort(key=lambda x: -x[0])
        else:
            # No query — hide dynamic rows, show static in original order
            for c in static:
                scored.append((1.0, c))

        self._filtered = [c for _s, c in scored]
        self._selected_idx = 0 if self._filtered else -1
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        # Clear
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, cmd in enumerate(self._filtered):
            row = _Row(cmd, query=self._query if cmd.dynamic else "")
            row.set_selected(i == self._selected_idx)
            row.mousePressEvent = lambda _ev, idx=i: self._click_row(idx)  # type: ignore[assignment]
            self._results_layout.insertWidget(self._results_layout.count() - 1, row)

    def _click_row(self, idx: int) -> None:
        self._selected_idx = idx
        self._rebuild_rows()
        self._run_selected()

    def _run_selected(self) -> None:
        if not self._filtered or self._selected_idx < 0:
            self.close()
            return
        cmd = self._filtered[self._selected_idx]
        # Run action — dynamic rows get the query, static don't
        try:
            if cmd.dynamic:
                cmd.action(self._query.strip())  # type: ignore[call-arg]
            else:
                cmd.action()
        except Exception as exc:  # noqa: BLE001
            print(f"[palette] {cmd.id} failed: {exc}")
        self.close()

    # ---- keyboard nav ----
    def keyPressEvent(self, ev: QKeyEvent):  # noqa: N802
        k = ev.key()
        if k == Qt.Key_Escape:
            self.close()
            ev.accept()
            return
        if k == Qt.Key_Down:
            if self._filtered:
                self._selected_idx = (self._selected_idx + 1) % len(self._filtered)
                self._rebuild_rows()
            ev.accept()
            return
        if k == Qt.Key_Up:
            if self._filtered:
                self._selected_idx = (self._selected_idx - 1) % len(self._filtered)
                self._rebuild_rows()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def showEvent(self, ev):  # noqa: N802
        super().showEvent(ev)
        # Center over parent
        if self.parent():
            pg = self.parent().geometry()
            self.move(
                pg.center().x() - self.width() // 2,
                pg.top() + 120,
            )
        self.input.setFocus()

    def closeEvent(self, ev):  # noqa: N802
        self.dismissed.emit()
        super().closeEvent(ev)
