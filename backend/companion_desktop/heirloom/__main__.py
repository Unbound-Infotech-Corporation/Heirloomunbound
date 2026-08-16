"""Heirloom desktop — entry point.

Run from source:
    python -m heirloom

The backend bakes BACKEND_URL and DEVICE_TOKEN into config.py at download
time, so the user double-clicks Heirloom.bat and is immediately signed in.
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from . import config
from .maintenance import Maintenance
from .ui.main_window import MainWindow, TrayProxy
from .ui.splash import Splash


def _setup_log_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        folder = Path(base) / "Heirloom"
    else:
        folder = Path.home() / ".heirloom"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "setup.log"


def _append_setup_log(text: str) -> None:
    try:
        path = _setup_log_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n{datetime.now().isoformat()}\n{text}\n")
    except Exception:
        pass


def _show_start_error(message: str) -> None:
    _append_setup_log(message)
    try:
        if QApplication.instance() is None:
            QApplication(sys.argv)
        QMessageBox.critical(None, "Heirloom", message)
    except Exception:
        print(message, file=sys.stderr)


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


def _run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Heirloom")
    app.setOrganizationName("Unbound Infotech")
    app.setQuitOnLastWindowClosed(False)  # tray keeps us alive

    unsigned = not config.is_paired()
    if unsigned:
        _append_setup_log(
            "This copy isn’t signed in. Continue with Google in the big window. "
            "Unbound Keyboard will still catch spelling here without signing in."
        )

    window = MainWindow()
    tray = TrayProxy(window)  # noqa: F841 — kept alive by app
    window.quit_requested.connect(app.quit)
    app.aboutToQuit.connect(window.shutdown)
    _schedule_midnight_maintenance(window)

    def _after_splash() -> None:
        window.show()
        try_keyboard = os.environ.get("HEIRLOOM_TRY_KEYBOARD", "").strip() == "1"
        if unsigned:
            QTimer.singleShot(200, window.open_sign_in)
        if try_keyboard:
            QTimer.singleShot(450, window.open_writing_helper)

    # Serif boot fade — 800ms, then reveal the main window
    splash = Splash()
    splash.finished.connect(_after_splash)
    splash.start()

    return app.exec()


def main() -> int:
    try:
        return _run()
    except Exception:
        tb = traceback.format_exc()
        _append_setup_log(tb)
        _show_start_error(
            "Heirloom couldn't start. Download it again from Local PC in your account.\n\n"
            f"Details: {_setup_log_path()}"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
