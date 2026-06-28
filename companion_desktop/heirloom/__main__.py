"""Heirloom desktop — entry point.

Run from source:
    python -m heirloom

The backend bakes BACKEND_URL and DEVICE_TOKEN into config.py at download
time, so the user double-clicks Heirloom.bat and is immediately signed in.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from . import config
from .ui.main_window import MainWindow, TrayProxy


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Heirloom")
    app.setOrganizationName("Unbound Infotech")
    app.setQuitOnLastWindowClosed(False)  # tray keeps us alive

    if not config.DEVICE_TOKEN:
        QMessageBox.critical(
            None,
            "Heirloom",
            "No device token configured. Re-download Heirloom from your account.",
        )
        return 1

    window = MainWindow()
    tray = TrayProxy(window)  # noqa: F841 — kept alive by app
    window.quit_requested.connect(app.quit)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
