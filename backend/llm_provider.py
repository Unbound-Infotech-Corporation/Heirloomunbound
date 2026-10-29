"""Chat provider selection for the Twin Box and the existing cloud path.

``HEIRLOOM_LLM_PROVIDER=ollama`` sends chat completions to Ollama's
OpenAI-compatible endpoint (``/v1/chat/completions``). Unset, empty, and the
existing names (``emergent``, ``anthropic``, ``openai``) keep the Emergent
LlmChat path when this process is not a Twin Box. An unknown value also stays
on that path so a typo cannot silently drop the cloud provider.

``HEIRLOOM_BOX`` forces the local Ollama service. Chat uses ``qwen2.5:14b``
unless ``OLLAMA_TWIN_MODEL`` names another local tag. Vision uses
``qwen2.5vl:7b``. The host is ``OLLAMA_BASE_URL`` or ``OLLAMA_URL``. A cloud
model or provider is refused, logged, and never called.
"""
from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

OLLAMA_PROVIDER = "ollama"
EMERGENT_PROVIDER = "emergent"
BOX_CHAT_MODEL = "qwen2.5:14b"
BOX_VISION_MODEL = "qwen2.5vl:7b"

# Names that mean "keep the current Emergent / Anthropic / OpenAI transport"
# when the process is not a Twin Box.
_CLOUD_NAMES = frozenset({"", "emergent", "anthropic", "openai", "cloud", "cloud_claude"})
_CLOUD_PROVIDERS = frozenset({
    "anthropic",
    "openai",
    "gemini",
    "google",
    "emergent",
    "vertex_ai",
    "bedrock",
    "azure",
    "fal",
    "elevenlabs",
    "litellm",
})
_CLOUD_MODEL_MARKERS = (
    "claude",
    "gpt-",
    "gpt-4",
    "gpt-3",
    "gemini",
    "sonnet",
    "opus",
    "haiku",
    "whisper-1",
    "tts-1",
    "dall-e",
    "anthropic/",
    "openai/",
)

_logged_cloud_override = False
_guard_installed = False

_usage: ContextVar[Optional[dict[str, Any]]] = ContextVar("heirloom_llm_usage", default=None)


@dataclass(frozen=True)
class ChatCompletion:
    text: str
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


class CloudAiDisabled(RuntimeError):
    """A cloud model or provider was requested while HEIRLOOM_BOX is set."""


def box_mode() -> bool:
    return (os.environ.get("HEIRLOOM_BOX") or "").strip().lower() in {"1", "true", "yes", "on"}


def is_cloud_choice(model: str = "", provider: str = "") -> bool:
    """True when the model tag or provider names a paid or hosted AI service."""
    provider_name = (provider or "").strip().lower()
    model_name = (model or "").strip().lower()
    if provider_name in _CLOUD_PROVIDERS:
        return True
    if model_name.startswith("ollama/") or model_name.startswith("ollama_chat/"):
        return False
    return any(marker in model_name for marker in _CLOUD_MODEL_MARKERS)


def refuse_cloud(provider: str, model: str, *, caller: str) -> None:
    """Log and raise when a Twin Box is about to call a cloud model.

    Local tags return without doing anything, including when the box is off,
    so the web deployment can still name its existing provider.
    """
    if not box_mode() or not is_cloud_choice(model, provider):
        return
    logger.error(
        "HEIRLOOM_BOX refused cloud AI caller=%s provider=%s model=%s",
        caller,
        provider,
        model,
    )
    raise CloudAiDisabled(f"cloud AI is disabled on this box ({caller})")


def prefer_local() -> bool:
    """Ollama serves this turn. Always true on a Twin Box."""
    return box_mode() or uses_ollama()


def resolve_llm_provider(raw: Optional[str] = None) -> str:
    """Return ``ollama`` or ``emergent``.

    ``raw`` overrides the environment. Tests pass it directly.
    A Twin Box always resolves to Ollama, and a cloud name is logged once.
    """
    if raw is None:
        raw = os.environ.get("HEIRLOOM_LLM_PROVIDER", "")
    key = (raw or "").strip().lower()
    if box_mode():
        global _logged_cloud_override
        if key and key != OLLAMA_PROVIDER and not _logged_cloud_override:
            logger.error("HEIRLOOM_BOX ignored cloud provider %r; using ollama", key)
            _logged_cloud_override = True
        install_box_guard()
        return OLLAMA_PROVIDER
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
        raw = os.environ.get("OLLAMA_TWIN_MODEL", "")
        if not (raw or "").strip():
            raw = BOX_CHAT_MODEL if box_mode() else "llama3.1"
    chosen = (raw or "").strip() or (BOX_CHAT_MODEL if box_mode() else "llama3.1")
    if box_mode() and is_cloud_choice(chosen, ""):
        logger.error("HEIRLOOM_BOX refused cloud model %s; using %s", chosen, BOX_CHAT_MODEL)
        return BOX_CHAT_MODEL
    return chosen


