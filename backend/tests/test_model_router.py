"""Tests for studio model routing + brain pack assembly."""
from __future__ import annotations

import pytest

from model_router import (
    effective_model_map,
    resolve_avatar_backend,
    resolve_stt_backend,
    resolve_tts_backend,
    resolve_twin_backend,
)
from twin_runtime import _score_entry, build_brain_pack, history_turns


def test_resolve_stt_prefers_local_when_whisper_ready():
    probe = {"whisper": {"ready": True}}
    assert resolve_stt_backend({"stt": "auto"}, probe) == "local_whisper"
    assert resolve_stt_backend({"stt": "local_whisper"}, probe) == "local_whisper"
    assert resolve_stt_backend({"stt": "cloud_whisper"}, probe) == "cloud_whisper"


def test_resolve_twin_ollama_when_probe_ready():
    probe = {"ollama": {"ready": True, "models": ["llama3.1"]}}
    assert resolve_twin_backend({"twin": "auto"}, probe) == "ollama"
    assert resolve_twin_backend({"twin": "ollama"}, probe) == "ollama"
    assert resolve_twin_backend({"twin": "cloud_claude"}, probe) == "cloud_claude"


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


def test_effective_model_map_includes_clone():
    user = {
        "studio_models": {"stt": "auto", "twin": "auto", "tts": "auto"},
        "elevenlabs_voice_id": "voice123",
        "elevenlabs_api_key": "key",
    }
    probe = {"whisper": {"ready": True}, "ollama": {"ready": True}}
    eff = effective_model_map({**user, "companion_runtime_probe": probe}, probe)
    assert eff["stt"] == "local_whisper"
    assert eff["twin"] == "ollama"
    assert eff["tts"] == "elevenlabs"


def test_score_entry_ranks_keyword_hits():
    entry = {"title": "Vermont childhood", "content": "I grew up in Vermont near the lake.", "tags": [], "type": "story"}
    assert _score_entry(entry, ["vermont", "childhood"]) > _score_entry(entry, ["california"])


@pytest.mark.asyncio
async def test_build_brain_pack_shape(monkeypatch):
    async def fake_enabled(_uid):
        return set()

    async def fake_passages(_uid, query_hint="", limit=8):
        return []

    async def fake_archive(_uid, query_hint=""):
        return "[MEMORY] Home\nVermont"

    async def fake_skills(_uid):
        return ""

    async def fake_memory(_uid, query_hint=""):
        return {"identity_facts": [], "episodes": []}

    async def fake_persona(_uid, _user):
        return None

    import abilities as ab
    import twin_runtime as tr
    from routers import memory as mem

    monkeypatch.setattr(ab, "enabled_ability_ids", fake_enabled)
    monkeypatch.setattr(tr, "archive_blob", fake_archive)
    monkeypatch.setattr(tr, "archive_passages", fake_passages)
    monkeypatch.setattr(tr, "skills_blob", fake_skills)
    monkeypatch.setattr(mem, "build_memory_pack", fake_memory)
    monkeypatch.setattr(tr, "get_active_persona", fake_persona)

    user = {"user_id": "u1", "name": "Alex", "studio_models": {"twin": "cloud_claude"}}
    conv = {"conversation_id": "c1", "messages": history_turns([{"role": "user", "content": "hi"}])}
    pack = await build_brain_pack(user, "where did I grow up?", conversation=conv)
    assert "Alex" in pack.system
    assert pack.conversation_id == "c1"
    assert pack.twin_backend in ("cloud_claude", "ollama")
    assert "faithful continuation" in pack.system.lower()


@pytest.mark.asyncio
async def test_build_brain_pack_assistant_is_copilot(monkeypatch):
    async def fake_enabled(_uid):
        return {"pc_control", "web"}

    async def fake_passages(_uid, query_hint="", limit=8):
        return []

    async def fake_archive(_uid, query_hint=""):
        return ""

    async def fake_skills(_uid):
        return ""

    async def fake_memory(_uid, query_hint=""):
        return {"identity_facts": [], "episodes": []}

    async def fake_persona(_uid, _user):
        return None

    import abilities as ab
    import twin_runtime as tr
    from routers import memory as mem

    monkeypatch.setattr(ab, "enabled_ability_ids", fake_enabled)
    monkeypatch.setattr(tr, "archive_blob", fake_archive)
    monkeypatch.setattr(tr, "archive_passages", fake_passages)
    monkeypatch.setattr(tr, "skills_blob", fake_skills)
    monkeypatch.setattr(mem, "build_memory_pack", fake_memory)
    monkeypatch.setattr(tr, "get_active_persona", fake_persona)

    user = {"user_id": "u1", "name": "Alex", "studio_models": {"twin": "cloud_claude"}}
    conv = {"conversation_id": "c1", "messages": []}
    twin = await build_brain_pack(user, "open notepad", conversation=conv, role="twin")
    assist = await build_brain_pack(user, "open notepad", conversation=conv, role="assistant")
    assert "not their digital twin" in assist.system.lower()
    assert "open_on_pc" in assist.system
    assert "open_on_pc" not in twin.system
    assert "faithful continuation" in twin.system.lower()
