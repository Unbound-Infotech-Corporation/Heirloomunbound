"""Provider selection stays on the existing cloud path unless ollama is named."""
from __future__ import annotations

import asyncio

from llm_provider import (
    EMERGENT_PROVIDER,
    OLLAMA_PROVIDER,
    complete_openai_chat,
    openai_chat_url,
    parse_openai_chat,
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

    completed = asyncio.run(complete_openai_chat(
        [{"role": "user", "content": "Hi"}],
        model="qwen2.5:3b",
        base_url="http://ollama:11434",
        poster=poster,
    ))
    assert completed.text == "from ollama"
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["body"]["model"] == "qwen2.5:3b"
    assert seen["body"]["stream"] is False
    usage = take_usage()
    assert usage["prompt_tokens"] == 4
    assert usage["completion_tokens"] == 2
    assert usage["model"] == "qwen2.5:3b"
