"""Abilities — Heirloom's modular capability framework.

An "ability" is a togglable bundle the owner switches on for their twin. Each
declares: the tools it grants, whether it needs the companion PC, the
permissions it touches (browser-style trust), and a curated prompt block that
teaches the twin how/when to use it.

Only ENABLED abilities inject their tools into the twin — so the tool list
stays lean and the model stays sharp. The four memory tools are CORE (always
on): they are the twin's own mind, not an add-on.

State lives in the `user_abilities` collection:
    {user_id, ability_id, enabled: bool, granted_permissions: [str], updated_at}
Missing rows fall back to each ability's `default_enabled`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from deps import db

# Tools that are ALWAYS available — the twin's memory. Not part of any ability.
CORE_TOOLS: set[str] = {"search_archive", "save_memory", "set_reminder", "list_recent_memories"}


ABILITIES: list[dict] = [
    {
        "id": "web",
        "name": "Web & Weather",
        "tagline": "Let your twin look things up online and check the weather.",
        "icon": "globe",
        "category": "knowledge",
        "default_enabled": True,
        "requires_companion": False,
        "tools": ["web_search", "web_fetch", "get_weather"],
        "permissions": [
            {"id": "internet", "label": "Search the web and read public pages"},
        ],
        "prompt_block": (
            "Web & weather (enabled):\n"
            "- `web_search(query)` — ONLY for outside-world facts (news, prices, releases). Never for questions about the owner.\n"
            "- `web_fetch(url)` — read the readable text of a specific URL.\n"
            "- `get_weather(location)` — current conditions.\n"
        ),
    },
    {
        "id": "music",
        "name": "Music",
        "tagline": "Say “play some Pink Floyd” and your twin cues it up on your PC or browser.",
        "icon": "music",
        "category": "companion",
        "default_enabled": True,
        "requires_companion": False,
        "tools": [],  # handled by the music-intent short-circuit, gated on this ability
        "permissions": [
            {"id": "open_media", "label": "Open your chosen music service"},
        ],
        "prompt_block": (
            "Music (enabled): if the owner asks to play/queue a song or artist, it is handled automatically — "
            "just acknowledge naturally.\n"
        ),
    },
    {
        "id": "smart_home",
        "name": "Smart Home & Skills",
        "tagline": "Trigger your webhooks, IFTTT applets, and smart-home scenes by voice.",
        "icon": "wrench",
        "category": "companion",
        "default_enabled": True,
        "requires_companion": False,
        "tools": ["run_skill"],
        "permissions": [
            {"id": "trigger_webhooks", "label": "Call the webhook skills you've configured"},
        ],
        "prompt_block": (
            "Smart home & skills (enabled):\n"
            "- `run_skill(skill_id)` — trigger one of the owner's configured webhook skills, ONLY when they explicitly "
            "ask for the action AND a skill clearly matches.\n"
        ),
    },
    {
        "id": "pc_control",
        "name": "PC Control",
        "tagline": "Open apps, control media & volume, notifications, typing, files, and power.",
        "icon": "monitor",
        "category": "computer",
        "default_enabled": True,
        "requires_companion": True,
        "tools": [
            "open_on_pc", "control_media", "set_volume", "power_action",
            "notify_on_pc", "type_text", "clipboard", "system_status", "find_file",
        ],
        "permissions": [
            {"id": "launch", "label": "Open apps and websites"},
            {"id": "control_system", "label": "Control media, volume, power, and notifications"},
            {"id": "input", "label": "Type text and use your clipboard"},
            {"id": "read_system", "label": "Read system status and find files"},
        ],
        "prompt_block": (
            "PC control (enabled — needs the desktop app running; if a tool says no PC is connected, warmly tell them to open it):\n"
            "- `open_on_pc(target)` — launch an app or website.\n"
            "- `control_media(action)` / `set_volume(level)` — playback + volume.\n"
            "- `power_action(action)` — lock/sleep/shutdown/restart. For shutdown & restart you MUST explain and get an explicit yes, then call again with confirmed=true.\n"
            "- `notify_on_pc(title, message)` — desktop toast.\n"
            "- `type_text(text)` — type into their focused window.\n"
            "- `clipboard(mode)` — read or write their clipboard.\n"
            "- `system_status()` — CPU/RAM/GPU/disk/battery.\n"
            "- `find_file(query)` — locate/open a file in their common folders.\n"
        ),
    },
    {
        "id": "screen_vision",
        "name": "Screen Vision",
        "tagline": "“What's on my screen?” — your twin takes a look and helps.",
        "icon": "eye",
        "category": "computer",
        "default_enabled": True,
        "requires_companion": True,
        "tools": ["see_screen"],
        "permissions": [
            {"id": "capture_screen", "label": "Capture and analyse your screen (image is deleted after)"},
        ],
        "prompt_block": (
            "Screen vision (enabled): `see_screen(question)` — screenshot + look at what's on their screen "
            "('what's on my screen?', 'read this error').\n"
        ),
    },
    {
        "id": "terminal",
        "name": "Terminal Access",
        "tagline": "Advanced: let your twin run shell commands (with confirmation).",
        "icon": "terminal",
        "category": "computer",
        "default_enabled": False,  # most powerful — opt in
        "requires_companion": True,
        "tools": ["run_command"],
        "permissions": [
            {"id": "run_shell", "label": "Run terminal/shell commands on your PC"},
        ],
        "prompt_block": (
            "Terminal (enabled): `run_command(command)` — run a shell command. Powerful & risky: always show the "
            "command, explain it, and confirm with the owner, then call again with confirmed=true.\n"
        ),
    },
    {
        "id": "phone",
        "name": "Phone",
        "tagline": "Answer and place family calls as the Twin — cloned voice, vault-grounded.",
        "icon": "phone",
        "category": "presence",
        "default_enabled": False,
        "requires_companion": False,
        "tools": [],
        "permissions": [
            {"id": "phone_line", "label": "Give this Twin a phone line for family calls"},
        ],
        "prompt_block": (
            "Phone (enabled): you may already be on a live family call. Keep replies short and spoken. "
            "Do not file memories from the call. Do not drive the PC.\n"
        ),
    },
]

ABILITY_BY_ID: dict[str, dict] = {a["id"]: a for a in ABILITIES}
TOOL_TO_ABILITY: dict[str, str] = {tool: a["id"] for a in ABILITIES for tool in a["tools"]}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_states(user_id: str) -> dict[str, dict]:
    """Every ability merged with the user's stored state (defaults fill gaps)."""
    rows = await db.user_abilities.find({"user_id": user_id}, {"_id": 0}).to_list(length=100)
    by_id = {r["ability_id"]: r for r in rows}
    states: dict[str, dict] = {}
    for a in ABILITIES:
        row = by_id.get(a["id"])
        if row is not None:
            states[a["id"]] = {
                "enabled": bool(row.get("enabled")),
                "granted_permissions": row.get("granted_permissions") or [],
            }
        else:
            states[a["id"]] = {
                "enabled": bool(a["default_enabled"]),
                "granted_permissions": [p["id"] for p in a["permissions"]] if a["default_enabled"] else [],
            }
    return states


