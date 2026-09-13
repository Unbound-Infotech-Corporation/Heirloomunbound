"""Heirloom Unbound local-voice routing + ticket redaction — no live API."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine_probes import probe_qwen3_tts, probe_voicebox
from model_router import resolve_avatar_backend, resolve_tts_backend
from studio_defaults import clamp_compute, clamp_model_map, default_model_map
from support_ticket import build_ticket_snapshot, redact_text


def test_resolve_tts_auto_prefers_voicebox():
    probe = {"voicebox": {"ready": True, "url": "http://127.0.0.1:17493"}, "qwen3_tts": {"ready": True}}
    assert resolve_tts_backend({"tts": "auto"}, probe, has_voice_clone=True) == "voicebox"
    down = {"voicebox": {"ready": False}, "qwen3_tts": {"ready": True}}
    assert resolve_tts_backend({"tts": "auto"}, down, has_voice_clone=True) == "qwen3_tts"
    none = {"voicebox": {"ready": False}, "qwen3_tts": {"ready": False}, "piper": {"ready": True}}
    assert resolve_tts_backend({"tts": "auto"}, none, has_voice_clone=True) == "elevenlabs"
    assert resolve_tts_backend({"tts": "auto"}, none, has_voice_clone=False) == "local_piper"
    assert resolve_tts_backend({"tts": "voicebox"}, none, has_voice_clone=False) == "local_piper"
    assert resolve_tts_backend({"tts": "openai_tts"}, probe, has_voice_clone=True) == "openai_tts"


def test_resolve_avatar_auto_prefers_latentsync():
    probe = {"latentsync": {"ready": True}, "musetalk": {"ready": True}}
    assert resolve_avatar_backend({"avatar": "auto"}, probe, has_did=True) == "latentsync"
    down = {"latentsync": {"ready": False}, "musetalk": {"ready": True}}
    assert resolve_avatar_backend({"avatar": "auto"}, down, has_did=True) == "musetalk"
    none = {}
    assert resolve_avatar_backend({"avatar": "auto"}, none, has_did=True) == "did"
    assert resolve_avatar_backend({"avatar": "auto"}, none, has_did=False) == "waveform"
    assert resolve_avatar_backend({"avatar": "latentsync"}, none, has_did=True) == "waveform"


def test_clamp_model_map_accepts_local_voice_backends():
    out = clamp_model_map({"tts": "voicebox", "avatar": "latentsync", "twin": "ollama"})
    assert out["tts"] == "voicebox"
    assert out["avatar"] == "latentsync"
    qwen = clamp_model_map({"tts": "qwen3_tts", "avatar": "musetalk"})
    assert qwen["tts"] == "qwen3_tts"
    assert qwen["avatar"] == "musetalk"
    rejected = clamp_model_map({"tts": "pinokio"})
    assert rejected["tts"] == default_model_map()["tts"]


def test_clamp_compute_keeps_engine_urls():
    engines = clamp_compute(
        {
            "mode": "local",
            "remote": {
                "voicebox_url": "http://127.0.0.1:17493",
                "qwen3_tts_url": "http://10.0.0.8:8001",
                "latentsync_url": "ftp://bad",
            },
        }
    )
    assert engines["remote"]["voicebox_url"] == "http://127.0.0.1:17493"
    assert engines["remote"]["qwen3_tts_url"] == "http://10.0.0.8:8001"
    assert engines["remote"]["latentsync_url"].startswith("http://127.0.0.1:7860")
    assert engines["remote"]["ollama_url"].startswith("http://")


def test_ticket_redaction_strips_secrets():
    raw = "here is sk_live_abcdefghijklmnop and Authorization: Bearer abc.def.ghi"
    cleaned = redact_text(raw)
    assert "sk_live_abcdefghijklmnop" not in cleaned
    assert "Bearer abc.def.ghi" not in cleaned
    assert "[redacted]" in cleaned
    snap = build_ticket_snapshot(
        os_name="Linux",
        build_id="dev",
        companion_version="0.5.0",
        probe={
            "voicebox": {"ready": False, "url": "http://127.0.0.1:17493", "detail": "refused"},
            "elevenlabs_api_key": "sk_should_not_appear",
            "journal": "grandma's story",
        },
        model_map={"tts": "auto"},
        compute={"mode": "local", "remote": {"voicebox_url": "http://127.0.0.1:17493"}},
        log_lines=["Authorization: Bearer secret-token-value", "probe ok"],
    )
    blob = str(snap)
    assert "sk_should_not_appear" not in blob
    assert "grandma" not in blob
    assert "secret-token-value" not in blob
    assert snap["probe"]["voicebox"]["url"] == "http://127.0.0.1:17493"
    assert snap["product"] == "Heirloom Unbound"


def test_engine_probes_refused_without_crash():
    vb = probe_voicebox("http://127.0.0.1:1")
    q3 = probe_qwen3_tts("http://127.0.0.1:1")
    assert vb["ready"] is False
    assert q3["ready"] is False
    assert "url" in vb and "detail" in vb
    assert "url" in q3 and "detail" in q3
