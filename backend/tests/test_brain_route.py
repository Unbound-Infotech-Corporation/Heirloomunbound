"""LAN brain routing: remote first, short timeout, CPU fallback, no token leak."""
from __future__ import annotations

import asyncio
import json

import pytest

from brain_route import (
    CONNECT_TIMEOUT,
    PROBE_TIMEOUT,
    BrainSettings,
    auth_headers,
    brain_status,
    clear_caches,
    loaded_models_off_gpu,
    normalize_lan_url,
    pick_target,
    prepare_owner_update,
    ps_text_off_gpu,
    public_settings,
    safe_remote_url,
)
from llm_provider import complete_text


def test_lan_url_rules():
    assert normalize_lan_url("http://192.168.0.50:11434") == "http://192.168.0.50:11434"
    assert normalize_lan_url("http://10.1.2.3") == "http://10.1.2.3:11434"
    assert safe_remote_url("http://8.8.8.8:11434") == ""
    with pytest.raises(ValueError):
        normalize_lan_url("http://bigdeal.example:11434")
    with pytest.raises(ValueError):
        normalize_lan_url("http://192.168.0.16:11434")
    with pytest.raises(ValueError):
        normalize_lan_url("http://user:secret@192.168.0.50:11434")


def test_vram_and_processor_mean_partial_gpu():
    assert loaded_models_off_gpu({"models": [{"size": 100, "size_vram": 40}]}) is True
    assert loaded_models_off_gpu({"models": [{"size": 100, "size_vram": 100}]}) is False
    assert loaded_models_off_gpu({"models": []}) is False
    assert ps_text_off_gpu("NAME ID SIZE PROCESSOR\nqwen abc 8GB 100% GPU\n") is False
    assert ps_text_off_gpu("qwen abc 8GB 60%/40% CPU/GPU") is True
    assert ps_text_off_gpu("qwen  100% CPU") is True


def test_public_view_hides_the_token():
    settings = BrainSettings(
        remote_url="http://192.168.0.50:11434",
        remote_model="llama3.3:70b",
        token="sekret-token",
        local_model="qwen2.5:14b",
    )
    view = public_settings(settings, answered="remote", local_gpu="partial")
    blob = json.dumps(view)
    assert "sekret-token" not in blob
    assert view["token_set"] is True
    assert view["host"] == "192.168.0.50"
    assert auth_headers(settings.token) == {"Authorization": "Bearer sekret-token"}


def test_owner_update_rejects_cloud_and_public():
    saved = prepare_owner_update(
        {"url": "http://192.168.0.40:11434", "model": "llama3.3:70b", "token": "abc"},
        None,
    )
    assert saved["url"] == "http://192.168.0.40:11434"
    assert saved["token"] == "abc"
    with pytest.raises(ValueError):
        prepare_owner_update({"url": "https://api.openai.com", "model": "llama3.3:70b"}, None)
    with pytest.raises(ValueError):
        prepare_owner_update({"url": "http://192.168.0.40:11434", "model": "claude-sonnet-4-6"}, None)


def test_partial_gpu_restarts_and_prefers_remote():
    clear_caches()
    settings = BrainSettings(
        remote_url="http://192.168.0.50:11434",
        remote_model="llama3.3:70b",
        token="sek",
        local_url="http://ollama:11434",
        local_model="qwen2.5:14b",
    )
    restarted: list[str] = []
    seen: dict = {}

    async def probe_remote(url, headers, timeout):
        seen["remote_url"] = url
        seen["headers"] = dict(headers)
        seen["timeout"] = timeout
        return True

    async def probe_ps(url, timeout):
        seen["ps_url"] = url
        seen["ps_timeout"] = timeout
        return {"models": [{"name": "qwen2.5:14b", "size": 100, "size_vram": 40}]}

    async def _run():
        return await pick_target(
            settings,
            probe_remote_fn=probe_remote,
            probe_ps_fn=probe_ps,
            restart_fn=lambda: restarted.append("ollama") or "ok",
            now=10.0,
        )

    target = asyncio.run(_run())
    assert target.name == "remote"
    assert target.model == "llama3.3:70b"
    assert target.url == "http://192.168.0.50:11434"
    assert seen["headers"]["Authorization"] == "Bearer sek"
    assert seen["timeout"] == PROBE_TIMEOUT
    assert seen["timeout"] <= 2
    assert CONNECT_TIMEOUT <= 1
    assert seen["ps_url"] == "http://ollama:11434"
    assert restarted == ["ollama"]
    assert target.local_gpu == "partial"
    status = brain_status()
    assert status["answered"] == "remote"
    assert "sek" not in json.dumps(status)


