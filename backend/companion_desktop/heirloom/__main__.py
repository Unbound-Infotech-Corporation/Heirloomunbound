"""Heirloom desktop — entry point.

Run from source:
    python -m heirloom

The backend bakes BACKEND_URL and DEVICE_TOKEN into config.py at download
time, so the user double-clicks Heirloom.bat and is immediately signed in.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from . import config
from .maintenance import Maintenance
from .ui.main_window import MainWindow, TrayProxy
from .ui.splash import Splash


def _schedule_midnight_maintenance(window: MainWindow) -> None:
    """If user picked the 'Daily at 3 AM' schedule, fire a timer to do it.
    Cheap: a single QTimer that re-arms after each fire."""

    def _fire():
        sched = (config.load_settings().get("maintenance_schedule") or "on_quit").lower()
        if sched == "midnight":
            try:
                Maintenance().run_async()
            except Exception as exc:  # noqa: BLE001
                print(f"[scheduler] maintenance failed: {exc}")
        _arm()

    def _arm():
        now = datetime.now()
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        delay_ms = max(60_000, int((target - now).total_seconds() * 1000))
        QTimer.singleShot(delay_ms, _fire)

    _arm()


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
    app.aboutToQuit.connect(window.shutdown)
    _schedule_midnight_maintenance(window)

    # Optional: ensure Windows Startup shortcut exists so the twin is always-on
    try:
        settings = config.load_settings()
        if settings.get("autostart", True):
            from .inheritance import enable_windows_autostart
            enable_windows_autostart()
    except Exception as exc:  # noqa: BLE001
        print(f"[autostart] {exc}")

    # Serif boot fade — 800ms, then reveal the main window
    splash = Splash()
    splash.finished.connect(window.show)
    splash.start()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
