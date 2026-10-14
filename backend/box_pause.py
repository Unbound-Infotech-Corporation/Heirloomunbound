"""One pause switch for Observer and Presence.

Manual pause (cli, web, hotkey) is shared. Quiet hours stay on each feature
and only apply inside their window. A missing file means not paused.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


def data_root() -> Path:
    raw = (os.environ.get("HEIRLOOM_DATA_ROOT") or "/var/lib/heirloom").strip()
    return Path(raw or "/var/lib/heirloom")


DEFAULT_PATH = "/var/lib/heirloom/pause.json"
_MANUAL = frozenset({"cli", "web", "hotkey"})


def pause_path(raw: Optional[str] = None) -> Path:
    if raw is None:
        raw = os.environ.get("HEIRLOOM_PAUSE_FILE", "")
    text = (raw or "").strip()
    if not text:
        text = str(data_root() / "pause.json")
    return Path(text)


def read_pause(path: Optional[Path] = None) -> dict:
    file = path or pause_path()
    try:
        if not file.is_file():
            return {"paused": False, "reason": ""}
        loaded = json.loads(file.read_text(encoding="utf-8") or "null")
    except (OSError, json.JSONDecodeError):
        return {"paused": False, "reason": ""}
    if not isinstance(loaded, dict):
        return {"paused": False, "reason": ""}
    reason = str(loaded.get("reason") or "")
    paused = bool(loaded.get("paused")) and reason in _MANUAL
    return {"paused": paused, "reason": reason if paused else ""}


def write_pause(paused: bool, reason: str, path: Optional[Path] = None) -> dict:
    file = path or pause_path()
    payload = {"paused": bool(paused), "reason": reason if paused else ""}
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(file.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(file)
    try:
        os.chmod(file, 0o640)
    except OSError:
        pass
    return payload


def merged_state(state: Optional[dict], shared: Optional[dict] = None) -> dict:
    """Manual shared pause wins over a clear local state. Local manual pause still wins."""
    current = dict(state or {})
    if current.get("paused") and str(current.get("reason") or "") in _MANUAL:
        return current
    other = shared if shared is not None else read_pause()
    if other.get("paused") and str(other.get("reason") or "") in _MANUAL:
        current["paused"] = True
        current["reason"] = str(other.get("reason") or "cli")
    return current


def share_pause(paused: bool, reason: str, path: Optional[Path] = None) -> dict:
    """Write the shared switch and both feature stores when they already exist."""
    payload = write_pause(paused, reason, path)
    _touch_observer(paused, reason)
    _touch_presence(paused, reason)
    return payload


def _touch_observer(paused: bool, reason: str) -> None:
    try:
        from observer_store import ObserverStore, observer_dir, observer_enabled

        root = observer_dir()
        if not observer_enabled() and not (root / "state.json").is_file():
            return
        ObserverStore(root).set_paused(bool(paused), reason if paused else "")
    except OSError:
        return


def _touch_presence(paused: bool, reason: str) -> None:
    try:
        from presence_store import PresenceStore, presence_dir, presence_enabled

        root = presence_dir()
        if not presence_enabled() and not (root / "state.json").is_file():
            return
        PresenceStore(root).set_paused(bool(paused), reason if paused else "")
    except OSError:
        return


def shared_is_paused(state: Optional[dict] = None, shared: Optional[dict] = None) -> bool:
    merged = merged_state(state, shared)
    return bool(merged.get("paused")) and str(merged.get("reason") or "") in _MANUAL | {"schedule"}
