"""Windows 11 Mica / dark-mode enablement via dwmapi.

Nothing here is required for the app to run — every call is wrapped so a
missing dwmapi.dll (Wine, Win7, ReactOS), a rejected attribute (Win10 builds
before 1809), or an ABI mismatch silently no-ops. The goal is: on modern
Windows 11 the whole window becomes tinted glass; everywhere else the app
still looks correct against the palette's solid bg.

References:
- DwmSetWindowAttribute:   https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/nf-dwmapi-dwmsetwindowattribute
- DWM_SYSTEMBACKDROP_TYPE: https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import byref, c_int, sizeof
from typing import Optional

# Attribute IDs
DWMWA_USE_IMMERSIVE_DARK_MODE = 20         # Win10 1809+ / Win11
DWMWA_MICA_EFFECT = 1029                    # Win11 pre-22H2 (undocumented)
DWMWA_SYSTEMBACKDROP_TYPE = 38              # Win11 22H2+ (public)

# DWM_SYSTEMBACKDROP_TYPE values
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2       # Mica
DWMSBT_TRANSIENTWINDOW = 3  # Acrylic
DWMSBT_TABBEDWINDOW = 4     # Tabbed / Mica Alt


def is_windows() -> bool:
    return sys.platform == "win32"


def enable_dark_titlebar(hwnd: int) -> bool:
    """Force the client-drawn titlebar into immersive dark mode."""
    if not is_windows():
        return False
    try:
        dwm = ctypes.windll.dwmapi
        val = c_int(1)
        dwm.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, byref(val), sizeof(val)
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[mica] dark titlebar failed: {exc}")
        return False


def enable_mica(hwnd: int, kind: str = "mica") -> Optional[str]:
    """Enable Mica (or Acrylic) on the given HWND.

    Returns "22h2" | "legacy" | None depending on which path succeeded.
    Silent no-op on non-Windows / older Windows.
    """
    if not is_windows():
        return None
    try:
        dwm = ctypes.windll.dwmapi
        # Try the modern API first
        backdrop_value = {
            "mica": DWMSBT_MAINWINDOW,
            "acrylic": DWMSBT_TRANSIENTWINDOW,
            "tabbed": DWMSBT_TABBEDWINDOW,
        }.get(kind, DWMSBT_MAINWINDOW)
        val = c_int(backdrop_value)
        rc = dwm.DwmSetWindowAttribute(
            hwnd, DWMWA_SYSTEMBACKDROP_TYPE, byref(val), sizeof(val)
        )
        if rc == 0:
            return "22h2"
        # Fallback for pre-22H2 Win11 builds
        enable = c_int(1)
        rc2 = dwm.DwmSetWindowAttribute(
            hwnd, DWMWA_MICA_EFFECT, byref(enable), sizeof(enable)
        )
        if rc2 == 0:
            return "legacy"
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"[mica] enable failed: {exc}")
        return None


def apply(window) -> Optional[str]:
    """Convenience: dark titlebar + Mica on a QWidget.

    Requires the window to have `Qt.WA_TranslucentBackground` set AND the
    root widget to have a semi-transparent background in QSS, otherwise the
    solid bg will cover the Mica layer.
    """
    try:
        hwnd = int(window.winId())
    except Exception as exc:  # noqa: BLE001
        print(f"[mica] winId failed: {exc}")
        return None
    enable_dark_titlebar(hwnd)
    return enable_mica(hwnd, "mica")
