"""Maestro-style model catalog — cloud APIs + one-click local downloads.

This module is deliberately free of database / FastAPI imports so it can be
unit-tested without Mongo. The HTTP surface lives in routers/models.py.

Option IDs
----------
Cloud:  ``openai:gpt-4o``
Local:  ``local:llama3.2:3b``  (the model tag may itself contain colons)
"""
from __future__ import annotations

from typing import Optional

# Cloud API services the owner can connect with a single key paste.
# `id` matches services.llm_router.PROVIDERS so routing config stays in sync.
CLOUD_SERVICES: list[dict] = [
    {
        "id": "emergent",
        "label": "Heirloom key",
        "blurb": "Works out of the box. No signup, no paste, no fuss.",
        "byok": False,
        "signup_url": "",
        "dashboard_url": "",
        "key_hint": "",
        "default_model": "claude-sonnet-4-6",
        "models": [
            "claude-sonnet-4-6",
            "claude-sonnet-5",
            "claude-opus-4-7",
            "gpt-5.4",
            "gpt-5.6-sol",
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
        ],
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "blurb": "GPT-4o and GPT-5. Best all-rounder if you already have a ChatGPT Plus key.",
        "byok": True,
        "signup_url": "https://platform.openai.com/signup",
        "dashboard_url": "https://platform.openai.com/api-keys",
        "key_hint": "sk-…",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-5.4", "gpt-5.4-mini"],
    },
    {
        "id": "anthropic",
        "label": "Anthropic",
        "blurb": "Claude. Warm, careful, great at sounding like you.",
        "byok": True,
        "signup_url": "https://console.anthropic.com/",
        "dashboard_url": "https://console.anthropic.com/settings/keys",
        "key_hint": "sk-ant-…",
        "default_model": "claude-sonnet-4-6",
        "models": ["claude-sonnet-4-6", "claude-sonnet-5", "claude-opus-4-7"],
    },
    {
        "id": "gemini",
        "label": "Google Gemini",
        "blurb": "Huge context window. Best for long letters, whole archives, big photo albums.",
        "byok": True,
        "signup_url": "https://aistudio.google.com/",
        "dashboard_url": "https://aistudio.google.com/apikey",
        "key_hint": "AIza…",
        "default_model": "gemini-2.5-flash",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.1-pro-preview", "gemini-3-flash-preview"],
    },
    {
        "id": "groq",
        "label": "Groq",
        "blurb": "Very fast and cheap. Free tier is plenty for everyday chat.",
        "byok": True,
        "signup_url": "https://console.groq.com/keys",
        "dashboard_url": "https://console.groq.com/keys",
        "key_hint": "gsk_…",
        "default_model": "llama-3.3-70b-versatile",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    },
    {
        "id": "xai",
        "label": "xAI Grok",
        "blurb": "Grok. Direct, a bit irreverent — good if that's your voice.",
        "byok": True,
        "signup_url": "https://console.x.ai/",
        "dashboard_url": "https://console.x.ai/",
        "key_hint": "xai-…",
        "default_model": "grok-2-latest",
        "models": ["grok-2-latest", "grok-2", "grok-beta"],
    },
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "blurb": "Strong reasoning for pennies. Good for Focus mode / tools.",
        "byok": True,
        "signup_url": "https://platform.deepseek.com/",
        "dashboard_url": "https://platform.deepseek.com/api_keys",
        "key_hint": "sk-…",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
]