def ollama_vision_model(raw: Optional[str] = None) -> str:
    if raw is None:
        raw = os.environ.get("OLLAMA_VISION_MODEL") or os.environ.get("OLLAMA_OBSERVER_MODEL") or ""
    chosen = (raw or "").strip() or BOX_VISION_MODEL
    if box_mode() and is_cloud_choice(chosen, ""):
        logger.error("HEIRLOOM_BOX refused cloud vision model %s; using %s", chosen, BOX_VISION_MODEL)
        return BOX_VISION_MODEL
    return chosen


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
    model_name = ollama_model(model)
    refuse_cloud("ollama", model_name, caller="complete_openai_chat")
    url = openai_chat_url(ollama_base_url(base_url))
    body: dict[str, Any] = {
        "model": model_name,
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


def _prior_turns(history: Optional[list]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in history or []:
        if not isinstance(item, Mapping):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            rows.append({"role": str(role), "content": content})
    return rows


def _reply_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content.strip()
    return str(result or "").strip()


async def complete_text(
    system: str,
    user: str,
    *,
    history: Optional[list] = None,
    session_id: str = "heirloom",
    model: Optional[str] = None,
    poster: Optional[Poster] = None,
) -> str:
    """One chat completion. A Twin Box always uses the local Ollama chat model."""
    prior = _prior_turns(history)
    if prefer_local():
        messages: list[dict[str, str]] = []
        if (system or "").strip():
            messages.append({"role": "system", "content": system})
        messages.extend(prior)
        messages.append({"role": "user", "content": user})
        completed = await complete_openai_chat(messages, model=model, poster=poster)
        return completed.text
    refuse_cloud("anthropic", "claude-sonnet-4-6", caller=session_id or "complete_text")
    from deps import EMERGENT_LLM_KEY
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    chat = (
        LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id or "heirloom",
            system_message=system or "",
            initial_messages=prior,
        )
        .with_model("anthropic", "claude-sonnet-4-6")
    )
    text = _reply_text(await chat.send_message(UserMessage(text=user)))
    if not text:
        raise RuntimeError("model returned empty content")
    return text


def _image_b64(image_b64: str) -> str:
    raw = (image_b64 or "").strip()
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    return raw


async def complete_vision(
    system: str,
    prompt: str,
    image_b64: str,
    *,
    mime: str = "image/jpeg",
    session_id: str = "heirloom-vision",
    poster: Optional[Poster] = None,
) -> str:
    """Describe an image. A Twin Box uses ``qwen2.5vl:7b`` on the local Ollama host."""
    raw = _image_b64(image_b64)
    if prefer_local():
        model_name = ollama_vision_model()
        refuse_cloud("ollama", model_name, caller="complete_vision")
        messages: list[dict[str, Any]] = []
        if (system or "").strip():
            messages.append({"role": "system", "content": system})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{raw}"}},
            ],
        })
        url = openai_chat_url(ollama_base_url())
        body = {"model": model_name, "messages": messages, "temperature": 0.2, "stream": False}
        send = poster or _default_poster
        data = await send(url, body, 120.0)
        completed = parse_openai_chat(data)
        if not completed.text:
            raise RuntimeError("Ollama vision returned empty content")
        if not completed.model:
            completed = ChatCompletion(text=completed.text, model=model_name)
        note_usage(completed)
        return completed.text
    refuse_cloud("anthropic", "claude-sonnet-4-6", caller=session_id or "complete_vision")
    from deps import EMERGENT_LLM_KEY
    from emergentintegrations.llm.chat import ImageContent, LlmChat, StreamDone, TextDelta, UserMessage

    chat = (
        LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id or "heirloom-vision",
            system_message=system or "You look at an image and answer directly.",
        )
        .with_model("anthropic", "claude-sonnet-4-6")
    )
    text = ""
    async for ev in chat.stream_message(
        UserMessage(text=prompt, file_contents=[ImageContent(image_base64=raw)])
    ):
        if isinstance(ev, TextDelta):
            text += ev.content
        elif isinstance(ev, StreamDone):
            break
    text = text.strip()
    if not text:
        raise RuntimeError("model returned empty content")
    return text


