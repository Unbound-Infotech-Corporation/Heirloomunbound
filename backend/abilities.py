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
CORE_TOOLS: set[str] = {
    "search_archive", "save_memory", "set_reminder", "list_recent_memories",
    "list_reminders", "complete_reminder", "whats_on_my_plate",
}


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
        "id": "email",
        "name": "Email",
        "tagline": "Connect Gmail or Outlook once. Your twin can read recent mail and send only after you say yes.",
        "icon": "mail",
        "category": "knowledge",
        "default_enabled": True,
        "requires_companion": False,
        "tools": ["read_inbox", "search_mail", "find_setup_mail", "send_email", "find_follow_ups"],
        "permissions": [
            {"id": "read_mail", "label": "Read recent mail (who it's from, the subject, a short snippet)"},
            {"id": "send_mail", "label": "Send mail only after you say yes"},
        ],
        "prompt_block": (
            "Email (enabled):\n"
            "- If they haven't connected, tell them to tap Connect my email. Google or Microsoft will ask — "
            "NEVER ask them to type an email password here.\n"
            "- `read_inbox()` — recent subjects + short snippets. Do not dump full bodies.\n"
            "- `search_mail(query)` — find mail matching a phrase.\n"
            "- `find_setup_mail()` — look for Pinokio / Ollama / Heirloom verification or magic-link mail and show the links. "
            "Help them tap the link. Do not create third-party accounts for them. Pinokio and ComfyUI usually don't need accounts.\n"
            "- `send_email(to, subject, body)` — first call WITHOUT confirmed so they see a draft. "
            "Only after they clearly say yes, call again with confirmed=true.\n"
            "- `find_follow_ups()` — mail that looks like it is waiting on them (questions, RSVPs, 'please confirm'). "
            "Offer to draft a reply with send_email; never send until they say yes.\n"
        ),
    },
    {
        "id": "calendar",
        "name": "Calendar",
        "tagline": "See what's on today and add a date — same Gmail or Outlook tap, never a password.",
        "icon": "calendar",
        "category": "companion",
        "default_enabled": True,
        "requires_companion": False,
        "tools": ["list_events", "create_event"],
        "permissions": [
            {"id": "read_calendar", "label": "See upcoming events on your calendar"},
            {"id": "write_calendar", "label": "Add an event only after you say yes"},
        ],
        "prompt_block": (
            "Calendar (enabled):\n"
            "- Uses the same Connect Gmail / Outlook tap as email. If a tool says to reconnect, tell them to tap it again "
            "so Google/Microsoft can share the calendar. NEVER ask for a password.\n"
            "- `list_events(days)` — what's coming up (default today).\n"
            "- `create_event(title, when)` — first call without confirmed so they see a draft. "
            "Only after they clearly say yes, call again with confirmed=true.\n"
        ),
    },
    {
        "id": "people",
        "name": "People & Calls",
        "tagline": "Look up family in your address book. Place a call only after you say yes.",
        "icon": "phone",
        "category": "companion",
        "default_enabled": True,
        "requires_companion": False,
        "tools": ["find_contact", "call_contact"],
        "permissions": [
            {"id": "read_contacts", "label": "Look up names in your Heirloom address book"},
            {"id": "place_call", "label": "Place a phone call only after you say yes"},
        ],
        "prompt_block": (
            "People & calls (enabled):\n"
            "- `find_contact(name)` — search the Heirloom address book (not their phone SIM).\n"
            "- `call_contact(name)` — first call WITHOUT confirmed. Only after they clearly say yes, call again with confirmed=true. "
            "If phone isn't set up, tell them to open Connect → Phone. Never invent a number.\n"
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
        "tagline": "Your twin can look at your screen and help — games, grammar, movies, errors.",
        "icon": "eye",
        "category": "computer",
        "default_enabled": True,
        "requires_companion": True,
        "tools": ["see_screen"],
        "permissions": [
            {"id": "capture_screen", "label": "Look at your screen to help (the picture is deleted after)"},
        ],
        "prompt_block": (
            "Screen vision (enabled) — you can SEE their computer when they ask for help with what's in front of them:\n"
            "- `see_screen(question)` — take a screenshot on the home PC, look at it, then coach.\n"
            "- ALWAYS call this when they ask you to look at the screen, help with a game, check grammar "
            "or writing on screen, identify a movie/show, read an error, or say 'look at this'.\n"
            "- Games: name the game if you can, say what's happening, give a clear next step. No spoilers unless asked.\n"
            "- Grammar/writing: quote the text you can read, then give specific edits.\n"
            "- Movies/TV: identify title/scene if you can; no unsolicited spoilers.\n"
            "- The picture is deleted after you look. If no PC is connected, tell them to open the Heirloom app "
            "on the home computer. Never ask for a password.\n"
            "- If the user message already includes a screen look, do NOT call see_screen again.\n"
        ),
    },
    {
        "id": "business",
        "name": "Business",
        "tagline": "Write Docs, read Search & YouTube, draft SEO, post on connected apps after you say yes.",
        "icon": "briefcase",
        "category": "work",
        "default_enabled": True,
        "requires_companion": False,
        "tools": [
            "write_google_doc", "write_google_sheet", "list_workspace_files",
            "research_seo", "post_to_social",
            "read_search_console", "list_youtube", "list_tiktok",
            "write_notion_page", "save_to_dropbox", "send_mailchimp",
        ],
        "permissions": [
            {"id": "write_docs", "label": "Create a Google Doc or Notion page only after you say yes"},
            {"id": "write_sheets", "label": "Create a spreadsheet or Dropbox file only after you say yes"},
            {"id": "research_marketing", "label": "Look up public pages and Search Console to draft an SEO plan"},
            {"id": "post_social", "label": "Post on connected apps only after you say yes"},
        ],
        "prompt_block": (
            "Business (enabled):\n"
            "- Docs/Sheets/YouTube/Search Console use the same Connect Gmail tap. If a tool says to reconnect, "
            "tell them to tap Connect Gmail again so Google can share Docs, Search, and YouTube. NEVER ask for a password.\n"
            "- `write_google_doc(title, body)` — first call WITHOUT confirmed so they see a draft. "
            "Write the full plan in `body` (business plan, letter, campaign). After they say yes, call again with confirmed=true. "
            "Then share the Google link. If the home PC is open, it can open the Doc.\n"
            "- `write_google_sheet(title, headers, rows)` — same confirm pattern. Use for budgets, keyword lists, posting calendars.\n"
            "- `list_workspace_files()` — Docs/Sheets Heirloom already made.\n"
            "- `research_seo(topic, location, audience)` — public-web starter plan (phrases, two-week posts, page outline). "
            "Do not invent ranking numbers. For real Google numbers, call `read_search_console()`.\n"
            "- `read_search_console(site, days)` — Google's numbers for sites they already verified. Never invent rankings.\n"
            "- `list_youtube()` — channel + recent uploads. Cannot upload a video file.\n"
            "- `list_tiktok()` — recent TikToks after Connect TikTok. New clips need a video file.\n"
            "- `post_to_social(network, text)` — twitter (X), linkedin, discord, reddit, pinterest, wordpress, slack. "
            "First call WITHOUT confirmed. Extra args: title, image_url (Pinterest), subreddit, channel. "
            "If they haven't connected, tell them to tap Connect on Settings. "
            "Instagram/Facebook/Threads need Meta review. Bluesky/WhatsApp/Telegram are not wired. NEVER ask for a password.\n"
            "- `write_notion_page(title, body)` / `save_to_dropbox(filename, body)` / `send_mailchimp(subject, body)` — "
            "draft first, confirmed=true after they say yes. Notion: they must share a page with Heirloom.\n"
        ),
    },
    {
        "id": "creative",
        "name": "Creative",
        "tagline": "Describe a picture, clip, or song. We sketch it on your computer, then open Photoshop, CapCut, or your music app.",
        "icon": "palette",
        "category": "create",
        "default_enabled": True,
        "requires_companion": True,
        "tools": ["create_artwork", "edit_video", "make_music", "open_studio"],
        "permissions": [
            {"id": "make_media", "label": "Make pictures, videos, and songs on your computer after you say yes"},
        ],
        "prompt_block": (
            "Creative (enabled — needs the desktop app running):\n"
            "- I sketch on the home PC (Pinokio / ComfyUI: Fooocus or Flux for pictures, WAN for short clips, ACE-Step for songs), "
            "then open the app they already have. I cannot click every Photoshop, CapCut, Premiere, or DAW control. "
            "I cannot edit a timeline inside YouTube Studio or TikTok — I can only open those websites.\n"
            "- Pinokio and ComfyUI do not need an account. NEVER ask for a Photoshop, Adobe, CapCut, or music-app password.\n"
            "- If no PC is connected, tell them to open the Heirloom app on the home computer.\n"
            "- GPU work needs a yes first: call WITHOUT confirmed so they see the plan, then after they clearly say yes, "
            "call again with confirmed=true.\n"
            "- `create_artwork(prompt, open_in)` — pictures. Default studio is Photoshop (Photopea if Photoshop isn't installed).\n"
            "- `edit_video(prompt, open_in, source)` — short local clip, then CapCut / Premiere / DaVinci. "
            "open_in=youtube or tiktok only opens the website.\n"
            "- `make_music(prompt, open_in)` — short sketch, then Ableton / FL Studio / Logic / GarageBand / REAPER.\n"
            "- `open_studio(app)` — just open the app they named. No confirm.\n"
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


async def is_enabled(user_id: str, ability_id: str) -> bool:
    return ability_id in await enabled_ability_ids(user_id)


async def enabled_tool_names(user_id: str) -> set[str]:
    """Core tools + every tool from the user's enabled abilities."""
    names = set(CORE_TOOLS)
    ids = await enabled_ability_ids(user_id)
    for aid in ids:
        names.update(ABILITY_BY_ID[aid]["tools"])
    return names


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
