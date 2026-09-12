"""Owner pairing prefs — Slice 2 of OWNER_RAIL.md.

Assist and owner Twin sessions read these. Heir / caller / released
sessions must not receive the pairing productivity block.
"""
from __future__ import annotations

from typing import Any

PAIRING_STYLES = frozenset({"teammate", "wait", "proactive"})
DEFAULT_PAIRING_STYLE = "teammate"

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
    return default


def normalize_pairing_prefs(raw: dict | None = None) -> dict[str, Any]:
    src = raw or {}
    style = str(src.get("pairing_style") or DEFAULT_PAIRING_STYLE).strip().lower()
    if style not in PAIRING_STYLES:
        style = DEFAULT_PAIRING_STYLE
    return {
        "pairing_style": style,
        "act_default": _as_bool(src.get("act_default"), True),
        "close_loop": _as_bool(src.get("close_loop"), True),
        "remember_prefs": _as_bool(src.get("remember_prefs"), True),
    }


def pairing_prefs_from_user(user: dict | None) -> dict[str, Any]:
    return normalize_pairing_prefs(user)


def assist_pairing_block(prefs: dict | None = None) -> str:
    p = normalize_pairing_prefs(prefs)
    style = p["pairing_style"]
    if style == "wait":
        style_line = (
            "Wait for a clear ask before acting. Propose the next step in one sentence; "
            "do not start work until they say so."
        )
    elif style == "proactive":
        style_line = (
            "Be proactive: when the next useful step is obvious and safe, take it. "
            "Still wait in-document when Confirm is required."
        )
    else:
        style_line = (
            "Pair like a teammate: decide sensible defaults, do the job, and do not dump menus "
            "or ask them to pick from a list unless a real choice is required."
        )

    act_line = (
        "Act by default: do the work unless they asked you to wait or Confirm is required."
        if p["act_default"] and style != "wait"
        else "Do not change the PC until they clearly ask, except for lookup tools that only read."
    )
    close_line = (
        "Close the loop: after you act or look something up, report in 1–3 sentences of what you did or found."
        if p["close_loop"]
        else "Stay brief. Do not pad a closing recap if the result is already visible."
    )
    remember_line = (
        "Keep using this working style until they change it."
        if p["remember_prefs"]
        else "Treat this session's working style as temporary; do not assume it next time."
    )
    return (
        "HOW WE WORK (owner pairing):\n"
        f"- {style_line}\n"
        f"- {act_line}\n"
        f"- {close_line}\n"
        f"- {remember_line}\n"
        "- If Confirm is required, say what you will do and wait in-document. Do not invent a dialog.\n"
        "- Prefer tools over guessing. Never speak in first person as the owner."
    )


def twin_owner_pairing_block(prefs: dict | None = None) -> str:
    p = normalize_pairing_prefs(prefs)
    style = p["pairing_style"]
    if style == "wait":
        style_line = "Wait for a clear ask before filing or setting reminders."
    elif style == "proactive":
        style_line = "When the next useful archive step is obvious (a reminder, a search), take it."
    else:
        style_line = "Decide sensible defaults for capture, reminders, and archive search."

    act_line = (
        "Do the useful vault work without asking them to pick from a menu."
        if p["act_default"] and style != "wait"
        else "Propose the next vault step and wait for a yes."
    )
    lines = [
        "HOW WE WORK (owner sitting):",
        "- Be useful in their voice: capture, remind, search the archive, and close loops.",
        f"- {style_line}",
        f"- {act_line}",
    ]
    if p["close_loop"]:
        lines.append(
            "- Close the loop in 1–3 sentences when you filed, reminded, or found something."
        )
    if p["remember_prefs"]:
        lines.append("- Keep this working style until they change it.")
    lines.append(
        "- If they need the computer, say so plainly so Assist can Do. "
        "Never invent PC actions or biography."
    )
    return "\n".join(lines)


def is_owner_audience(audience: str | None) -> bool:
    return (audience or "owner").strip().lower() == "owner"