def _refuse_call(caller: str, args: tuple, kwargs: dict) -> None:
    model = kwargs.get("model")
    if model is None and args and isinstance(args[0], str):
        model = args[0]
    model_text = str(model or "")
    provider = str(kwargs.get("custom_llm_provider") or kwargs.get("provider") or "")
    lowered = model_text.lower()
    if not provider:
        if lowered.startswith("anthropic/") or "claude" in lowered:
            provider = "anthropic"
        elif lowered.startswith("openai/") or lowered.startswith("gpt"):
            provider = "openai"
        elif "gemini" in lowered:
            provider = "gemini"
    refuse_cloud(provider, model_text, caller=caller)


def _wrap_callable(original: Callable[..., Any], caller: str) -> Callable[..., Any]:
    if getattr(original, "_heirloom_guard", False):
        return original

    if _is_async(original):
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            _refuse_call(caller, args, kwargs)
            return await original(*args, **kwargs)
    else:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            _refuse_call(caller, args, kwargs)
            return original(*args, **kwargs)

    setattr(wrapped, "_heirloom_guard", True)
    return wrapped


def _is_async(fn: Callable[..., Any]) -> bool:
    import asyncio

    return asyncio.iscoroutinefunction(fn)


def _patch_attr(owner: Any, name: str, caller: str) -> None:
    original = getattr(owner, name, None)
    if original is None or getattr(original, "_heirloom_guard", False):
        return
    setattr(owner, name, _wrap_callable(original, caller))


def _patch_litellm() -> None:
    try:
        import litellm
    except Exception:
        return
    _patch_attr(litellm, "completion", "litellm.completion")
    _patch_attr(litellm, "acompletion", "litellm.acompletion")


def _patch_llmchat() -> None:
    try:
        from emergentintegrations.llm.chat import LlmChat
    except Exception:
        return
    original = getattr(LlmChat, "with_model", None)
    if original is None or getattr(original, "_heirloom_guard", False):
        return

    def with_model(self: Any, provider: str, model: str, *args: Any, **kwargs: Any) -> Any:
        refuse_cloud(str(provider), str(model), caller="LlmChat.with_model")
        return original(self, provider, model, *args, **kwargs)

    setattr(with_model, "_heirloom_guard", True)
    LlmChat.with_model = with_model  # type: ignore[method-assign]


def _patch_openai_speech() -> None:
    try:
        from emergentintegrations.llm import openai as openai_llm
    except Exception:
        return
    for cls_name, method in (
        ("OpenAISpeechToText", "transcribe"),
        ("OpenAITextToSpeech", "generate_speech"),
    ):
        cls = getattr(openai_llm, cls_name, None)
        if cls is None:
            continue
        _patch_attr(cls, method, f"{cls_name}.{method}")


def _patch_sdk_init(module_name: str, class_name: str, provider: str) -> None:
    try:
        module = __import__(module_name, fromlist=[class_name])
    except Exception:
        return
    cls = getattr(module, class_name, None)
    if cls is None:
        return
    original = getattr(cls, "__init__", None)
    if original is None or getattr(original, "_heirloom_guard", False):
        return

    def wrapped(self: Any, *args: Any, **kwargs: Any) -> None:
        refuse_cloud(provider, str(kwargs.get("model") or class_name), caller=f"{class_name}.__init__")
        original(self, *args, **kwargs)

    setattr(wrapped, "_heirloom_guard", True)
    cls.__init__ = wrapped  # type: ignore[method-assign]


def install_box_guard() -> None:
    """Make cloud client entry points fail closed while HEIRLOOM_BOX is set."""
    global _guard_installed
    if _guard_installed or not box_mode():
        return
    _guard_installed = True
    _patch_litellm()
    _patch_llmchat()
    _patch_openai_speech()
    _patch_sdk_init("anthropic", "Anthropic", "anthropic")
    _patch_sdk_init("anthropic", "AsyncAnthropic", "anthropic")
    _patch_sdk_init("openai", "OpenAI", "openai")
    _patch_sdk_init("openai", "AsyncOpenAI", "openai")
    _patch_sdk_init("google.generativeai", "GenerativeModel", "gemini")
