"""Cold local-model wait. No sockets and no remote brain."""
from __future__ import annotations

import asyncio
import json

import pytest

from brain_council import (
    COLD_LOAD_SECONDS,
    DRAFT_TIMEOUT,
    clear_answer_meta,
    complete_turn,
    describe_draft_error,
    local_preload_target,
)
from brain_route import clear_caches


def _env(monkeypatch) -> None:
    monkeypatch.setenv("HEIRLOOM_BOX", "1")
    monkeypatch.setenv("HEIRLOOM_BRAIN_DISABLE_STORE", "1")
    monkeypatch.setenv("OLLAMA_TWIN_MODEL", "qwen2.5:14b")
    monkeypatch.setenv("HEIRLOOM_BRAIN_STRATEGY", "single")
    monkeypatch.delenv("HEIRLOOM_BRAIN_URL", raising=False)
    monkeypatch.delenv("HEIRLOOM_BRAIN_TOKEN", raising=False)
    monkeypatch.delenv("HEIRLOOM_BRAIN_MODEL", raising=False)
    clear_caches()
    clear_answer_meta()


def test_draft_timeout_covers_a_measured_cold_14b_load():
    assert COLD_LOAD_SECONDS >= 56
    assert DRAFT_TIMEOUT >= 90
    assert DRAFT_TIMEOUT > COLD_LOAD_SECONDS


def test_preload_stays_on_the_local_model_and_skips_a_remote_brain():
    target = local_preload_target(
        box=True,
        remote_url="http://192.168.0.60:11434",
        local_url="http://127.0.0.1:11434",
        local_model="qwen2.5:14b",
    )
    assert target == ("http://127.0.0.1:11434", "qwen2.5:14b")
    assert "192.168.0.60" not in target[0]
    assert local_preload_target(
        box=False,
        remote_url="http://192.168.0.60:11434",
        local_url="http://127.0.0.1:11434",
        local_model="qwen2.5:14b",
    ) is None
    assert describe_draft_error(TimeoutError()) == "the local model is still loading"


def test_warm_chat_uses_the_longer_cap_but_returns_immediately(monkeypatch):
    _env(monkeypatch)
    seen = {}

    async def poster(url, body, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        assert "192.168.0.60" not in url
        assert "SECRET VAULT" not in json.dumps(body)
        return {"model": body["model"], "choices": [{"message": {"content": "Four."}}]}

    async def _run():
        return await complete_turn(
            [{"role": "user", "content": "thanks"}],
            "thanks",
            audience="owner",
            poster=poster,
        )

    outcome = asyncio.run(_run())
    assert outcome.text == "Four."
    assert seen["timeout"] == DRAFT_TIMEOUT
    assert seen["timeout"] > COLD_LOAD_SECONDS


def test_cold_timeout_is_a_loading_error_not_an_empty_502(monkeypatch):
    _env(monkeypatch)

    async def poster(url, body, timeout):
        assert timeout == DRAFT_TIMEOUT
        raise TimeoutError()

    async def _run():
        await complete_turn(
            [{"role": "user", "content": "thanks"}],
            "thanks",
            audience="owner",
            poster=poster,
        )

    with pytest.raises(RuntimeError) as raised:
        asyncio.run(_run())
    assert "still loading" in str(raised.value)
    assert str(raised.value) != "Local twin (Ollama) failed:"
