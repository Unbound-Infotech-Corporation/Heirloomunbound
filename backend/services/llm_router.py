"""Multi-provider LLM router with usage tracking + budget-aware fallback.

Design
------
- **Six BYOK providers** (openai, anthropic, gemini, groq, xai, deepseek) plus
  the built-in `emergent` provider (which uses `EMERGENT_LLM_KEY` and covers
  OpenAI/Anthropic/Gemini transparently).
- All non-emergent providers are called through their OpenAI-compatible chat
  completions API — Groq / xAI / DeepSeek publish OpenAI-shape endpoints, and
  OpenAI / Anthropic (via their official proxy) do too. This keeps the router
  small: one `openai.AsyncOpenAI(base_url=..., api_key=...)` dispatch path.
- **Task-based routing**: the owner picks a default provider per task
  (chat, interview, embeddings, tools, cheap, long_context). Any task can be
  overridden per-call. If the picked provider is over its monthly budget or
  fails, the router walks a fallback chain.
- Every call is logged to `usage_events` with token counts + $ estimate so the
  UI can show a running tally.

This module is intentionally standalone — the existing `/twin/chat` endpoint
still uses `emergentintegrations.LlmChat` directly for streaming/tool-use, and
that path is unchanged. The new `/api/routing/chat` endpoint uses this router.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from openai import AsyncOpenAI

from deps import EMERGENT_LLM_KEY, db

# --- Provider registry ---------------------------------------------------
# base_url is None for "emergent" (which uses emergentintegrations.LlmChat).
# Every other provider is called via the AsyncOpenAI SDK against its
# published OpenAI-compatible endpoint.
PROVIDERS: dict[str, dict] = {
    "emergent": {
        "label": "Emergent LLM Key",
        "base_url": None,
        "byok": False,
        "default_model": "claude-sonnet-4-6",
        "models": [
            "claude-sonnet-4-6", "claude-sonnet-5", "claude-opus-4-7",
            "gpt-5.4", "gpt-5.6-sol", "gemini-3.1-pro-preview", "gemini-3-flash-preview",
        ],
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "byok": True,
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-5.4", "gpt-5.4-mini"],
    },
    "anthropic": {
        "label": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",  # via anthropic-openai bridge
        "byok": True,
        "default_model": "claude-sonnet-4-6",
        "models": ["claude-sonnet-4-6", "claude-sonnet-5", "claude-opus-4-7"],
    },
    "gemini": {
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "byok": True,
        "default_model": "gemini-2.5-flash",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.1-pro-preview", "gemini-3-flash-preview"],
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "byok": True,
        "default_model": "llama-3.3-70b-versatile",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    },
    "xai": {
        "label": "xAI Grok",
        "base_url": "https://api.x.ai/v1",
        "byok": True,
        "default_model": "grok-2-latest",
        "models": ["grok-2-latest", "grok-2", "grok-beta"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "byok": True,
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
}

# Task presets — the router chooses one of these per call.
TASKS: dict[str, dict] = {
    "chat":         {"label": "Twin chat",       "default": "emergent"},
    "interview":    {"label": "AI interviewer",  "default": "emergent"},
    "tools":        {"label": "Tool use",        "default": "emergent"},
    "cheap":        {"label": "Cheap / fast",    "default": "groq"},
    "long_context": {"label": "Long context",    "default": "gemini"},
    "embeddings":   {"label": "Embeddings",      "default": "openai"},
}

# Ordered fallback chain when the primary provider is over budget / errors.
DEFAULT_FALLBACK = ["emergent", "openai", "anthropic", "gemini", "groq", "xai", "deepseek"]

# --- Routing presets ("Provider Templates") ------------------------------
# One-click routing setups the UI offers so newcomers get a sensible layout
# without editing every task. Each preset only touches `task_routes` — keys,
# enabled flags and budget caps are left alone. If a target provider isn't
# enabled/keyed the runtime fallback chain still keeps the twin working.
PRESETS: dict[str, dict] = {
    "cheapest": {
        "label": "Cheapest",
        "blurb": "Groq for most tasks, DeepSeek for reasoning, Gemini for long context. Requires Groq + DeepSeek keys.",
        "task_routes": {
            "chat": "groq", "interview": "groq", "tools": "deepseek",
            "cheap": "groq", "long_context": "gemini", "embeddings": "openai",
        },
    },
    "quality_first": {
        "label": "Quality-first",
        "blurb": "Anthropic Claude for the twin's voice, Gemini for long docs. Requires Anthropic + Gemini keys.",
        "task_routes": {
            "chat": "anthropic", "interview": "anthropic", "tools": "anthropic",
            "cheap": "groq", "long_context": "gemini", "embeddings": "openai",
        },
    },
    "balanced": {
        "label": "Balanced",
        "blurb": "Emergent for chat, Groq for fast/cheap, Gemini for long context. Works out of the box.",
        "task_routes": {
            "chat": "emergent", "interview": "emergent", "tools": "emergent",
            "cheap": "groq", "long_context": "gemini", "embeddings": "openai",
        },
    },
    "all_emergent": {
        "label": "All Emergent",
        "blurb": "One provider for everything — no BYOK required. Uses your Universal Key balance.",
        "task_routes": {tid: "emergent" for tid in ("chat", "interview", "tools", "cheap", "long_context", "embeddings")},
    },
    "local_first": {
        "label": "Local-first (privacy)",
        "blurb": "Groq + DeepSeek + Gemini — none of your prompts go to Anthropic or OpenAI. Requires all three keys.",
        "task_routes": {
            "chat": "groq", "interview": "groq", "tools": "deepseek",
            "cheap": "groq", "long_context": "gemini", "embeddings": "gemini",
        },
    },
}

# --- Pricing table (USD per 1M tokens; input / output) --------------------
# Approximate published rates as of Feb 2026 — used only for cost *estimates*.
# Keys are `<provider>:<model>`; unknown pairs fall back to a mid-market rate.
PRICING: dict[str, tuple[float, float]] = {
    "openai:gpt-4o":                (2.50, 10.00),
    "openai:gpt-4o-mini":           (0.15, 0.60),
    "openai:gpt-4.1":               (2.00, 8.00),
    "openai:gpt-4.1-mini":          (0.15, 0.60),
    "openai:gpt-5.4":               (3.00, 12.00),
    "openai:gpt-5.4-mini":          (0.20, 0.80),
    "anthropic:claude-sonnet-4-6":  (3.00, 15.00),
    "anthropic:claude-sonnet-5":    (3.00, 15.00),
    "anthropic:claude-opus-4-7":    (15.00, 75.00),
    "gemini:gemini-2.5-flash":      (0.10, 0.40),
    "gemini:gemini-2.5-pro":        (1.25, 5.00),
    "gemini:gemini-3.1-pro-preview":(2.00, 8.00),
    "gemini:gemini-3-flash-preview":(0.15, 0.60),
    "groq:llama-3.3-70b-versatile": (0.59, 0.79),
    "groq:llama-3.1-8b-instant":    (0.05, 0.08),
    "groq:mixtral-8x7b-32768":      (0.24, 0.24),
    "xai:grok-2-latest":            (2.00, 10.00),
    "xai:grok-2":                   (2.00, 10.00),
    "xai:grok-beta":                (5.00, 15.00),
    "deepseek:deepseek-chat":       (0.27, 1.10),
    "deepseek:deepseek-reasoner":   (0.55, 2.19),
    # emergent route bills against the Universal Key balance — we mirror the
    # underlying provider price as a best-effort estimate.
    "emergent:claude-sonnet-4-6":   (3.00, 15.00),
    "emergent:claude-sonnet-5":     (3.00, 15.00),
    "emergent:claude-opus-4-7":     (15.00, 75.00),
    "emergent:gpt-5.4":             (3.00, 12.00),
    "emergent:gpt-5.6-sol":         (5.00, 15.00),
    "emergent:gemini-3.1-pro-preview": (2.00, 8.00),
    "emergent:gemini-3-flash-preview": (0.15, 0.60),
}
_MID_MARKET = (1.00, 3.00)  # dollars per 1M tokens for unknown models


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    inp, out = PRICING.get(f"{provider}:{model}", _MID_MARKET)
    return round((prompt_tokens * inp + completion_tokens * out) / 1_000_000, 6)


# --- Config helpers ------------------------------------------------------
DEFAULT_CONFIG = {
    "providers": {
        pid: {
            "enabled": pid == "emergent",  # only Emergent on by default
            "api_key": "",
            "default_model": PROVIDERS[pid]["default_model"],
            "monthly_budget_usd": 0.0,  # 0 = no cap
        }
        for pid in PROVIDERS
    },
    "task_routes": {task_id: spec["default"] for task_id, spec in TASKS.items()},
    "fallback_order": list(DEFAULT_FALLBACK),
}


async def get_config(user_id: str) -> dict:
    """Load the user's routing config, filling in defaults for any missing keys."""
    doc = await db.routing_configs.find_one({"user_id": user_id}, {"_id": 0}) or {}
    cfg = {
        "providers": {**DEFAULT_CONFIG["providers"]},
        "task_routes": {**DEFAULT_CONFIG["task_routes"]},
        "fallback_order": list(doc.get("fallback_order") or DEFAULT_CONFIG["fallback_order"]),
    }
    for pid, defaults in DEFAULT_CONFIG["providers"].items():
        stored = (doc.get("providers") or {}).get(pid) or {}
        cfg["providers"][pid] = {**defaults, **stored}
    for task_id, default_pid in DEFAULT_CONFIG["task_routes"].items():
        cfg["task_routes"][task_id] = (doc.get("task_routes") or {}).get(task_id, default_pid)
    return cfg


