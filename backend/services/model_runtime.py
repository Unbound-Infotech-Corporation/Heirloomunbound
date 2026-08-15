"""Resolve which provider + model a function should use, then build an LlmChat.

Twin chat, the interviewer, and Focus mode all used to hard-code
Claude-via-Emergent. This helper honours the Maestro picker:

    1. Per-call override (dropdown on the page)
    2. Per-function assignment (Models page)
    3. Task route + provider default
    4. Emergent last resort

Local models run on the home PC through the companion (`kind="local"`).
Cloud providers that LlmChat understands (emergent / openai / anthropic /
gemini) return a ready `chat` object. Groq / xAI / DeepSeek return
`kind="compat"` so the caller can fall back to the OpenAI-shape router.
"""
from __future__ import annotations

from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage

from deps import EMERGENT_LLM_KEY
from services.llm_router import PROVIDERS, chat_once, get_config
from services.model_catalog import TOOL_CAPABLE_PROVIDERS, llm_family_for, option_id
from twin_tools import _queue_pc_command, _wait_for_command_result


async def resolve_runtime(
    user_id: str,
    task: str,
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
) -> dict:
    """Return a resolved backend for `task`.

    Shape::

        {
          kind: "cloud" | "local" | "compat",
          provider, model, option_id,
          api_key, llm_family, tools_ok,
        }
    """
    cfg = await get_config(user_id)
    local_routes = cfg.get("local_task_routes") or {}
    task_models = cfg.get("task_models") or {}

    # Explicit per-call override wins. "local" is a picker provider, not a
    # routing PROVIDERS key.
    if (provider_override or "").strip() == "local":
        model = (model_override or local_routes.get(task) or "").strip()
        if not model:
            raise ValueError("Pick a home-PC model first — download one from Models.")
        return {
            "kind": "local",
            "provider": "local",
            "model": model,
            "option_id": option_id("local", model),
            "api_key": "",
            "llm_family": None,
            "tools_ok": False,
        }

    if not provider_override and local_routes.get(task) and not model_override:
        model = local_routes[task]
        return {
            "kind": "local",
            "provider": "local",
            "model": model,
            "option_id": option_id("local", model),
            "api_key": "",
            "llm_family": None,
            "tools_ok": False,
        }

    pid = (provider_override or "").strip() or (cfg.get("task_routes") or {}).get(task) or "emergent"
    if pid not in PROVIDERS:
        pid = "emergent"
    pcfg = (cfg.get("providers") or {}).get(pid) or {}
    model = (
        (model_override or "").strip()
        or (task_models.get(task) or "").strip()
        or (pcfg.get("default_model") or "")
        or PROVIDERS[pid]["default_model"]
    )
    family = llm_family_for(pid, model)
    if pid == "emergent":
        api_key = EMERGENT_LLM_KEY
    else:
        api_key = (pcfg.get("api_key") or "").strip()
    kind = "cloud" if family else "compat"
    return {
        "kind": kind,
        "provider": pid,
        "model": model,
        "option_id": option_id(pid, model),
        "api_key": api_key,
        "llm_family": family[0] if family else None,
        "tools_ok": pid in TOOL_CAPABLE_PROVIDERS,
    }


async def run_local_chat(user_id: str, model: str, messages: list[dict], *, timeout: float = 180.0) -> str:
    """Ask the home PC to complete a chat against a local Ollama model."""
    cmd_id = await _queue_pc_command(user_id, "llm_chat", {"model": model, "messages": messages})
    doc = await _wait_for_command_result(cmd_id, user_id, timeout=timeout)
    if doc is None:
        raise RuntimeError(
            "The home computer didn't answer in time. Is the Heirloom desktop app open?"
        )
    if doc.get("status") == "error":
        raise RuntimeError(doc.get("result") or "Local model failed.")
    return (doc.get("result") or "").strip()


async def complete_text(
    user_id: str,
    task: str,
    *,
    session_id: str,
    system_message: str,
    user_text: str,
    history: Optional[list[dict]] = None,
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
) -> tuple[str, dict]:
    """Non-tool completion used by the interviewer and Focus planner.

    Returns (text, resolved_runtime).
    """
    resolved = await resolve_runtime(user_id, task, provider_override, model_override)
    history = history or []
    if resolved["kind"] == "local":
        messages = [{"role": "system", "content": system_message}]
        for m in history:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": user_text})
        text = await run_local_chat(user_id, resolved["model"], messages)
        return text, resolved

    if resolved["kind"] == "compat":
        messages = [{"role": "system", "content": system_message}]
        for m in history:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": user_text})
        result = await chat_once(
            user_id, task, messages,
            model_override=resolved["model"], provider_override=resolved["provider"],
        )
        return (result.get("text") or "").strip(), resolved

    chat = build_llm_chat(
        resolved,
        session_id=session_id,
        system_message=system_message,
        initial_messages=[{"role": "system", "content": system_message}, *history],
    )
    reply = await chat.send_message(UserMessage(text=user_text))
    text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    return (text or "").strip(), resolved


def build_llm_chat(
    resolved: dict,
    *,
    session_id: str,
    system_message: str,
    initial_messages: Optional[list] = None,
) -> LlmChat:
    """Build an LlmChat from a `kind="cloud"` resolve_runtime result."""
    family = resolved.get("llm_family")
    if not family:
        raise ValueError(f"provider '{resolved.get('provider')}' is not LlmChat-capable")
    key = resolved.get("api_key") or EMERGENT_LLM_KEY
    chat = LlmChat(
        api_key=key,
        session_id=session_id,
        system_message=system_message,
        initial_messages=initial_messages or [],
    )
    return chat.with_model(family, resolved["model"])
