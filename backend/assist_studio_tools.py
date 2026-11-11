"""Assist-only tool executors. Twin turns cannot run these.

Web research is redacted before the existing search helper sees it.
Drafts are never sent. Device changes that need Confirm return
``needs_confirm`` and do not run.
"""
from __future__ import annotations

from typing import Any

from assist_agent import draft_message, plan_subagent, prepare_mcp_arguments, prepare_research, validate_mcp
from code_workspace import diff_hunks, pick_coder_model
from owner_pairing import is_owner_audience
from smart_home import prepare_action, scan_ssdp
from writing_assistant import check_text, propose_paste

STUDIO_TOOL_NAMES = frozenset({
    "smart_home_read",
    "smart_home_set",
    "draft_message",
    "web_research",
    "code_edit",
    "writing_check",
    "writing_rewrite",
    "mcp_call",
    "spawn_subagent",
})

STUDIO_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "smart_home_read",
            "description": "Read a light, plug, or thermostat on this home network. Reading does not need Confirm.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "name": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "smart_home_set",
            "description": (
                "Change a home device. The first change waits for Confirm. "
                "Do not turn off a fridge, medical device, furnace, or thermostat unless the owner confirms that specifically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "name": {"type": "string"},
                    "kind": {"type": "string"},
                    "action": {"type": "string"},
                    "value": {"type": "number"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_message",
            "description": "Draft an email or message. Never send it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "to": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_research",
            "description": "Look something up on the public web. Do not include the owner's private memories in the query.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "code_edit",
            "description": "Propose a code edit as reviewable hunks. Do not apply it until the owner accepts the hunks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "before": {"type": "string"},
                    "after": {"type": "string"},
                },
                "required": ["before", "after"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "writing_check",
            "description": "Check spelling, grammar, style, tone, and clarity on this PC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "surface": {"type": "string"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "writing_rewrite",
            "description": "Propose a shorter, friendlier, or more formal rewrite. Paste only after the owner approves.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "mode": {"type": "string"},
                },
                "required": ["text", "mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_call",
            "description": "Use a connector that runs on this PC. Remote connectors are refused.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "url": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "Plan a background task. It stays on this PC and does not call a hosted model.",
            "parameters": {
                "type": "object",
                "properties": {"goal": {"type": "string"}},
                "required": ["goal"],
            },
        },
    },
]


def prompt_private_snippets(system: str) -> list[str]:
    """Lines from the memory and archive sections of a prompt.

    A research or draft call redacts these even when the model copies them
    into the tool arguments and does not label them private.
    """
    text = system or ""
    chunks: list[str] = []
    markers = (
        "=== LONG-TERM MEMORY ===",
        "=== YOUR LONG-TERM MEMORY ===",
        "=== ARCHIVE EXCERPTS ===",
        "=== ARCHIVE",
    )
    for marker in markers:
        start = text.find(marker)
        if start < 0:
            continue
        rest = text[start + len(marker):]
        end = rest.find("\n===")
        block = rest if end < 0 else rest[:end]
        chunks.append(block)
    snippets: list[str] = []
    for block in chunks:
        for line in block.splitlines():
            cleaned = line.strip().lstrip("-").strip()
            if len(cleaned) >= 12 and cleaned not in snippets:
                snippets.append(cleaned)
    return snippets


def studio_names_for(role: str, audience: str | None, *, source: str = "web") -> set[str]:
    if (role or "").strip().lower() != "assistant":
        return set()
    if not is_owner_audience(audience):
        return set()
    if (source or "").strip().lower() == "phone":
        return set()
    return set(STUDIO_TOOL_NAMES)