async def save_config(user_id: str, cfg: dict) -> dict:
    doc = {
        "user_id": user_id,
        "providers": cfg.get("providers", {}),
        "task_routes": cfg.get("task_routes", {}),
        "fallback_order": cfg.get("fallback_order", DEFAULT_CONFIG["fallback_order"]),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.routing_configs.replace_one({"user_id": user_id}, doc, upsert=True)
    return await get_config(user_id)


# --- Budget check --------------------------------------------------------
async def month_to_date_cost(user_id: str, provider: str) -> float:
    """Sum usage_events.cost_usd for this provider since the 1st of the UTC month."""
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    pipeline = [
        {"$match": {"user_id": user_id, "provider": provider, "ts": {"$gte": start}}},
        {"$group": {"_id": None, "total": {"$sum": "$cost_usd"}}},
    ]
    async for row in db.usage_events.aggregate(pipeline):
        return round(float(row.get("total") or 0.0), 6)
    return 0.0


async def _is_over_budget(user_id: str, provider: str, cfg: dict) -> bool:
    cap = float(((cfg["providers"].get(provider) or {}).get("monthly_budget_usd") or 0))
    if cap <= 0:
        return False
    spent = await month_to_date_cost(user_id, provider)
    return spent >= cap


async def resolve_provider(user_id: str, task: str, cfg: Optional[dict] = None) -> tuple[str, list[str]]:
    """Return (primary_provider, fallback_chain) honoring task routes + budget caps.

    The fallback chain is filtered to enabled providers only, minus any over budget.
    If the primary is over-budget or disabled, we walk the chain until we find a viable one.
    """
    cfg = cfg or await get_config(user_id)
    primary = cfg["task_routes"].get(task) or DEFAULT_CONFIG["task_routes"].get(task, "emergent")
    chain = [primary] + [p for p in cfg["fallback_order"] if p != primary]

    viable: list[str] = []
    for pid in chain:
        pcfg = cfg["providers"].get(pid) or {}
        if not pcfg.get("enabled"):
            continue
        if PROVIDERS[pid]["byok"] and not (pcfg.get("api_key") or "").strip():
            continue
        if await _is_over_budget(user_id, pid, cfg):
            continue
        viable.append(pid)

    if not viable:
        # Always allow Emergent as an absolute last resort so the app never bricks.
        viable = ["emergent"]
    return viable[0], viable


def _api_key(provider: str, cfg: dict) -> str:
    """Return the API key for a provider.

    Security note (SEC-HARD-1): we DO NOT fall back to a shared env variable
    for BYOK providers. If a user hasn't configured their own key, the call
    must fail loud (missing key) — silently spending the operator's key would
    break per-tenant isolation and BYOK expectations.
    """
    if provider == "emergent":
        return EMERGENT_LLM_KEY
    pcfg = cfg["providers"].get(provider) or {}
    return (pcfg.get("api_key") or "").strip()


# --- Chat dispatch (non-streaming, returns full response + usage) --------
async def chat_once(
    user_id: str,
    task: str,
    messages: list[dict],
    *,
    model_override: Optional[str] = None,
    provider_override: Optional[str] = None,
) -> dict:
    """Send a chat completion request, log usage, return the full reply.

    Args:
        user_id: caller identity — used for BYOK lookup + usage logging.
        task: one of TASKS keys (drives default provider).
        messages: OpenAI-shape [{role, content}, ...].
        model_override / provider_override: bypass task routing for one call.

    Returns:
        {ok, provider, model, text, prompt_tokens, completion_tokens, cost_usd, attempted}
    """
    cfg = await get_config(user_id)
    if provider_override:
        chain = [provider_override] + [p for p in cfg["fallback_order"] if p != provider_override]
    else:
        _, chain = await resolve_provider(user_id, task, cfg)

    attempted: list[dict] = []
    for provider in chain:
        pcfg = cfg["providers"].get(provider) or {}
        model = model_override or pcfg.get("default_model") or PROVIDERS[provider]["default_model"]
        try:
            if provider == "emergent":
                result = await _dispatch_emergent(user_id, model, messages)
            else:
                result = await _dispatch_openai_compat(provider, cfg, model, messages)
        except Exception as exc:  # noqa: BLE001
            attempted.append({"provider": provider, "error": str(exc)[:200]})
            continue

        cost = estimate_cost(provider, model, result["prompt_tokens"], result["completion_tokens"])
        await _log_usage(
            user_id=user_id, provider=provider, model=model, task=task,
            prompt_tokens=result["prompt_tokens"], completion_tokens=result["completion_tokens"],
            cost_usd=cost,
        )
        return {
            "ok": True,
            "provider": provider,
            "model": model,
            "text": result["text"],
            "prompt_tokens": result["prompt_tokens"],
            "completion_tokens": result["completion_tokens"],
            "cost_usd": cost,
            "attempted": attempted,
        }

    return {"ok": False, "error": "All providers failed", "attempted": attempted}


async def _dispatch_openai_compat(provider: str, cfg: dict, model: str, messages: list[dict]) -> dict:
    """One-shot call to any OpenAI-compatible chat completions endpoint."""
    base_url = PROVIDERS[provider]["base_url"]
    api_key = _api_key(provider, cfg)
    if not api_key:
        raise RuntimeError(f"{provider}: no API key configured")

    # Anthropic's public endpoint is not OpenAI-shape (they use /v1/messages).
    # We handle it via the emergentintegrations path when the user selects it,
    # so raw BYOK "anthropic" here routes through their OpenAI-compat proxy at
    # https://api.anthropic.com/v1/  — which supports /chat/completions since
    # late 2025. If the account doesn't have the proxy enabled the call errors
    # and the router falls back to the next provider automatically.
    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=60.0)
    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.7,
        max_tokens=1024,
    )
    choice = resp.choices[0] if resp.choices else None
    text = (choice.message.content if choice and choice.message else "") or ""
    usage = resp.usage
    return {
        "text": text.strip(),
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
    }


