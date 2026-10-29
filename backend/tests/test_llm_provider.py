"""Provider selection stays on the existing cloud path unless ollama is named.

A Twin Box (``HEIRLOOM_BOX``) never selects a cloud model or provider.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from llm_provider import (
    BOX_CHAT_MODEL,
    BOX_VISION_MODEL,
    EMERGENT_PROVIDER,
    OLLAMA_PROVIDER,
    CloudAiDisabled,
    complete_openai_chat,
    complete_text,
    complete_vision,
    is_cloud_choice,
    ollama_model,
    ollama_vision_model,
    openai_chat_url,
    parse_openai_chat,
    refuse_cloud,
    resolve_llm_provider,
    take_usage,
    uses_ollama,
)


def test_unset_and_existing_providers_stay_emergent(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_LLM_PROVIDER", raising=False)
    assert resolve_llm_provider() == EMERGENT_PROVIDER
    assert uses_ollama() is False
    for name in ("", "emergent", "anthropic", "openai", "cloud", "cloud_claude", "nope"):
        assert resolve_llm_provider(name) == EMERGENT_PROVIDER
        assert uses_ollama(resolve_llm_provider(name)) is False


def test_ollama_provider_is_explicit(monkeypatch):
    monkeypatch.setenv("HEIRLOOM_LLM_PROVIDER", "ollama")
    assert resolve_llm_provider() == OLLAMA_PROVIDER
    assert uses_ollama() is True
    assert resolve_llm_provider("  Ollama ") == OLLAMA_PROVIDER


def test_openai_compatible_url_is_not_native_chat():
    assert openai_chat_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1/chat/completions"
    assert openai_chat_url("http://ollama:11434/") == "http://ollama:11434/v1/chat/completions"
    assert openai_chat_url("http://ollama:11434/v1") == "http://ollama:11434/v1/chat/completions"
    assert "/api/chat" not in openai_chat_url("http://127.0.0.1:11434")


def test_parse_openai_usage():
    parsed = parse_openai_chat({
        "model": "qwen2.5:7b",
        "choices": [{"message": {"role": "assistant", "content": "  Hello  "}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3},
    })
    assert parsed.text == "Hello"
    assert parsed.model == "qwen2.5:7b"
    assert parsed.prompt_tokens == 11
    assert parsed.completion_tokens == 3


def test_complete_openai_chat_posts_and_notes_tokens():
    seen = {}

    async def poster(url, body, timeout):
        seen["url"] = url
        seen["body"] = dict(body)
        seen["timeout"] = timeout
        return {
            "model": body["model"],
            "choices": [{"message": {"content": "from ollama"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }

    async def _run():
        completed = await complete_openai_chat(
            [{"role": "user", "content": "Hi"}],
            model="qwen2.5:3b",
            base_url="http://ollama:11434",
            poster=poster,
        )
        # Same task as the chat routers, which read usage after the completion.
        return completed, take_usage()

    completed, usage = asyncio.run(_run())
    assert completed.text == "from ollama"
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["body"]["model"] == "qwen2.5:3b"
    assert seen["body"]["stream"] is False
    assert usage["prompt_tokens"] == 4
    assert usage["completion_tokens"] == 2
    assert usage["model"] == "qwen2.5:3b"


def test_box_mode_uses_no_cloud_model_or_provider(monkeypatch):
    monkeypatch.setenv("HEIRLOOM_BOX", "1")
    monkeypatch.setenv("HEIRLOOM_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("OLLAMA_TWIN_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_VISION_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_OBSERVER_MODEL", raising=False)

    assert resolve_llm_provider() == OLLAMA_PROVIDER
    assert uses_ollama() is True
    assert resolve_llm_provider("openai") == OLLAMA_PROVIDER
    assert resolve_llm_provider("gemini") == OLLAMA_PROVIDER
    assert ollama_model() == BOX_CHAT_MODEL
    assert ollama_model("claude-sonnet-4-6") == BOX_CHAT_MODEL
    assert ollama_vision_model() == BOX_VISION_MODEL
    assert ollama_vision_model("gemini-2.5-pro") == BOX_VISION_MODEL
    assert is_cloud_choice("claude-sonnet-4-6", "anthropic") is True
    assert is_cloud_choice(BOX_CHAT_MODEL, "ollama") is False
    with pytest.raises(CloudAiDisabled):
        refuse_cloud("anthropic", "claude-sonnet-4-6", caller="test")

    seen: list[dict] = []

    async def poster(url, body, timeout):
        seen.append({"url": url, "body": json.loads(json.dumps(body))})
        return {
            "model": body["model"],
            "choices": [{"message": {"content": "from the box"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    async def _run():
        chat = await complete_text("Stay local.", "Hello", poster=poster)
        vision = await complete_vision("Look.", "What is this?", "aGVsbG8=", poster=poster)
        return chat, vision

    chat, vision = asyncio.run(_run())
    assert chat == "from the box"
    assert vision == "from the box"
    assert [row["body"]["model"] for row in seen] == [BOX_CHAT_MODEL, BOX_VISION_MODEL]
    blob = json.dumps(seen).lower()
    assert all(row["url"].rstrip("/").endswith("/v1/chat/completions") for row in seen)
    for banned in ("claude", "anthropic", "openai", "gemini", "gpt-"):
        assert banned not in blob