# One-click local downloads. The desktop companion runs `ollama pull <id>`.
# Sizes are approximate published Ollama footprints (not quantized variants).
LOCAL_MODELS: list[dict] = [
    {
        "id": "llama3.2:3b",
        "name": "Llama 3.2 3B",
        "size": "2.0 GB",
        "ram": "4 GB",
        "kind": "chat",
        "recommended": True,
        "blurb": "Everyday twin chat. Fast on a laptop. Start here.",
    },
    {
        "id": "llama3.1:8b",
        "name": "Llama 3.1 8B",
        "size": "4.9 GB",
        "ram": "8 GB",
        "kind": "chat",
        "recommended": False,
        "blurb": "Smarter replies. Comfortable on 16 GB RAM or a modest GPU.",
    },
    {
        "id": "mistral:7b",
        "name": "Mistral 7B",
        "size": "4.1 GB",
        "ram": "8 GB",
        "kind": "chat",
        "recommended": False,
        "blurb": "Crisp, efficient chat. A solid Claude-alternative at home.",
    },
    {
        "id": "qwen2.5:7b",
        "name": "Qwen 2.5 7B",
        "size": "4.7 GB",
        "ram": "8 GB",
        "kind": "chat",
        "recommended": False,
        "blurb": "Great with mixed languages and longer notes.",
    },
    {
        "id": "phi3:mini",
        "name": "Phi-3 Mini",
        "size": "2.3 GB",
        "ram": "4 GB",
        "kind": "chat",
        "recommended": True,
        "blurb": "Tiny and clever. Best pick for an older PC.",
    },
    {
        "id": "gemma2:9b",
        "name": "Gemma 2 9B",
        "size": "5.4 GB",
        "ram": "12 GB",
        "kind": "chat",
        "recommended": False,
        "blurb": "Google's open model. Warm tone, good at stories.",
    },
    {
        "id": "deepseek-r1:8b",
        "name": "DeepSeek R1 8B",
        "size": "5.2 GB",
        "ram": "10 GB",
        "kind": "chat",
        "recommended": False,
        "blurb": "Thinks out loud. Best local pick for Focus mode.",
    },
    {
        "id": "nomic-embed-text",
        "name": "Nomic Embed",
        "size": "274 MB",
        "ram": "1 GB",
        "kind": "embeddings",
        "recommended": True,
        "blurb": "Memory search that never leaves your PC.",
    },
    {
        "id": "llava:7b",
        "name": "LLaVA 7B",
        "size": "4.5 GB",
        "ram": "10 GB",
        "kind": "vision",
        "recommended": False,
        "blurb": "Looks at photos on the home PC. Pairs with Screen Vision.",
    },
]

# Functions the owner picks a model for. `task` matches llm_router.TASKS
# except the last three, which map onto the local-provider subsystems.
FUNCTIONS: list[dict] = [
    {
        "id": "chat",
        "task": "chat",
        "label": "Twin chat",
        "blurb": "Talk to your twin — the main conversation.",
        "page": "/twin",
    },
    {
        "id": "interview",
        "task": "interview",
        "label": "Interviewer",
        "blurb": "The patient questions that fill the archive.",
        "page": "/interviewer",
    },
    {
        "id": "tools",
        "task": "tools",
        "label": "Focus mode / tools",
        "blurb": "Plans and PC actions. Pick a careful model.",
        "page": "/agent",
    },
    {
        "id": "cheap",
        "task": "cheap",
        "label": "Quick replies",
        "blurb": "Nudges, titles, one-liners. Fast and cheap is fine.",
        "page": "/today",
    },
    {
        "id": "long_context",
        "task": "long_context",
        "label": "Long documents",
        "blurb": "Letters, imports, whole-archive questions.",
        "page": "/library",
    },
    {
        "id": "embeddings",
        "task": "embeddings",
        "label": "Memory search",
        "blurb": "How the twin finds the right memory.",
        "page": "/library",
    },
]

CLOUD_BY_ID: dict[str, dict] = {s["id"]: s for s in CLOUD_SERVICES}
LOCAL_BY_ID: dict[str, dict] = {m["id"]: m for m in LOCAL_MODELS}
FUNCTION_BY_ID: dict[str, dict] = {f["id"]: f for f in FUNCTIONS}

# Providers whose chat APIs can carry Twin tools (search archive, PC actions…).
TOOL_CAPABLE_PROVIDERS = {"emergent", "openai", "anthropic", "gemini"}


def option_id(provider: str, model: str) -> str:
    """Stable dropdown value. Local models use the `local:` prefix so a tag
    like `llama3.2:3b` doesn't collide with a cloud `provider:model` pair.
    """
    provider = (provider or "").strip()
    model = (model or "").strip()
    if not provider or not model:
        raise ValueError("provider and model are required")
    if provider == "local":
        return f"local:{model}"
    return f"{provider}:{model}"


