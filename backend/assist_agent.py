"""Assist-only tools for the big update.

Twin, heirs, and callers receive none of these tools. Drafts are never sent.
Web research, Odysseus, smart home, writing, and MCP calls pass through the
privacy fence first. Progress events are plain status lines for the UI.

The live chat loop in ``twin_runtime.py`` is unchanged in this pass so the
BIGDEAL fallback from PR #60 stays as it is. The Windows Assist document calls
these helpers directly until that loop is wired.
"""
from __future__ import annotations

from typing import Any

from owner_privacy import PrivacyError, prepare_external_payload

TOOLS: tuple[dict[str, str], ...] = (
    {"name": "smart_home_read", "approval": "read", "label": "Read a device"},
    {"name": "smart_home_set", "approval": "confirm", "label": "Change a device"},
    {"name": "draft_message", "approval": "read", "label": "Draft a message"},
    {"name": "web_research", "approval": "read", "label": "Search the web"},
    {"name": "code_edit", "approval": "confirm", "label": "Edit code"},
    {"name": "run_command", "approval": "confirm", "label": "Run a command"},
    {"name": "writing_check", "approval": "read", "label": "Check writing"},
    {"name": "writing_rewrite", "approval": "confirm", "label": "Rewrite writing"},
    {"name": "mcp_call", "approval": "confirm", "label": "Use a connector"},
    {"name": "spawn_subagent", "approval": "read", "label": "Work in the background"},
)


class McpRefused(Exception):
    """The connector would leave this PC or has nowhere to run."""


def tools_for(*, role: str, audience: str | None, heir_surface: bool = False) -> list[dict[str, str]]:
    if heir_surface:
        return []
    if (audience or "owner").strip().lower() != "owner":
        return []
    if (role or "").strip().lower() != "assistant":
        return []
    return [dict(row) for row in TOOLS]


def draft_message(
    *,
    kind: str,
    to: str,
    body: str,
    private_texts: list[str] | None = None,
) -> dict[str, Any]:
    """A draft only. There is no send path in this module."""
    safe = prepare_external_payload("web_research", body, private_texts)
    return {
        "kind": kind,
        "to": to,
        "body": safe["payload"],
        "sent": False,
        "status": "draft",
        "needs_approval_to_send": True,
    }


def prepare_research(query: str, private_texts: list[str] | None = None) -> dict[str, Any]:
    return prepare_external_payload("web_research", query, private_texts)


def prepare_odysseus(query: str, private_texts: list[str] | None = None) -> dict[str, Any]:
    """Guard for any new Odysseus hop. The twin brain path is unchanged."""
    return prepare_external_payload("odysseus", query, private_texts)


def validate_mcp(spec: dict[str, Any]) -> dict[str, Any]:
    url = str(spec.get("url") or "").strip()
    command = str(spec.get("command") or "").strip()
    if url:
        from owner_privacy import is_loopback_url

        if not is_loopback_url(url):
            raise McpRefused(
                "A remote connector is off in this update so a prompt cannot leave this PC."
            )
    if command.lower().startswith("http://") or command.lower().startswith("https://") or "://" in command:
        raise McpRefused("The connector command has to be a program on this PC.")
    if not url and not command:
        raise McpRefused("Add a program on this PC or a connector at 127.0.0.1.")
    return {"command": command, "url": url, "remote": False}


def prepare_mcp_arguments(arguments: dict[str, Any], private_texts: list[str] | None = None) -> dict[str, Any]:
    import json

    blob = json.dumps(arguments, ensure_ascii=False)
    safe = prepare_external_payload("mcp", blob, private_texts)
    try:
        parsed = json.loads(safe["payload"])
    except json.JSONDecodeError as exc:
        raise PrivacyError("The connector arguments could not be kept private.") from exc
    if not isinstance(parsed, dict):
        raise PrivacyError("The connector arguments could not be kept private.")
    return parsed


def plan_subagent(goal: str) -> dict[str, Any]:
    return {
        "goal": goal,
        "cloud": False,
        "status": "planned",
        "steps": [
            {"id": "understand", "detail": "Read the request."},
            {"id": "do", "detail": "Do the work with local tools."},
            {"id": "report", "detail": "Report what happened."},
        ],
    }


def progress(phase: str, detail: str, *, index: int = 1, total: int = 1) -> dict[str, Any]:
    return {"phase": phase, "detail": detail, "index": index, "total": total}
