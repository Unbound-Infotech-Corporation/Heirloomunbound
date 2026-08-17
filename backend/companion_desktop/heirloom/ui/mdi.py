"""Photoshop-style MDI subwindow with its own menubar."""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenuBar, QMdiSubWindow, QVBoxLayout, QWidget


MenuSpec = Iterable[tuple[str, Iterable[tuple[str, Optional[Callable], str]]]]


class FeatureWindow(QMdiSubWindow):
    """A named studio window. `menus` is [(menu_title, [(label, callback, shortcut)])]."""

    def __init__(self, title: str, body: QWidget, menus: MenuSpec | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        wrap = QWidget()
        wrap.setObjectName("mdi_body")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.menubar = QMenuBar(wrap)
        self.menubar.setNativeMenuBar(False)
        lay.addWidget(self.menubar)
        lay.addWidget(body, 1)
        self.body = body
        self.setWidget(wrap)
        if menus:
            self.rebuild_menus(menus)

    def rebuild_menus(self, menus: MenuSpec) -> None:
        self.menubar.clear()
        for title, items in menus:
            menu = self.menubar.addMenu(title)
            for spec in items:
                label = spec[0]
                callback = spec[1] if len(spec) > 1 else None
                shortcut = spec[2] if len(spec) > 2 else ""
                if label == "---":
                    menu.addSeparator()
                    continue
                act = QAction(label, self)
                if shortcut:
                    act.setShortcut(QKeySequence(shortcut))
                if callback is not None:
                    act.triggered.connect(callback)
                menu.addAction(act)