async def _dispatch_emergent(user_id: str, model: str, messages: list[dict]) -> dict:
    """Route through emergentintegrations.LlmChat — best-effort token counts.

    LlmChat doesn't yet expose token usage in a stable way, so we approximate
    from character length (roughly 4 chars/token). Users see this as a rough
    estimate; the important thing is that Emergent bills their Universal Key.
    """
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    system = next((m["content"] for m in messages if m.get("role") == "system"), "")
    convo = [m for m in messages if m.get("role") in ("user", "assistant")]
    # Reduce to the tail — LlmChat replays conversation via initial_messages.
    tail_user = convo[-1]["content"] if convo and convo[-1]["role"] == "user" else ""
    initial = [m for m in convo[:-1]]

    # Pick provider based on model prefix.
    if model.startswith("claude"):
        vendor = "anthropic"
    elif model.startswith("gemini"):
        vendor = "gemini"
    else:
        vendor = "openai"

    chat = (
        LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"router:{user_id}",
            system_message=system,
            initial_messages=([{"role": "system", "content": system}] + initial) if initial else None,
        )
        .with_model(vendor, model)
    )
    resp = await chat.send_message(UserMessage(text=tail_user))
    text = (getattr(resp, "content", None) or str(resp) or "").strip()
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    return {
        "text": text,
        "prompt_tokens": max(1, prompt_chars // 4),
        "completion_tokens": max(1, len(text) // 4),
    }


# --- Streaming dispatch --------------------------------------------------
async def chat_stream(
    user_id: str,
    task: str,
    messages: list[dict],
    *,
    model_override: Optional[str] = None,
    provider_override: Optional[str] = None,
) -> AsyncGenerator[dict, None]:
    """Yield {'delta': str} chunks as they arrive, then a final {'done': True, ...usage}.

    On failure of the primary provider, yields a {'fallback': provider} event
    and retries down the chain.
    """
    cfg = await get_config(user_id)
    if provider_override:
        chain = [provider_override] + [p for p in cfg["fallback_order"] if p != provider_override]
    else:
        _, chain = await resolve_provider(user_id, task, cfg)

    last_error: Optional[str] = None
    for idx, provider in enumerate(chain):
        pcfg = cfg["providers"].get(provider) or {}
        model = model_override or pcfg.get("default_model") or PROVIDERS[provider]["default_model"]
        if idx > 0:
            yield {"fallback": provider, "model": model}
        try:
            full = ""
            prompt_tokens = 0
            completion_tokens = 0
            if provider == "emergent":
                async for ev in _stream_emergent(user_id, model, messages):
                    if "delta" in ev:
                        full += ev["delta"]
                        yield {"delta": ev["delta"], "provider": provider, "model": model}
                    elif "usage" in ev:
                        prompt_tokens = ev["usage"]["prompt_tokens"]
                        completion_tokens = ev["usage"]["completion_tokens"]
            else:
                async for ev in _stream_openai_compat(provider, cfg, model, messages):
                    if "delta" in ev:
                        full += ev["delta"]
                        yield {"delta": ev["delta"], "provider": provider, "model": model}
                    elif "usage" in ev:
                        prompt_tokens = ev["usage"]["prompt_tokens"]
                        completion_tokens = ev["usage"]["completion_tokens"]

            if not full.strip():
                raise RuntimeError("empty response")
            cost = estimate_cost(provider, model, prompt_tokens, completion_tokens)
            await _log_usage(
                user_id=user_id, provider=provider, model=model, task=task,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                cost_usd=cost,
            )
            yield {
                "done": True, "provider": provider, "model": model,
                "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                "cost_usd": cost,
            }
            return
        except Exception as exc:  # noqa: BLE001
            last_error = f"{provider}: {exc}"
            continue

    yield {"error": last_error or "All providers failed"}


async def _stream_openai_compat(
    provider: str, cfg: dict, model: str, messages: list[dict]
) -> AsyncGenerator[dict, None]:
    base_url = PROVIDERS[provider]["base_url"]
    api_key = _api_key(provider, cfg)
    if not api_key:
        raise RuntimeError(f"{provider}: no API key configured")

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=60.0)
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    full_text = ""

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.7,
        max_tokens=1024,
        stream=True,
        stream_options={"include_usage": True},
    )
    p_tok = 0
    c_tok = 0
    async for chunk in stream:
        # usage arrives on the final chunk when stream_options.include_usage is set
        if getattr(chunk, "usage", None):
            p_tok = int(getattr(chunk.usage, "prompt_tokens", 0) or 0)
            c_tok = int(getattr(chunk.usage, "completion_tokens", 0) or 0)
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None) or ""
        if piece:
            full_text += piece
            yield {"delta": piece}

    # Some providers (xAI, DeepSeek historically) skip usage in streaming.
    if not p_tok:
        p_tok = max(1, prompt_chars // 4)
    if not c_tok:
        c_tok = max(1, len(full_text) // 4)
    yield {"usage": {"prompt_tokens": p_tok, "completion_tokens": c_tok}}


async def _stream_emergent(
    user_id: str, model: str, messages: list[dict]
) -> AsyncGenerator[dict, None]:
    from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage

    system = next((m["content"] for m in messages if m.get("role") == "system"), "")
    convo = [m for m in messages if m.get("role") in ("user", "assistant")]
    tail_user = convo[-1]["content"] if convo and convo[-1]["role"] == "user" else ""
    initial = convo[:-1]

    if model.startswith("claude"):
        vendor = "anthropic"
    elif model.startswith("gemini"):
        vendor = "gemini"
    else:
        vendor = "openai"

    chat = (
        LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"router:{user_id}",
            system_message=system,
            initial_messages=([{"role": "system", "content": system}] + initial) if initial else None,
        )
        .with_model(vendor, model)
    )
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    full = ""
    async for ev in chat.stream_message(UserMessage(text=tail_user)):
        if isinstance(ev, TextDelta):
            full += ev.content
            yield {"delta": ev.content}
        elif isinstance(ev, StreamDone):
            break
    yield {"usage": {
        "prompt_tokens": max(1, prompt_chars // 4),
        "completion_tokens": max(1, len(full) // 4),
    }}


# --- Usage logging + rollups ---------------------------------------------
async def _log_usage(*, user_id: str, provider: str, model: str, task: str,
                    prompt_tokens: int, completion_tokens: int, cost_usd: float) -> None:
    doc = {
        "user_id": user_id,
        "provider": provider,
        "model": model,
        "task": task,
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "cost_usd": float(cost_usd),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    await db.usage_events.insert_one(doc)
    # Non-blocking budget-threshold email — safe to fail silently.
    try:
        await _maybe_send_budget_alert(user_id, provider)
    except Exception:  # noqa: BLE001
        pass


async def _maybe_send_budget_alert(user_id: str, provider: str) -> None:
    """Fire a 80% / 100% budget email — once per month, per tier, per provider.

    Uses the `budget_alerts` collection as an idempotency guard:
      key = (user_id, provider, YYYY-MM, tier)
    so the owner never gets spammed if usage keeps climbing.
    """
    cfg = await get_config(user_id)
    pcfg = cfg["providers"].get(provider) or {}
    cap = float(pcfg.get("monthly_budget_usd") or 0)
    if cap <= 0:
        return
    spent = await month_to_date_cost(user_id, provider)
    ratio = spent / cap if cap else 0.0
    if ratio < 0.8:
        return
    tier = "100" if ratio >= 1.0 else "80"

    now = datetime.now(timezone.utc)
    month = f"{now.year:04d}-{now.month:02d}"
    guard_key = {"user_id": user_id, "provider": provider, "month": month, "tier": tier}
    # Race-safe: rely on the unique index at (user_id, provider, month, tier).
    # Two concurrent over-cap calls can both pass the find_one gate; only one
    # will win the insert — the other raises DuplicateKeyError and we no-op.
    try:
        await db.budget_alerts.insert_one({**guard_key, "sent_at": now.isoformat()})
    except Exception:  # DuplicateKeyError or any race — someone else got here first.
        return

    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1, "name": 1})
    if not user or not (user.get("email") or "").strip():
        return
    from email_service import send_budget_alert_email
    await send_budget_alert_email(
        to=user["email"], owner_name=user.get("name", "Friend"),
        provider=provider, tier=tier, spent_usd=round(spent, 4), cap_usd=cap,
    )


async def usage_summary(user_id: str, days: int = 30) -> dict:
    """Aggregate usage over the last N days, grouped by provider + by task."""
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
    match = {"$match": {"user_id": user_id, "ts": {"$gte": since}}}

    by_provider: list[dict] = []
    async for row in db.usage_events.aggregate([
        match,
        {"$group": {
            "_id": "$provider",
            "prompt_tokens": {"$sum": "$prompt_tokens"},
            "completion_tokens": {"$sum": "$completion_tokens"},
            "cost_usd": {"$sum": "$cost_usd"},
            "calls": {"$sum": 1},
        }},
        {"$project": {
            "_id": 0, "provider": "$_id",
            "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 1, "calls": 1,
        }},
    ]):
        by_provider.append(row)

    by_task: list[dict] = []
    async for row in db.usage_events.aggregate([
        match,
        {"$group": {
            "_id": "$task",
            "prompt_tokens": {"$sum": "$prompt_tokens"},
            "completion_tokens": {"$sum": "$completion_tokens"},
            "cost_usd": {"$sum": "$cost_usd"},
            "calls": {"$sum": 1},
        }},
        {"$project": {
            "_id": 0, "task": "$_id",
            "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 1, "calls": 1,
        }},
    ]):
        by_task.append(row)

    total_cost = round(sum(r["cost_usd"] for r in by_provider), 6)
    total_calls = sum(r["calls"] for r in by_provider)
    return {
        "days": days,
        "total_cost_usd": total_cost,
        "total_calls": total_calls,
        "by_provider": sorted(by_provider, key=lambda r: -r["cost_usd"]),
        "by_task": sorted(by_task, key=lambda r: -r["cost_usd"]),
    }


async def daily_spend_series(user_id: str, days: int = 30) -> dict:
    """Return per-day cost buckets per provider — powers the sparkline chart.

    Shape:
        {
          "days": [YYYY-MM-DD, ...],       # oldest → newest, length=days
          "series": {provider_id: [cost_per_day, ...]}
        }
    """
    from datetime import timedelta
    # Spec: `days=0` should clamp to 1, not fall through to the default 30.
    # `int(days or 30)` would collapse 0 to 30 before the max() ran, so we
    # translate None → 30 explicitly and always run the clamp afterwards.
    days = max(1, min(int(days if days is not None else 30), 90))
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    since = (now - timedelta(days=days - 1)).isoformat()

    # Mongo aggregate: group by (provider, date-string of ts).
    pipeline = [
        {"$match": {"user_id": user_id, "ts": {"$gte": since}}},
        {"$group": {
            "_id": {
                "provider": "$provider",
                "day": {"$substr": ["$ts", 0, 10]},  # ts is ISO 'YYYY-MM-DDT…'
            },
            "cost": {"$sum": "$cost_usd"},
        }},
    ]
    day_labels = [(now - timedelta(days=days - 1 - i)).date().isoformat() for i in range(days)]
    day_index = {d: i for i, d in enumerate(day_labels)}

    series: dict[str, list[float]] = {}
    async for row in db.usage_events.aggregate(pipeline):
        pid = row["_id"]["provider"]
        d = row["_id"]["day"]
        if d not in day_index:
            continue
        arr = series.setdefault(pid, [0.0] * days)
        arr[day_index[d]] = round(float(row["cost"] or 0), 6)

    return {"days": day_labels, "series": series}


async def month_end_projections(user_id: str) -> dict:
    """Extrapolate current-month spend to month-end per provider.

    Method: sum this month's usage_events per provider (month-to-date $), then
    linear-extrapolate (`mtd / days_elapsed * days_in_month`). Also returns
    days_elapsed / days_in_month so the frontend can render a runway bar.

    Not perfectly accurate — real spend is bursty and non-linear — but good
    enough to tell an owner "you're on track for $12, cap is $10" at a glance.
    """
    import calendar
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    days_elapsed = max(1, (now - month_start).days + 1)  # +1 to include today

    pipeline = [
        {"$match": {"user_id": user_id, "ts": {"$gte": month_start.isoformat()}}},
        {"$group": {"_id": "$provider", "mtd": {"$sum": "$cost_usd"}}},
    ]
    out: dict[str, dict] = {}
    async for row in db.usage_events.aggregate(pipeline):
        pid = row["_id"]
        mtd = float(row["mtd"] or 0)
        projected = round(mtd / days_elapsed * days_in_month, 4)
        out[pid] = {
            "mtd_usd": round(mtd, 4),
            "projected_month_end_usd": projected,
            "days_elapsed": days_elapsed,
            "days_in_month": days_in_month,
        }
    return out
