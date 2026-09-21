"""Named specialists under one twin — Grok-bot-like teammates, not a second product.

The twin remains the person (first-person, vault-grounded). Assistants are
specialists the owner can pick or @mention. PC tools still belong to Assist;
heirs never inherit specialists or PC abilities.

Personas (existing) are tone/modes of the same twin. Assistants are a different
axis: who speaks this turn, with which tools.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from owner_rail import PC_TOOL_NAMES, ROUTE_ASSIST, ROUTE_TWIN

# Tools an owner may allowlist on a specialist. Intersection with
# tools_for_turn() still applies — Twin legs never receive PC tools.
KNOWN_TOOLS: tuple[dict[str, str], ...] = (
    {"id": "search_archive", "label": "Search archive", "group": "twin"},
    {"id": "save_memory", "label": "Save a memory", "group": "assist"},
    {"id": "set_reminder", "label": "Set a reminder", "group": "twin"},
    {"id": "list_recent_memories", "label": "Recent memories", "group": "twin"},
    {"id": "web_search", "label": "Web search", "group": "twin"},
    {"id": "web_fetch", "label": "Read a page", "group": "twin"},
    {"id": "get_weather", "label": "Weather", "group": "twin"},
    {"id": "run_skill", "label": "Run a skill", "group": "twin"},
    {"id": "open_on_pc", "label": "Open on this PC", "group": "assist"},
    {"id": "control_media", "label": "Media control", "group": "assist"},
    {"id": "set_volume", "label": "Volume", "group": "assist"},
    {"id": "power_action", "label": "Power", "group": "assist"},
    {"id": "notify_on_pc", "label": "Notify on PC", "group": "assist"},
    {"id": "type_text", "label": "Type text", "group": "assist"},
    {"id": "clipboard", "label": "Clipboard", "group": "assist"},
    {"id": "system_status", "label": "System status", "group": "assist"},
    {"id": "find_file", "label": "Find a file", "group": "assist"},
    {"id": "see_screen", "label": "See the screen", "group": "assist"},
    {"id": "run_command", "label": "Run a command", "group": "assist"},
)

KNOWN_TOOL_IDS = frozenset(t["id"] for t in KNOWN_TOOLS)

MENTION_RE = re.compile(r"^@([A-Za-z0-9][\w-]{0,47})\b[:,]?\s*", re.UNICODE)

DEFAULT_ASSISTANTS: tuple[dict[str, Any], ...] = (
    {
        "slug": "research",
        "name": "Research",
        "role": "Look things up. Web, weather, and public pages — never invent biography.",
        "tools_allowlist": ["web_search", "web_fetch", "get_weather", "search_archive"],
        "enabled": True,
        "speak_as": "specialist",
    },
    {
        "slug": "archive",
        "name": "Archive",
        "role": "Search what is already filed. Reminders. No PC control.",
        "tools_allowlist": ["search_archive", "set_reminder", "list_recent_memories"],
        "enabled": True,
        "speak_as": "specialist",
    },
    {
        "slug": "letters",
        "name": "Letters",
        "role": "Help draft and think about sealed letters. No PC tools. The twin stays the person.",
        "tools_allowlist": ["search_archive", "list_recent_memories"],
        "enabled": True,
        "speak_as": "specialist",
    },
    {
        "slug": "pc",
        "name": "PC",
        "role": "Do work on this computer. This is Assist — never first-person as the owner.",
        "tools_allowlist": [
            "open_on_pc",
            "control_media",
            "set_volume",
            "notify_on_pc",
            "type_text",
            "clipboard",
            "system_status",
            "find_file",
            "see_screen",
            "run_command",
            "search_archive",
        ],
        "enabled": True,
        "speak_as": "assist",
    },
)


def clean_tools(raw: Optional[list]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        key = str(item or "").strip()
        if key not in KNOWN_TOOL_IDS or key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= 24:
            break
    return out


def speak_as_for_tools(tools: list[str], requested: Optional[str] = None) -> str:
    if set(tools) & PC_TOOL_NAMES:
        return "assist"
    req = (requested or "").strip().lower()
    if req == "assist":
        return "assist"
    return "specialist"


def chat_role_for_specialist(assistant: Optional[dict]) -> str:
    """Map a specialist onto twin_runtime role=twin|assistant.

    PC / Assist specialists use the copilot role (PC tools allowed).
    Everyone else stays on the Twin leg so heirs and the gift voice stay clean.
    """
    if not assistant:
        return "twin"
    if (assistant.get("speak_as") or "").strip().lower() == "assist":
        return "assistant"
    if set(assistant.get("tools_allowlist") or []) & PC_TOOL_NAMES:
        return "assistant"
    return "twin"


def filter_tools_for_specialist(enabled_tools: set[str], assistant: Optional[dict]) -> set[str]:
    """Intersect the turn's legal tools with the specialist allowlist.

    Empty allowlist means "no extra tools" (still keep core search if present
    and the specialist is twin-side). PC tools never leak onto a twin-role
    specialist even if misconfigured.
    """
    names = set(enabled_tools)
    if not assistant:
        return names
    allow = set(clean_tools(assistant.get("tools_allowlist")))
    role = chat_role_for_specialist(assistant)
    if allow:
        names &= allow
    if role != "assistant":
        names -= PC_TOOL_NAMES
        names.discard("save_memory")
        names.discard("run_command")
        names.discard("see_screen")
        names.discard("open_on_pc")
        names.discard("type_text")
    return names


def specialist_prompt_block(assistant: dict, owner_name: str) -> str:
    who = owner_name or "the owner"
    name = (assistant.get("name") or "Assistant").strip()[:60]
    role = (assistant.get("role") or "").strip()[:400]
    speak = chat_role_for_specialist(assistant)
    tools = ", ".join(clean_tools(assistant.get("tools_allowlist"))) or "(none beyond core sitting)"
    if speak == "assistant":
        return (
            f"\n\n=== SPECIALIST THIS TURN: {name} ===\n"
            f"You are {name}, a specialist under {who}'s Heirloom twin. "
            f"You work FOR them on this PC. You are not their twin. "
            f"Never speak in first person as {who}. Never invent biography.\n"
            f"Your job: {role or 'Do the computer work and close the loop.'}\n"
            f"Tools you may use this turn: {tools}\n"
        )
    return (
        f"\n\n=== SPECIALIST THIS TURN: {name} ===\n"
        f"You are {name}, a specialist sitting with {who}'s twin. "
        f"The twin is the person — you are not them. Do not speak in first person as {who}. "
        f"Do not invent biography, dates, or family facts. "
        f"Stay inside your job: {role or 'help with this specialty.'}\n"
        f"If the question is really for the twin's own voice (memory, feeling, a story), "
        f"say so plainly so they can ask the twin.\n"
        f"Tools you may use this turn: {tools}\n"
    )


def slugify_name(name: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return (raw[:32] or "assistant")


def mention_from_text(text: str) -> tuple[Optional[str], str]:
    """Return (mention_slug_or_name, remainder)."""
    src = text or ""
    m = MENTION_RE.match(src)
    if not m:
        return None, src
    return m.group(1), src[m.end() :]


def match_assistant(assistants: list[dict], *, assistant_id: Optional[str] = None, mention: Optional[str] = None) -> Optional[dict]:
    enabled = [a for a in assistants if a.get("enabled") is not False]
    if assistant_id:
        for a in enabled:
            if a.get("assistant_id") == assistant_id:
                return a
        return None
    if not mention:
        return None
    key = mention.strip().lower()
    if not key:
        return None
    for a in enabled:
        if (a.get("slug") or "").lower() == key:
            return a
        if (a.get("name") or "").strip().lower() == key:
            return a
        if slugify_name(a.get("name") or "") == key:
            return a
        aid = (a.get("assistant_id") or "").lower()
        if aid and (aid == key or aid.endswith(key)):
            return a
    return None


def resolve_specialist_turn(
    text: str,
    assistants: list[dict],
    *,
    assistant_id: Optional[str] = None,
) -> dict[str, Any]:
    """Pick a specialist from an explicit id or a leading @mention."""
    mention, remainder = mention_from_text(text)
    chosen = match_assistant(assistants, assistant_id=assistant_id, mention=None)
    used_mention = False
    if chosen is None and mention:
        chosen = match_assistant(assistants, mention=mention)
        used_mention = chosen is not None
    message = remainder if used_mention else (text or "")
    if used_mention and not message.strip():
        message = text
    return {
        "assistant": chosen,
        "assistant_id": (chosen or {}).get("assistant_id") if chosen else None,
        "message": message,
        "mention": mention if used_mention else None,
        "role": chat_role_for_specialist(chosen),
        "route": ROUTE_ASSIST if chat_role_for_specialist(chosen) == "assistant" else ROUTE_TWIN,
    }


def public_assistant(doc: dict) -> dict:
    if not doc:
        return {}
    return {k: v for k, v in doc.items() if k != "_id"}
