"""Assist action receipts — reviewable proof of a Do / PC turn.

Twin (Ask) turns do not emit a receipt. Assist and the owner-rail Assist
leg always do: steps attempted, tool names, success/fail, and a short
human summary. A plan chip is included only for multi-step work or when
Confirm is waiting in-document.
"""
from __future__ import annotations

from typing import Any, Optional

STATUS_DID = "did"
STATUS_FAILED = "failed"
STATUS_WAITING_CONFIRM = "waiting_confirm"
STATUS_PLANNED = "planned"

VALID_STATUSES = frozenset({
    STATUS_DID,
    STATUS_FAILED,
    STATUS_WAITING_CONFIRM,
    STATUS_PLANNED,
})

# Human labels for Assist tools. Twin archive tools are listed so a
# stray row on a mixed trace still renders, but receipts are Assist-only.
TOOL_LABELS = {
    "open_on_pc": "Open on this PC",
    "control_media": "Control playback",
    "set_volume": "Set volume",
    "power_action": "Power control",
    "notify_on_pc": "Notify this PC",
    "type_text": "Type on this PC",
    "clipboard": "Clipboard",
    "see_screen": "See the screen",
    "system_status": "System status",
    "run_command": "Run a command",
    "find_file": "Find a file",
    "search_archive": "Search the archive",
    "save_memory": "Save to the archive",
    "set_reminder": "Set a reminder",
    "list_recent_memories": "Read recent memories",
    "get_weather": "Check the weather",
    "web_search": "Search the web",
    "web_fetch": "Read a page",
    "run_skill": "Run a skill",
}

_SUMMARY_MAX = 280


def clip_summary(text: str, limit: int = _SUMMARY_MAX) -> str:
    raw = " ".join((text or "").strip().split())
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)].rstrip() + "…"


def tool_label(name: str) -> str:
    key = (name or "").strip()
    return TOOL_LABELS.get(key, key or "tool")


def step_from_trace(row: dict[str, Any] | None) -> Optional[dict[str, Any]]:
    """Normalize one tool_trace row into a receipt step."""
    if not isinstance(row, dict):
        return None
    name = str(row.get("name") or "").strip()
    if not name:
        return None
    ui = row.get("ui") if isinstance(row.get("ui"), dict) else {}
    needs_confirm = bool(ui.get("needs_confirm"))
    ok_raw = ui.get("ok")
    if needs_confirm:
        ok = False
    elif ok_raw is None:
        ok = True
    else:
        ok = bool(ok_raw)
    summary = clip_summary(str(row.get("summary") or ui.get("label") or ""))
    return {
        "id": str(row.get("id") or ""),
        "name": name,
        "label": tool_label(name),
        "ok": ok,
        "needs_confirm": needs_confirm,
        "summary": summary,
    }


def receipt_status(steps: list[dict[str, Any]]) -> str:
    if any(s.get("needs_confirm") for s in steps):
        return STATUS_WAITING_CONFIRM
    if steps and any(not s.get("ok") for s in steps):
        return STATUS_FAILED
    return STATUS_DID


def receipt_plan(steps: list[dict[str, Any]], status: str) -> Optional[list[str]]:
    """Short plan chip before multi-step work or an in-document Confirm."""
    labels = [str(s.get("label") or s.get("name") or "tool") for s in steps]
    labels = [lab for lab in labels if lab]
    if status == STATUS_WAITING_CONFIRM and labels:
        return labels
    if len(labels) >= 2:
        return labels
    return None


def receipt_summary(
    steps: list[dict[str, Any]],
    reply: str,
    status: str,
) -> str:
    if status == STATUS_WAITING_CONFIRM:
        waiting = next((s for s in steps if s.get("needs_confirm")), None)
        if waiting:
            detail = waiting.get("summary") or waiting.get("label") or "this action"
            return clip_summary(f"Waiting for Confirm — {detail}.")
        return "Waiting for Confirm in this document."
    if status == STATUS_FAILED:
        failed = [s for s in steps if not s.get("ok") and not s.get("needs_confirm")]
        if failed:
            last = failed[-1]
            return clip_summary(last.get("summary") or f"{last.get('label') or last.get('name')} failed.")
        return "That didn't finish."
    done = [s for s in steps if s.get("ok")]
    if done:
        bits = [s.get("summary") or s.get("label") or s.get("name") for s in done]
        bits = [b for b in bits if b]
        if bits:
            return clip_summary("; ".join(bits))
    first = (reply or "").strip().split("\n")[0].strip()
    return clip_summary(first) or "Answered. No PC action this turn."


def build_assist_receipt(
    tool_trace: list[dict[str, Any]] | None,
    *,
    reply: str = "",
    include: bool = True,
) -> Optional[dict[str, Any]]:
    """Structured receipt for an Assist / owner Do leg.

    Twin-only callers pass include=False and get None. An Assist leg
    with no tools still returns a receipt so the owner can see that
    nothing ran on the PC.
    """
    if not include:
        return None
    steps: list[dict[str, Any]] = []
    for row in tool_trace or []:
        step = step_from_trace(row)
        if step:
            steps.append(step)
    status = receipt_status(steps)
    return {
        "status": status,
        "summary": receipt_summary(steps, reply, status),
        "steps": steps,
        "plan": receipt_plan(steps, status),
    }


def receipt_for_role(
    role: str,
    tool_trace: list[dict[str, Any]] | None,
    *,
    reply: str = "",
) -> Optional[dict[str, Any]]:
    """Emit a receipt only when this turn is Assist (never Twin)."""
    include = (role or "").strip().lower() == "assistant"
    return build_assist_receipt(tool_trace, reply=reply, include=include)
