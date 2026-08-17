"""Resolve studio model backends from user prefs + companion runtime probe."""
from __future__ import annotations

import os
from typing import Any, Optional

from studio_defaults import clamp_model_map, default_model_map


def _probe_ready(probe: Optional[dict], key: str) -> bool:
    if not isinstance(probe, dict):
        return False
    block = probe.get(key)
    return isinstance(block, dict) and bool(block.get("ready"))


def _ollama_url() -> Optional[str]:
    url = (os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_URL") or "").strip()
    if url:
        return url.rstrip("/")
    return None


def runtime_probe_from_user(user: dict) -> Optional[dict]:
    probe = user.get("companion_runtime_probe")
    return probe if isinstance(probe, dict) else None


def resolve_stt_backend(
    model_map: dict | None,
    probe: Optional[dict] = None,
) -> str:
    """Returns 'local_whisper' or 'cloud_whisper'."""
    chosen = clamp_model_map(model_map)
    pick = chosen.get("stt", "auto")
    local = _probe_ready(probe, "whisper")
    if pick == "cloud_whisper":
        return "cloud_whisper"
    if pick == "local_whisper":
        return "local_whisper" if local else "cloud_whisper"
    return "local_whisper" if local else "cloud_whisper"


def resolve_twin_backend(
    model_map: dict | None,
    probe: Optional[dict] = None,
) -> str:
    """Returns 'ollama' or 'cloud_claude'."""
    chosen = clamp_model_map(model_map)
    pick = chosen.get("twin", "auto")
    local = _probe_ready(probe, "ollama") or bool(_ollama_url())
    if pick == "cloud_claude":
        return "cloud_claude"
    if pick == "ollama":
        return "ollama" if local else "cloud_claude"
    return "ollama" if local else "cloud_claude"


def resolve_tts_backend(
    model_map: dict | None,
    probe: Optional[dict] = None,
    *,
    has_voice_clone: bool = False,
) -> str:
    """Returns one of: elevenlabs, openai_tts, local_piper."""
    chosen = clamp_model_map(model_map)
    pick = chosen.get("tts", "auto")
    piper = _probe_ready(probe, "piper")
    if pick == "elevenlabs":
        return "elevenlabs" if has_voice_clone else "openai_tts"
    if pick == "openai_tts":
        return "openai_tts"
    if pick == "local_piper":
        return "local_piper" if piper else ("elevenlabs" if has_voice_clone else "openai_tts")
    if has_voice_clone:
        return "elevenlabs"
    if piper:
        return "local_piper"
    return "openai_tts"


def effective_model_map(user: dict, probe: Optional[dict] = None) -> dict[str, str]:
    """Human-readable map of what will actually run."""
    raw = clamp_model_map(user.get("studio_models"))
    has_clone = bool(
        (user.get("elevenlabs_voice_id") or "").strip()
        and ((user.get("elevenlabs_api_key") or "").strip() or os.environ.get("ELEVENLABS_API_KEY"))
    )
    return {
        "stt": resolve_stt_backend(raw, probe),
        "twin": resolve_twin_backend(raw, probe),
        "tts": resolve_tts_backend(raw, probe, has_voice_clone=has_clone),
        **{k: raw.get(k, v) for k, v in default_model_map().items() if k not in ("stt", "twin", "tts")},
    }
