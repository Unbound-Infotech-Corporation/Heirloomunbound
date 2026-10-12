"""Chat provider selection for the Twin Box and the existing cloud path.

``HEIRLOOM_LLM_PROVIDER=ollama`` sends chat completions to Ollama's
OpenAI-compatible endpoint (``/v1/chat/completions``). Unset, empty, and the
existing names (``emergent``, ``anthropic``, ``openai``) keep the Emergent
LlmChat path. An unknown value also stays on that path so a typo cannot
silently drop the cloud provider.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

OLLAMA_PROVIDER = "ollama"
EMERGENT_PROVIDER = "emergent"

# Names that mean "keep the current Emergent / Anthropic / OpenAI transport".
_CLOUD_NAMES = frozenset({"", "emergent", "anthropic", "openai", "cloud", "cloud_claude"})

_usage: ContextVar[Optional[dict[str, Any]]] = ContextVar("heirloom_llm_usage", default=None)


@dataclass(frozen=True)
class ChatCompletion:
    text: str
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


def resolve_llm_provider(raw: Optional[str] = None) -> str:
    """Return ``ollama`` or ``emergent``.

    ``raw`` overrides the environment. Tests pass it directly.
    """
    if raw is None:
        raw = os.environ.get("HEIRLOOM_LLM_PROVIDER", "")
    key = (raw or "").strip().lower()
    if key == OLLAMA_PROVIDER:
        return OLLAMA_PROVIDER
    return EMERGENT_PROVIDER


def uses_ollama(provider: Optional[str] = None) -> bool:
    chosen = provider if provider is not None else resolve_llm_provider()
    return chosen == OLLAMA_PROVIDER


def cloud_provider_name(raw: Optional[str] = None) -> str:
    """The name the operator set, when it is an existing cloud provider.

    Unknown values still *run* as emergent (see ``resolve_llm_provider``).
    This helper is for logs and tests that want the original token.
    """
    if raw is None:
        raw = os.environ.get("HEIRLOOM_LLM_PROVIDER", "")
    key = (raw or "").strip().lower()
    if key in _CLOUD_NAMES or key == OLLAMA_PROVIDER:
        return key or EMERGENT_PROVIDER
    return key


def ollama_base_url(raw: Optional[str] = None) -> str:
    if raw is None:
        raw = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_URL") or "http://127.0.0.1:11434"
    return (raw or "").strip().rstrip("/") or "http://127.0.0.1:11434"


def ollama_model(raw: Optional[str] = None) -> str:
    if raw is None:
        raw = os.environ.get("OLLAMA_TWIN_MODEL", "llama3.1")
    return (raw or "").strip() or "llama3.1"


def openai_chat_url(base_url: str) -> str:
    """Ollama's OpenAI-compatible chat endpoint. Not the native ``/api/chat``."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        base = "http://127.0.0.1:11434"
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def parse_openai_chat(data: Mapping[str, Any]) -> ChatCompletion:
    choices = data.get("choices") or []
    message: Mapping[str, Any] = {}
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            raw_message = first.get("message") or {}
            if isinstance(raw_message, Mapping):
                message = raw_message
    content = message.get("content")
    text = content.strip() if isinstance(content, str) else ""
    usage = data.get("usage") if isinstance(data.get("usage"), Mapping) else {}
    model = data.get("model")
    return ChatCompletion(
        text=text,
        model=model.strip() if isinstance(model, str) else "",
        prompt_tokens=_as_int(usage.get("prompt_tokens")),
        completion_tokens=_as_int(usage.get("completion_tokens")),
    )


def note_usage(completion: ChatCompletion) -> None:
    """Add this completion's tokens onto the current task. Local only."""
    prev = _usage.get() or {}
    prompt = completion.prompt_tokens
    completion_tokens = completion.completion_tokens
    prev_prompt = prev.get("prompt_tokens")
    prev_completion = prev.get("completion_tokens")
    if isinstance(prev_prompt, int) and isinstance(prompt, int):
        prompt = prev_prompt + prompt
    if isinstance(prev_completion, int) and isinstance(completion_tokens, int):
        completion_tokens = prev_completion + completion_tokens
    _usage.set({
        "model": completion.model or prev.get("model") or "",
        "prompt_tokens": prompt,
        "completion_tokens": completion_tokens,
    })


def take_usage() -> dict[str, Any]:
    """Usage noted during this task. Empty when the cloud path did not report any."""
    current = _usage.get()
    if not isinstance(current, dict):
        return {"model": "", "prompt_tokens": None, "completion_tokens": None}
    return {
        "model": current.get("model") or "",
        "prompt_tokens": current.get("prompt_tokens"),
        "completion_tokens": current.get("completion_tokens"),
    }


Poster = Callable[[str, Mapping[str, Any], float], Awaitable[Mapping[str, Any]]]


async def _default_poster(url: str, body: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=dict(body))
    if response.status_code >= 400:
        raise RuntimeError(f"Ollama HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Ollama returned a non-object completion")
    return data


async def complete_openai_chat(
    messages: list[dict[str, str]],
    *,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 120.0,
    poster: Optional[Poster] = None,
) -> ChatCompletion:
    """One non-streaming completion against Ollama's OpenAI-compatible API."""
    url = openai_chat_url(ollama_base_url(base_url))
    body: dict[str, Any] = {
        "model": ollama_model(model),
        "messages": messages,
        "temperature": 0.65,
        "stream": False,
    }
    send = poster or _default_poster
    data = await send(url, body, timeout)
    completed = parse_openai_chat(data)
    if not completed.text:
        raise RuntimeError("Ollama returned empty content")
    if not completed.model:
        completed = ChatCompletion(
            text=completed.text,
            model=str(body["model"]),
            prompt_tokens=completed.prompt_tokens,
            completion_tokens=completed.completion_tokens,
        )
    note_usage(completed)
    return completed
