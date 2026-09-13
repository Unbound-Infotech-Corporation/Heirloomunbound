"""Install-size catalog for the Heirloom Unbound companion.

Mirrors backend/studio_setup.py so the zip still works when the live API
lags GitHub. Aliases keep lite/full/max rows resolving.
"""
from __future__ import annotations

from typing import Any, Optional

PROFILE_ALIASES = {
    "lite": "small",
    "full": "medium",
    "max": "large",
    "studio": "large",
}

DEDICATED_RECOMMEND_GB = 180
LARGE_RECOMMEND_GB = 100
MEDIUM_RECOMMEND_GB = 40

SPACE_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "id": "small",
        "label": "Small",
        "gb_min": 5,
        "gb_max": 12,
        "vault_tier": "lite",
        "provision_features": ("stt", "tts"),
        "whisper": "base",
        "gpu_required": False,
        "warm_engines": (),
        "machine_role": False,
        "summary": "App, Whisper, Piper, lite vault. Twin/TTS/avatar stay cloud Auto.",
    },
    {
        "id": "medium",
        "label": "Medium",
        "gb_min": 40,
        "gb_max": 70,
        "vault_tier": "partial",
        "provision_features": ("stt", "tts", "twin", "voice_clone"),
        "whisper": "small",
        "gpu_required": False,
        "warm_engines": ("ollama",),
        "machine_role": False,
        "summary": "Small plus Ollama llama3.1 and one voice-clone path.",
    },
    {
        "id": "large",
        "label": "Large",
        "gb_min": 100,
        "gb_max": 160,
        "vault_tier": "full",
        "provision_features": (
            "stt",
            "tts",
            "twin",
            "vision",
            "voicebox",
            "qwen3_tts",
            "latentsync",
            "avatar",
        ),
        "whisper": "large-v3",
        "gpu_required": True,
        "warm_engines": ("ollama", "voicebox", "qwen3_tts", "latentsync"),
        "machine_role": False,
        "summary": "Whisper large-v3, stronger twin + vision, Voicebox and Qwen3-TTS, LatentSync.",
    },
    {
        "id": "dedicated",
        "label": "Dedicated PC",
        "gb_min": 200,
        "gb_max": 0,
        "vault_tier": "full",
        "provision_features": (
            "stt",
            "tts",
            "twin",
            "vision",
            "voicebox",
            "qwen3_tts",
            "latentsync",
            "avatar",
            "machine_role",
        ),
        "whisper": "large-v3",
        "gpu_required": True,
        "warm_engines": ("ollama", "voicebox", "qwen3_tts", "latentsync"),
        "machine_role": True,
        "summary": "Large plus a machine role: startup, vault drive, warm engines.",
    },
)

_CANONICAL = {p["id"] for p in SPACE_PROFILES}


def normalize_profile_id(profile_id: str | None) -> str:
    raw = str(profile_id or "").strip().lower()
    if raw in PROFILE_ALIASES:
        return PROFILE_ALIASES[raw]
    if raw in _CANONICAL:
        return raw
    return "medium"


def space_profile(profile_id: str | None) -> dict[str, Any]:
    wanted = normalize_profile_id(profile_id)
    for p in SPACE_PROFILES:
        if p["id"] == wanted:
            return p
    return next(p for p in SPACE_PROFILES if p["id"] == "medium")


def recommend_profile(free_gb: float | int | None) -> str:
    try:
        free = float(free_gb) if free_gb is not None else 0.0
    except (TypeError, ValueError):
        free = 0.0
    if free >= DEDICATED_RECOMMEND_GB:
        return "dedicated"
    if free >= LARGE_RECOMMEND_GB:
        return "large"
    if free >= MEDIUM_RECOMMEND_GB:
        return "medium"
    return "small"


def provision_features(profile_id: str | None) -> list[str]:
    return list(space_profile(profile_id)["provision_features"])


def provision_manifest(profile_id: str | None) -> dict[str, Any]:
    profile = space_profile(profile_id)
    return {
        "id": profile["id"],
        "label": profile["label"],
        "gpu_required": bool(profile.get("gpu_required")),
        "whisper": profile.get("whisper") or "base",
        "vault_tier": profile.get("vault_tier") or "lite",
        "features": list(profile["provision_features"]),
        "warm_engines": list(profile.get("warm_engines") or ()),
        "machine_role": bool(profile.get("machine_role")),
        "coach_on_engine_failure": True,
        "abort_on_engine_failure": False,
        "pinokio": False,
    }


def radio_copy() -> list[tuple[str, str]]:
    """(id, radio label) for the first-run wizard."""
    rows = []
    for p in SPACE_PROFILES:
        span = f"{p['gb_min']}–{p['gb_max']} GB" if p["gb_max"] else f"{p['gb_min']} GB+"
        rows.append((p["id"], f"{p['label']} · {span} · {p['summary']}"))
    return rows
