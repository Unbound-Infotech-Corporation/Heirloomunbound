"""Resolve studio model backends from user prefs + companion runtime probe."""
from __future__ import annotations

import os
from typing import Optional

from studio_defaults import clamp_model_map, default_model_map


def _probe_ready(probe: Optional[dict], key: str) -> bool:
    if not isinstance(probe, dict):
        return False
    block = probe.get(key)
    return isinstance(block, dict) and bool(block.get("ready"))


def _ollama_url(user: dict | None = None) -> Optional[str]:
    if user:
        from studio_compute import resolve_ollama_url

        resolved = resolve_ollama_url(user)
        if resolved:
            return resolved
    url = (os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_URL") or "").strip()
    if url:
        return url.rstrip("/")
    return None


def _ollama_available(user: dict | None, probe: Optional[dict]) -> bool:
    from local_inference import ollama_ready_at

    url = _ollama_url(user)
    if url:
        return ollama_ready_at(url)
    return _probe_ready(probe, "ollama")


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
    *,
    user: dict | None = None,
) -> str:
    """Returns 'ollama' or 'cloud_claude'."""
    chosen = clamp_model_map(model_map)
    pick = chosen.get("twin", "auto")
    local = _ollama_available(user, probe)
    if pick == "cloud_claude":
        return "cloud_claude"
    if pick == "ollama":
        return "ollama" if local else "cloud_claude"
    return "ollama" if local else "cloud_claude"


def _tts_fallback(
    probe: Optional[dict],
    *,
    has_voice_clone: bool,
    skip: set[str] | None = None,
) -> str:
    """Auto-order chain used by Auto and by explicit picks that are not ready."""
    ignore = skip or set()
    if "voicebox" not in ignore and _probe_ready(probe, "voicebox"):
        return "voicebox"
    if "qwen3_tts" not in ignore and _probe_ready(probe, "qwen3_tts"):
        return "qwen3_tts"
    if "elevenlabs" not in ignore and has_voice_clone:
        return "elevenlabs"
    if "local_piper" not in ignore and _probe_ready(probe, "piper"):
        return "local_piper"
    return "openai_tts"


def resolve_tts_backend(
    model_map: dict | None,
    probe: Optional[dict] = None,
    *,
    has_voice_clone: bool = False,
) -> str:
    """Returns one of: voicebox, qwen3_tts, elevenlabs, openai_tts, local_piper.

    Auto order: Voicebox → Qwen3-TTS → ElevenLabs (if clone keyed) → Piper → OpenAI.
    Explicit picks fall back along the same chain when the probe is not ready.
    """
    chosen = clamp_model_map(model_map)
    pick = chosen.get("tts", "auto")
    if pick == "voicebox":
        return "voicebox" if _probe_ready(probe, "voicebox") else _tts_fallback(
            probe, has_voice_clone=has_voice_clone, skip={"voicebox"}
        )
    if pick == "qwen3_tts":
        return "qwen3_tts" if _probe_ready(probe, "qwen3_tts") else _tts_fallback(
            probe, has_voice_clone=has_voice_clone, skip={"qwen3_tts"}
        )
    if pick == "elevenlabs":
        return "elevenlabs" if has_voice_clone else _tts_fallback(
            probe, has_voice_clone=False, skip={"elevenlabs"}
        )
    if pick == "openai_tts":
        return "openai_tts"
    if pick == "local_piper":
        return "local_piper" if _probe_ready(probe, "piper") else _tts_fallback(
            probe, has_voice_clone=has_voice_clone, skip={"local_piper"}
        )
    return _tts_fallback(probe, has_voice_clone=has_voice_clone)


def resolve_avatar_backend(
    model_map: dict | None,
    probe: Optional[dict] = None,
    *,
    has_did: bool = False,
) -> str:
    """Returns one of: latentsync, musetalk, waveform, did.

    Auto order: LatentSync → MuseTalk → waveform → D-ID.
    Explicit local picks fall back when the probe is not ready.
    """
    chosen = clamp_model_map(model_map)
    pick = chosen.get("avatar", "auto")
    latentsync = _probe_ready(probe, "latentsync")
    musetalk = _probe_ready(probe, "musetalk")
    if pick == "latentsync":
        if latentsync:
            return "latentsync"
        if musetalk:
            return "musetalk"
        return "waveform"
    if pick == "musetalk":
        if musetalk:
            return "musetalk"
        if latentsync:
            return "latentsync"
        return "waveform"
    if pick == "did":
        return "did" if has_did else "waveform"
    if pick == "waveform":
        return "waveform"
    if latentsync:
        return "latentsync"
    if musetalk:
        return "musetalk"
    if has_did:
        return "did"
    return "waveform"


def effective_model_map(user: dict, probe: Optional[dict] = None) -> dict[str, str]:
    """Human-readable map of what will actually run."""
    raw = clamp_model_map(user.get("studio_models"))
    has_clone = bool(
        (user.get("elevenlabs_voice_id") or "").strip()
        and ((user.get("elevenlabs_api_key") or "").strip() or os.environ.get("ELEVENLABS_API_KEY"))
    )
    has_did = bool(
        (user.get("d_id_api_key") or "").strip() or os.environ.get("D_ID_API_KEY")
    )
    return {
        "stt": resolve_stt_backend(raw, probe),
        "twin": resolve_twin_backend(raw, probe, user=user),
        "tts": resolve_tts_backend(raw, probe, has_voice_clone=has_clone),
        "avatar": resolve_avatar_backend(raw, probe, has_did=has_did),
        **{k: raw.get(k, v) for k, v in default_model_map().items() if k not in ("stt", "twin", "tts", "avatar")},
    }
