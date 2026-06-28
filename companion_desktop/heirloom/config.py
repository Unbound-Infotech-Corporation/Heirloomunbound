"""Runtime configuration for the Heirloom desktop app.

Two values are baked-in by the backend's build step:
- BACKEND_URL : the API root (e.g. https://app.heirloom.com)
- DEVICE_TOKEN: the user's Bearer token (created at purchase time)

User-editable settings live in %LOCALAPPDATA%/Heirloom/settings.json so the
user's choices (bubble style, avatar mode, push-to-talk hotkey) survive
upgrades when the app is re-downloaded.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

# ---- baked-in by build step (placeholders if running from source) ----
BACKEND_URL = "__BACKEND_URL__"
DEVICE_TOKEN = "__DEVICE_TOKEN__"

# Fall back to env vars when running from source (developer mode)
if BACKEND_URL.startswith("__"):
    BACKEND_URL = os.environ.get("HEIRLOOM_BACKEND_URL", "http://localhost:8001")
if DEVICE_TOKEN.startswith("__"):
    DEVICE_TOKEN = os.environ.get("HEIRLOOM_DEVICE_TOKEN", "")


def app_data_dir() -> Path:
    """Per-user storage. On Windows: %LOCALAPPDATA%/Heirloom; on macOS/Linux:
    ~/.heirloom — keeps the same code working when devs run on Mac."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        p = Path(base) / "Heirloom"
    else:
        p = Path.home() / ".heirloom"
    p.mkdir(parents=True, exist_ok=True)
    return p


SETTINGS_PATH = app_data_dir() / "settings.json"

_DEFAULTS: Dict[str, Any] = {
    "bubble_style": True,            # bubbles vs flat
    "avatar_mode": "d_id",            # "d_id" | "waveform"
    "avatar_always_visible": True,
    "ptt_hotkey": "ctrl+space",
    "window_geometry": None,
    "pop_out_geometry": None,
    "stay_logged_in": True,
}


def load_settings() -> Dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        return {**_DEFAULTS, **(data if isinstance(data, dict) else {})}
    except Exception:
        return dict(_DEFAULTS)


def save_settings(data: Dict[str, Any]) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(data, indent=2))
    except Exception:
        pass