def test_remote_down_falls_back_to_local_after_restart():
    clear_caches()
    settings = BrainSettings(
        remote_url="http://192.168.0.50:11434",
        remote_model="llama3.3:70b",
        local_url="http://127.0.0.1:11434",
        local_model="qwen2.5:14b",
    )
    restarted: list[str] = []

    async def probe_remote(_url, _headers, _timeout):
        return False

    async def probe_ps(_url, _timeout):
        return "qwen  100% CPU"

    async def _run():
        return await pick_target(
            settings,
            probe_remote_fn=probe_remote,
            probe_ps_fn=probe_ps,
            restart_fn=lambda: restarted.append("ollama") or "",
            now=50.0,
        )

    target = asyncio.run(_run())
    assert target.name == "local"
    assert target.model == "qwen2.5:14b"
    assert restarted == ["ollama"]


def test_full_gpu_still_tries_remote_first_without_restart():
    clear_caches()
    settings = BrainSettings(
        remote_url="http://192.168.0.50:11434",
        remote_model="llama3.3:70b",
        local_url="http://ollama:11434",
        local_model="qwen2.5:14b",
    )
    restarted: list[str] = []
    calls = {"n": 0}

    async def probe_remote(_url, _headers, _timeout):
        calls["n"] += 1
        return True

    async def probe_ps(_url, _timeout):
        return {"models": [{"size": 10, "size_vram": 10}]}

    async def _run():
        first = await pick_target(
            settings,
            probe_remote_fn=probe_remote,
            probe_ps_fn=probe_ps,
            restart_fn=lambda: restarted.append("x") or "",
            now=1.0,
        )
        second = await pick_target(
            settings,
            probe_remote_fn=probe_remote,
            probe_ps_fn=probe_ps,
            restart_fn=lambda: restarted.append("x") or "",
            now=2.0,
        )
        return first, second

    first, second = asyncio.run(_run())
    assert first.name == "remote"
    assert second.name == "remote"
    assert restarted == []
    assert calls["n"] == 1


def test_chat_uses_the_remote_brain(monkeypatch):
    clear_caches()
    monkeypatch.setenv("HEIRLOOM_BOX", "1")
    monkeypatch.setenv("HEIRLOOM_BRAIN_URL", "http://192.168.0.40:11434")
    monkeypatch.setenv("HEIRLOOM_BRAIN_MODEL", "llama3.3:70b")
    monkeypatch.setenv("OLLAMA_TWIN_MODEL", "qwen2.5:14b")

    async def probe_remote(_url, _headers, _timeout):
        return True

    async def probe_ps(_url, _timeout):
        return {"models": [{"size": 5, "size_vram": 5}]}

    monkeypatch.setattr("brain_route.probe_remote", probe_remote)
    monkeypatch.setattr("brain_route.probe_local_ps", probe_ps)
    monkeypatch.setattr("brain_route.restart_local", lambda: "")

    seen = {}

    async def poster(url, body, timeout):
        seen["url"] = url
        seen["model"] = body["model"]
        return {
            "model": body["model"],
            "choices": [{"message": {"content": "from bigdeal"}}],
        }

    async def _run():
        return await complete_text("Stay local.", "Hello", poster=poster)

    text = asyncio.run(_run())
    assert text == "from bigdeal"
    assert seen["model"] == "llama3.3:70b"
    assert "192.168.0.40" in seen["url"]
    assert brain_status()["answered"] == "remote"
