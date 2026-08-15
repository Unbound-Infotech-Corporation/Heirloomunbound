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

# Fall back to env vars when running from source (developer mode),
# or if a zip was baked without a public URL.
if not BACKEND_URL or BACKEND_URL.startswith("__"):
    BACKEND_URL = os.environ.get("HEIRLOOM_BACKEND_URL", "http://localhost:8001")
if not DEVICE_TOKEN or DEVICE_TOKEN.startswith("__"):
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
    "mini_talk_geometry": None,  # compact "just the twin" window
    "writing_geometry": None,    # Unbound Keyboard helper
    "stay_logged_in": True,
    "device_token": "",
    "backend_url": "",
    # ---- Local Vault ----
    "vault_folder": None,             # None → default (Documents/HeirloomVault)
    "storage_tier": "partial",        # "full" | "partial" | "lite"
    "maintenance_schedule": "on_quit",  # "midnight" | "on_quit" | "manual"
    "last_maintenance_at": None,
    # ---- Audio ----
    # Twin voice playback volume (0.0-1.0). Explicitly floored at 0.05 in the
    # avatar panel because Windows Volume Mixer gets stuck when a session is
    # created at ~0 volume. Default 1.0 = full volume out of the box.
    "twin_playback_volume": 1.0,
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


def _looks_real_token(token: str) -> bool:
    blob = (token or "").strip()
    return bool(blob) and not blob.startswith("__")


def apply_saved_login() -> None:
    """Unsigned try-it zips pick up a later in-app sign-in from settings.json."""
    global BACKEND_URL, DEVICE_TOKEN
    saved = load_settings()
    tok = str(saved.get("device_token") or "").strip()
    url = str(saved.get("backend_url") or "").strip().rstrip("/")
    if not _looks_real_token(DEVICE_TOKEN) and _looks_real_token(tok):
        DEVICE_TOKEN = tok
    localish = (not BACKEND_URL) or BACKEND_URL.startswith("__") or "localhost" in BACKEND_URL
    if localish and url.startswith("http"):
        BACKEND_URL = url


def persist_login(device_token: str, backend_url: str = "") -> None:
    """Remember this computer's house token. Never a third-party password."""
    global BACKEND_URL, DEVICE_TOKEN
    DEVICE_TOKEN = (device_token or "").strip()
    url = (backend_url or BACKEND_URL or "").strip().rstrip("/")
    if url:
        BACKEND_URL = url
    data = load_settings()
    data["device_token"] = DEVICE_TOKEN
    data["backend_url"] = BACKEND_URL
    save_settings(data)


apply_saved_login()
