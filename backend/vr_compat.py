"""Heirloom Room VR compatibility catalog + OpenXR runtime probe.

The JSON catalog in frontend/src/data/vr-headsets.json is the source of truth
so the in-app coach still renders if the API is down. This module loads that
file, never ships vendor binaries, and only reports filesystem OpenXR state.
"""
from __future__ import annotations

import json
import os
import platform
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "frontend" / "src" / "data" / "vr-headsets.json"

# Official OpenXR active-runtime locations. Do not invent vendor DLLs.
OPENXR_CANDIDATES = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "openxr" / "1" / "active_runtime.json",
    Path.home() / "AppData" / "Local" / "openxr" / "1" / "active_runtime.json",
    Path("/etc/xdg/openxr/1/active_runtime.json"),
    Path.home() / ".config" / "openxr" / "1" / "active_runtime.json",
    Path("/usr/share/openxr/1/active_runtime.json"),
    Path("/usr/local/share/openxr/1/active_runtime.json"),
)


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    raw = CATALOG_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or "headsets" not in data:
        raise RuntimeError("VR catalog is missing headsets")
    return data


def public_catalog() -> dict[str, Any]:
    data = dict(load_catalog())
    data["source"] = "frontend/src/data/vr-headsets.json"
    data["redistributes_binaries"] = False
    return data


def _runtime_name(doc: dict[str, Any], path: Path) -> str:
    runtime = doc.get("runtime") if isinstance(doc, dict) else None
    if isinstance(runtime, dict):
        name = str(runtime.get("name") or "").strip()
        lib = str(runtime.get("library_path") or "")
        if name:
            return name
        lower = lib.lower()
        if "steam" in lower:
            return "SteamVR"
        if "oculus" in lower or "meta" in lower:
            return "Meta OpenXR"
        if "pico" in lower:
            return "PicoStreamingXR"
        if "monado" in lower:
            return "Monado"
        if lib:
            return Path(lib).stem
    return path.name


def read_openxr_runtime(path: Path) -> Optional[dict[str, Any]]:
    try:
        if not path.is_file():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "found": True,
        "runtime_path": str(path),
        "runtime_name": _runtime_name(doc if isinstance(doc, dict) else {}, path),
        "file_format_version": (doc or {}).get("file_format_version") if isinstance(doc, dict) else None,
    }


def probe_openxr() -> dict[str, Any]:
    env_path = (os.environ.get("OPENXR_RUNTIME_JSON") or "").strip()
    ordered: list[Path] = []
    if env_path:
        ordered.append(Path(env_path))
    for candidate in OPENXR_CANDIDATES:
        if str(candidate) in {"", "/openxr/1/active_runtime.json"}:
            continue
        if candidate not in ordered:
            ordered.append(candidate)

    for path in ordered:
        hit = read_openxr_runtime(path)
        if hit:
            hit["via"] = "OPENXR_RUNTIME_JSON" if env_path and path == Path(env_path) else "active_runtime.json"
            hit["candidates"] = [str(p) for p in ordered if str(p)]
            return hit

    return {
        "found": False,
        "runtime_path": None,
        "runtime_name": None,
        "hint": (
            "No active_runtime.json on this machine. On the owner's Windows PC that "
            "file lives at %LOCALAPPDATA%\\openxr\\1\\active_runtime.json after "
            "SteamVR, Meta Horizon Link, or Pico Connect registers a runtime."
        ),
        "candidates": [str(p) for p in ordered if str(p)],
    }


def probe_host() -> dict[str, Any]:
    catalog = load_catalog()
    return {
        "os": platform.system().lower(),
        "openxr": probe_openxr(),
        "architecture": catalog.get("architecture"),
        "legal": catalog.get("legal"),
        "fix_openxr": catalog.get("fix_openxr"),
        "wifi_tips": catalog.get("wifi_tips"),
        "pc_requirements": catalog.get("pc_requirements"),
        "recommended_runtime": "openxr",
        "viewer": {
            "pc": "openxr_via_webxr",
            "headset_browser": "webxr",
            "native_winui": "deferred",
        },
    }


def headset_ids() -> list[str]:
    return [h["id"] for h in load_catalog().get("headsets") or [] if h.get("id")]
