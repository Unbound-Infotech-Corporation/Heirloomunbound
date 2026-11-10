"""Optional hidden start when Windows signs in. The owner turns it on."""
from __future__ import annotations

import sys
from pathlib import Path


def login_arguments(app_root: Path) -> str:
    script = Path(app_root) / "Start-StudyHall.ps1"
    return f'-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{script}" -Hidden'


def apply_login_start(enabled: bool, app_root: Path, *, invoke=None) -> dict:
    """Record the choice. On Windows, or when a runner is injected, apply the shortcut."""
    root = Path(app_root)
    script = root / "Enable-StudyHallLogin.ps1"
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    if not enabled:
        command.append("-Disable")
    applied = False
    if invoke is not None:
        invoke(command)
        applied = True
    elif sys.platform == "win32" and script.is_file():
        import subprocess
        subprocess.run(command, check=False)
        applied = True
    note = "Study Hall will start hidden at sign-in." if enabled else "Study Hall will not start at sign-in."
    if enabled and not applied:
        note = "Saved on this PC. On Windows the installer adds a hidden Startup shortcut."
    return {"enabled": bool(enabled), "applied": applied, "note": note, "arguments": login_arguments(root)}