def parse_option_id(value: str) -> tuple[str, str]:
    """Inverse of option_id. Unknown / empty values raise ValueError."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("empty option id")
    if raw.startswith("local:"):
        model = raw[len("local:"):].strip()
        if not model:
            raise ValueError("local option missing model")
        return "local", model
    if ":" not in raw:
        raise ValueError(f"malformed option id '{raw}'")
    provider, model = raw.split(":", 1)
    provider, model = provider.strip(), model.strip()
    if not provider or not model:
        raise ValueError(f"malformed option id '{raw}'")
    return provider, model


def local_kind(model_id: str) -> Optional[str]:
    spec = LOCAL_BY_ID.get(model_id)
    return spec["kind"] if spec else None


def is_known_cloud_provider(provider: str) -> bool:
    return provider in CLOUD_BY_ID


def is_known_local_model(model_id: str) -> bool:
    return model_id in LOCAL_BY_ID


def llm_family_for(provider: str, model: str) -> Optional[tuple[str, str]]:
    """Map a routing provider + model onto LlmChat.with_model(family, name).

    Returns None when LlmChat can't speak that provider (Groq / xAI / DeepSeek
    / local) — callers should use the OpenAI-compat router or the companion.
    """
    provider = (provider or "emergent").strip()
    model = (model or "").strip()
    if provider == "openai":
        return "openai", model or "gpt-4o-mini"
    if provider == "anthropic":
        return "anthropic", model or "claude-sonnet-4-6"
    if provider == "gemini":
        return "gemini", model or "gemini-2.5-flash"
    if provider == "emergent":
        lowered = model.lower()
        if lowered.startswith("gpt"):
            return "openai", model
        if lowered.startswith("gemini"):
            return "gemini", model
        return "anthropic", model or "claude-sonnet-4-6"
    return None


def installed_set(tags: list | tuple | set | None) -> set[str]:
    """Normalise `ollama list` names so `phi3:mini` and `phi3:latest` match."""
    out: set[str] = set()
    for name in original_tags(tags):
        out.add(name)
        if ":" not in name:
            out.add(f"{name}:latest")
        elif name.endswith(":latest"):
            out.add(name.rsplit(":", 1)[0])
    return out


def original_tags(tags: list | tuple | set | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        name = str(raw).split()[0].strip()
        if not name or name.startswith("(") or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def tag_is_installed(tag: str, installed: set[str]) -> bool:
    """True when this exact Ollama tag (or its `:latest` alias) is on the PC.

    Does not treat `llama3.2:3b` as installed just because `llama3.2:1b` is.
    """
    tag = (tag or "").strip()
    if not tag:
        return False
    if tag in installed:
        return True
    if ":" not in tag and f"{tag}:latest" in installed:
        return True
    if tag.endswith(":latest") and tag[: -len(":latest")] in installed:
        return True
    return False


def ready_options(cfg: dict, installed_tags: list | None = None) -> list[dict]:
    """Dropdown choices: connected cloud models + installed local models."""
    options: list[dict] = []
    providers = cfg.get("providers") or {}
    for svc in CLOUD_SERVICES:
        pcfg = providers.get(svc["id"]) or {}
        ready = bool(pcfg.get("enabled")) and (not svc["byok"] or (pcfg.get("api_key") or pcfg.get("has_key")))
        if not ready:
            continue
        default = pcfg.get("default_model") or svc["default_model"]
        for model in svc["models"]:
            options.append({
                "id": option_id(svc["id"], model),
                "provider": svc["id"],
                "model": model,
                "label": f"{svc['label']} · {model}",
                "kind": "cloud",
                "is_default": model == default,
            })
    installed = installed_set(installed_tags or [])
    for spec in LOCAL_MODELS:
        if not tag_is_installed(spec["id"], installed):
            continue
        options.append({
            "id": option_id("local", spec["id"]),
            "provider": "local",
            "model": spec["id"],
            "label": f"Home PC · {spec['name']}",
            "kind": "local",
            "is_default": False,
        })
    for tag in original_tags(installed_tags or []):
        if any(tag_is_installed(spec["id"], installed_set([tag])) for spec in LOCAL_MODELS):
            continue
        options.append({
            "id": option_id("local", tag),
            "provider": "local",
            "model": tag,
            "label": f"Home PC · {tag}",
            "kind": "local",
            "is_default": False,
        })
    return options


def assignment_for(fn: dict, cfg: dict) -> dict:
    """Which provider + model a function currently uses."""
    task = fn["task"]
    local = (cfg.get("local_task_routes") or {}).get(task)
    if local:
        return {
            "provider": "local",
            "model": local,
            "option_id": option_id("local", local),
        }
    pid = (cfg.get("task_routes") or {}).get(task) or "emergent"
    model = (cfg.get("task_models") or {}).get(task) or ""
    if not model:
        pcfg = (cfg.get("providers") or {}).get(pid) or {}
        spec = CLOUD_BY_ID.get(pid) or {}
        model = pcfg.get("default_model") or spec.get("default_model") or ""
    return {
        "provider": pid,
        "model": model,
        "option_id": option_id(pid, model) if pid and model else "",
    }
