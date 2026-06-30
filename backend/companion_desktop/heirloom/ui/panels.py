"""Right-sidebar quick-capture + recent-memories sidebar (used on the left)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import api
from . import PALETTE


class QuickCapture(QWidget):
    saved = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("quickcap")

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(8)

        overline = QLabel("QUICK CAPTURE")
        overline.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 2px; font-size: 10px;"
        )
        title = QLabel("Save a thought")
        title.setStyleSheet(
            f"color: {PALETTE['text_primary']}; font-family: 'Cormorant Garamond', serif; font-size: 18px;"
        )
        root.addWidget(overline)
        root.addWidget(title)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Title (optional)")
        root.addWidget(self.title_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["note", "memory", "belief", "story"])
        root.addWidget(self.type_combo)

        self.body = QPlainTextEdit()
        self.body.setPlaceholderText("Write it out — your twin will remember…")
        self.body.setMinimumHeight(160)
        root.addWidget(self.body, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        save = QPushButton("Save to archive")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        actions.addWidget(save)
        root.addLayout(actions)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 11px;")
        root.addWidget(self.status)

    def _save(self) -> None:
        text = self.body.toPlainText().strip()
        if not text:
            self.status.setText("Empty — write something first.")
            return
        payload = {
            "title": self.title_input.text().strip() or None,
            "content": text,
            "type": self.type_combo.currentText(),
            "tags": [],
        }
        self.status.setText("Saving…")
        api.post_async(
            "/desktop/capture",
            payload,
            on_ok=self._on_saved,
            on_err=lambda msg: self.status.setText(f"Error: {msg}"),
        )

    def _on_saved(self, data: dict) -> None:
        self.body.clear()
        self.title_input.clear()
        self.status.setText("Saved.")
        self.saved.emit(data or {})


class RecentMemories(QWidget):
    """Scrollable list of recent archive entries. Refresh button at top."""

    refreshed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 14, 14)
        root.setSpacing(8)

        head = QHBoxLayout()
        overline = QLabel("MEMORIES")
        overline.setStyleSheet(
            f"color: {PALETTE['text_muted']}; letter-spacing: 2px; font-size: 10px;"
        )
        head.addWidget(overline)
        head.addStretch(1)
        refresh = QPushButton("↻")
        refresh.setObjectName("ghost")
        refresh.setFixedWidth(28)
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh)
        root.addLayout(head)

        title = QLabel("Recent")
        title.setStyleSheet(
            f"color: {PALETTE['text_primary']}; font-family: 'Cormorant Garamond', serif; font-size: 18px;"
        )
        root.addWidget(title)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self._host = QWidget()
        self._layout = QVBoxLayout(self._host)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self.scroll.setWidget(self._host)
        root.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        api.get_async(
            "/desktop/memories/recent?limit=25",
            on_ok=self._on_data,
            on_err=lambda _m: None,
        )

    def _on_data(self, data: dict) -> None:
        items = (data or {}).get("items", [])
        # Clear
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for it in items:
            self._layout.insertWidget(self._layout.count() - 1, _MemoryRow(it))
        self.refreshed.emit()


class _MemoryRow(QFrame):
    def __init__(self, item: dict):
        super().__init__()
        self.setStyleSheet(
            f"background: {PALETTE['bg_elevated']}; border: 1px solid {PALETTE['border']};"
            " border-radius: 3px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(2)
        kind = QLabel((item.get("type", "note")).upper())
        kind.setStyleSheet(
            f"color: {PALETTE['accent']}; letter-spacing: 2px; font-size: 9px;"
        )
        layout.addWidget(kind)
        title = QLabel(item.get("title", ""))
        title.setStyleSheet(
            f"color: {PALETTE['text_primary']}; font-family: 'Cormorant Garamond', serif; font-size: 14px;"
        )
        title.setWordWrap(True)
        layout.addWidget(title)
        body = item.get("content", "")
        if body:
            preview = QLabel(body[:140] + ("…" if len(body) > 140 else ""))
            preview.setWordWrap(True)
            preview.setStyleSheet(f"color: {PALETTE['text_secondary']}; font-size: 12px;")
            layout.addWidget(preview)