async def enabled_ability_ids(user_id: str) -> set[str]:
    states = await get_states(user_id)
    return {aid for aid, s in states.items() if s["enabled"]}


def tool_names_for_abilities(enabled_ids: set[str]) -> set[str]:
    """Core tools + tools from the given enabled ability ids (no DB hit)."""
    names = set(CORE_TOOLS)
    for aid in enabled_ids:
        ability = ABILITY_BY_ID.get(aid)
        if ability:
            names.update(ability["tools"])
    return names


async def is_enabled(user_id: str, ability_id: str) -> bool:
    return ability_id in await enabled_ability_ids(user_id)


async def enabled_tool_names(user_id: str) -> set[str]:
    """Core tools + every tool from the user's enabled abilities."""
    return tool_names_for_abilities(await enabled_ability_ids(user_id))


async def set_state(user_id: str, ability_id: str, enabled: bool, granted_permissions: list[str] | None = None) -> dict:
    await db.user_abilities.update_one(
        {"user_id": user_id, "ability_id": ability_id},
        {"$set": {
            "user_id": user_id,
            "ability_id": ability_id,
            "enabled": enabled,
            "granted_permissions": granted_permissions or [],
            "updated_at": _now_iso(),
        }},
        upsert=True,
    )
    return {"ability_id": ability_id, "enabled": enabled, "granted_permissions": granted_permissions or []}


def build_abilities_prompt(enabled_ids: set[str]) -> str:
    """The dynamic capability section for the twin's system prompt — only the
    abilities the owner has turned on."""
    blocks = [ABILITY_BY_ID[a["id"]]["prompt_block"] for a in ABILITIES if a["id"] in enabled_ids]
    if not blocks:
        return ""
    return "\nExtra abilities the owner has enabled (call silently — a chip shows when a tool fires):\n" + "\n".join(blocks)