async def exec_studio_tool(
    name: str,
    args: dict[str, Any] | None,
    *,
    role: str | None,
    audience: str | None,
    search=None,
    private_texts: list[str] | None = None,
) -> dict[str, Any]:
    if name not in studio_names_for(role or "", audience):
        return {"summary": "That stays with Assist.", "ui": {"ok": False, "error": "assist_only"}}
    payload = args or {}
    # The model does not choose which memories are private. The turn supplies them.
    owned = [text for text in (private_texts or []) if (text or "").strip()]
    if name == "smart_home_read":
        decision = prepare_action({"id": payload.get("device_id"), "name": payload.get("name"), "kind": "light"}, "read")
        return {"summary": decision["reason"], "ui": {"ok": True, "needs_confirm": False}}
    if name == "smart_home_set":
        # Confirm is the owner's button. Arguments cannot grant it.
        decision = prepare_action(
            {
                "id": payload.get("device_id") or "",
                "name": payload.get("name") or "",
                "kind": payload.get("kind") or "light",
            },
            str(payload.get("action") or "off"),
            payload.get("value"),
            always_allow=False,
            approved=False,
            critical_confirm=False,
        )
        return {
            "summary": decision["reason"],
            "ui": {"ok": False, "needs_confirm": True},
        }
    if name == "draft_message":
        draft = draft_message(
            kind=str(payload.get("kind") or "email"),
            to=str(payload.get("to") or ""),
            body=str(payload.get("body") or ""),
            private_texts=owned,
        )
        return {"summary": "Draft ready. Nothing was sent.", "ui": {"ok": True, "sent": False, "body": draft["body"]}}
    if name == "web_research":
        safe = prepare_research(str(payload.get("query") or ""), owned)
        if safe["payload"].strip() in {"", "[private]"}:
            return {"summary": "That memory stays on this PC.", "ui": {"ok": False}}
        if search is None:
            return {"summary": "Lookup ready: " + safe["payload"][:180], "ui": {"ok": True, "query": safe["payload"]}}
        found = await search(safe["payload"])
        return found
    if name == "code_edit":
        hunks = diff_hunks(str(payload.get("before") or ""), str(payload.get("after") or ""))
        coder = pick_coder_model(list(payload.get("models") or []))
        return {
            "summary": f"{len(hunks)} edit{'s' if len(hunks) != 1 else ''} to review.",
            "ui": {"ok": True, "needs_confirm": True, "hunks": hunks, "coder": coder["model"]},
        }
    if name == "writing_check":
        checked = check_text(str(payload.get("text") or ""), surface=str(payload.get("surface") or "draft"))
        count = len(checked["issues"])
        return {"summary": f"{count} suggestion{'s' if count != 1 else ''}.", "ui": {"ok": True, "issues": checked["issues"]}}
    if name == "writing_rewrite":
        proposal = propose_paste(str(payload.get("text") or ""), str(payload.get("mode") or "shorter"))
        return {
            "summary": "Rewrite ready. Paste waits for Confirm.",
            "ui": {"ok": False, "needs_confirm": True, "after": proposal["after"]},
        }
    if name == "mcp_call":
        try:
            spec = validate_mcp({"command": payload.get("command") or "", "url": payload.get("url") or ""})
            arguments = prepare_mcp_arguments(dict(payload.get("arguments") or {}), owned)
        except Exception as exc:  # noqa: BLE001 — the owner sees a sentence, not a stack
            return {"summary": str(exc), "ui": {"ok": False}}
        return {"summary": "Connector is on this PC.", "ui": {"ok": True, "needs_confirm": True, "spec": spec, "arguments": arguments}}
    if name == "spawn_subagent":
        plan = plan_subagent(str(payload.get("goal") or ""))
        return {"summary": "Background plan ready. It stays on this PC.", "ui": {"ok": True, "cloud": False, "steps": plan["steps"]}}
    return {"summary": "That stays with Assist.", "ui": {"ok": False, "error": "assist_only"}}


def classify_ssdp(raw: str) -> dict[str, Any]:
    from smart_home import parse_ssdp_message, classify_discovery

    return classify_discovery(parse_ssdp_message(raw))


__all__ = ["STUDIO_SCHEMAS", "STUDIO_TOOL_NAMES", "exec_studio_tool", "scan_ssdp", "studio_names_for"]
