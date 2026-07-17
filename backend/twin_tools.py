"""Twin tool-use — the 8 canonical AI assistant tools, mapped to Heirloom.

Each tool has:
  • an OpenAI-format schema (LlmChat.with_tools() normalises across providers)
  • an async executor `exec_<name>(user_id, args) → {"summary": str, "ui": dict?}`

`summary` goes back to the model as the tool_result content — keep it terse
and factual so Claude can weave it into its reply naturally. `ui` (optional)
is a light-weight dict the frontend can render as a chip after the fact.

References:
- Anthropic tool-use spec:  https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview
- OpenAI function calling:  https://platform.openai.com/docs/guides/function-calling
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Coroutine

import requests
from bs4 import BeautifulSoup

from deps import EMERGENT_LLM_KEY, db

# ---------------- Tool schemas ---------------- #

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_archive",
            "description": (
                "Search the owner's own memories, stories, values, and beliefs. "
                "Call this whenever the user asks about their past, their opinions, or "
                "anything specific to their life. This is your primary source of truth "
                "about who they are — prefer it over guessing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords or a natural-language search"},
                    "limit": {"type": "integer", "description": "How many entries to fetch (1-15)", "default": 6},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "Capture something the user just told you as a new archive entry. "
                "Call this when the user shares a story, a belief, a value, or a preference "
                "worth remembering long-term (e.g. 'I hated the Cabo trip', 'I believe in loyalty over cleverness'). "
                "Ask before calling if it's ambiguous."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The full memory/belief/story text"},
                    "type": {
                        "type": "string",
                        "enum": ["memory", "story", "value", "advice", "quote"],
                        "description": "What kind of entry this is",
                        "default": "memory",
                    },
                    "title": {"type": "string", "description": "Short title (auto-generated if omitted)"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": (
                "Create a reminder for the user. Use this when they say 'remind me to X' or "
                "explicitly ask to be nudged about something later."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "what": {"type": "string", "description": "What to remind them about"},
                    "when": {
                        "type": "string",
                        "description": "When (ISO 8601 datetime OR natural language like 'tomorrow at 9am', 'in 30 minutes')",
                    },
                },
                "required": ["what"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_memories",
            "description": "Show recent archive entries — useful for 'what have I been thinking about?' or 'summarise my week'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "How far back to look", "default": 7},
                    "limit": {"type": "integer", "description": "Max entries to return", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city or location (uses Open-Meteo, no API key).",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name, or 'latitude,longitude'"},
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the live web for current information. Use this only when the user's "
                "question depends on recent/factual outside knowledge (news, prices, releases, "
                "how-to). Do NOT use it for information about the owner themselves — use search_archive for that."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": (
                "Fetch a specific URL and return its readable text. Useful after web_search "
                "to read the top result, or when the user shares a link."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Full https:// URL"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_skill",
            "description": (
                "Trigger one of the user's configured webhook skills (smart-home controls, "
                "IFTTT applets, custom scripts). Only call this when the user explicitly asks "
                "for an action AND the skill name clearly matches the intent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_id": {"type": "string", "description": "The skill_id from the injected skills list"},
                },
                "required": ["skill_id"],
            },
        },
    },
]


# ---------------- Executors ---------------- #

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str, n: int = 240) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


async def exec_search_archive(user_id: str, args: dict) -> dict:
    query = (args.get("query") or "").strip()
    limit = int(args.get("limit") or 6)
    limit = max(1, min(15, limit))
    if not query:
        return {"summary": "No query provided.", "ui": {"count": 0}}

    rows: list[dict] = []
    try:
        from semantic_search import semantic_search
        rows = await semantic_search(user_id, query, limit=limit)
    except Exception:
        rows = []

    if not rows:
        # Regex fallback
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        cursor = db.entries.find(
            {
                "user_id": user_id,
                "$or": [
                    {"title": {"$regex": pattern}},
                    {"content": {"$regex": pattern}},
                    {"tags": {"$regex": pattern}},
                ],
            },
            {"_id": 0, "entry_id": 1, "type": 1, "title": 1, "content": 1, "created_at": 1, "tags": 1},
        ).sort("created_at", -1).limit(limit)
        rows = await cursor.to_list(length=limit)

    if not rows:
        cursor = db.entries.find(
            {"user_id": user_id},
            {"_id": 0, "entry_id": 1, "type": 1, "title": 1, "content": 1, "created_at": 1, "tags": 1},
        ).sort("created_at", -1).limit(min(3, limit))
        rows = await cursor.to_list(length=min(3, limit))
        if not rows:
            return {"summary": f"No archive entries matched '{query}' — the archive appears empty.", "ui": {"count": 0}}
        header = f"No exact match for '{query}'. Falling back to the {len(rows)} most-recent entries:"
    else:
        header = f"Found {len(rows)} entries matching '{query}':"
    lines = [header]
    for r in rows:
        lines.append(
            f"- [{r.get('type', 'note')}] {r.get('title') or '(untitled)'} — {_truncate(r.get('content', ''), 200)}"
        )
    return {"summary": "\n".join(lines), "ui": {"count": len(rows), "query": query}}


async def exec_save_memory(user_id: str, args: dict) -> dict:
    from routers.executor_lock import assert_writable, is_legacy_locked
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "authenticity_mode": 1, "legacy_locked": 1})
    if await is_legacy_locked(user_id) or (user or {}).get("authenticity_mode") == "retrieve_only":
        return {"summary": "Archive is in retrieve-only mode — nothing was saved.", "ui": {"saved": False}}
    await assert_writable(user_id)
    content = (args.get("content") or "").strip()
    if not content:
        return {"summary": "No content given — nothing was saved.", "ui": {"saved": False}}
    kind = args.get("type") or "memory"
    if kind not in ("memory", "story", "value", "advice", "quote"):
        kind = "memory"
    title = (args.get("title") or "").strip()
    if not title:
        # Auto-title from first line / first sentence
        first = content.split("\n", 1)[0].split(". ", 1)[0].strip()
        title = _truncate(first, 60) or "Captured by twin"
    entry_id = f"ent_{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    doc = {
        "entry_id": entry_id,
        "user_id": user_id,
        "type": kind,
        "title": title,
        "content": content,
        "tags": ["twin-captured"],
        "audio_url": None,
        "source": "twin_tool",
        "created_at": now,
        "updated_at": now,
    }
    await db.entries.insert_one(doc)
    return {
        "summary": f"Saved as {kind}: '{title}'.",
        "ui": {"saved": True, "entry_id": entry_id, "type": kind, "title": title},
    }


async def exec_set_reminder(user_id: str, args: dict) -> dict:
    from routers.executor_lock import assert_writable, is_legacy_locked
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "authenticity_mode": 1})
    if await is_legacy_locked(user_id) or (user or {}).get("authenticity_mode") == "retrieve_only":
        return {"summary": "Retrieve-only mode — reminders cannot be created.", "ui": {"created": False}}
    await assert_writable(user_id)
    what = (args.get("what") or "").strip()
    if not what:
        return {"summary": "No reminder text given.", "ui": {"created": False}}
    when_str = (args.get("when") or "").strip()
    due_iso: str | None = None
    parsed_hint = ""
    if when_str:
        try:
            import dateparser  # local import — optional dep
            dt = dateparser.parse(when_str, settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": True})
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                due_iso = dt.astimezone(timezone.utc).isoformat()
                parsed_hint = f" (interpreted '{when_str}' as {dt.strftime('%b %d, %Y at %H:%M %Z')})"
        except Exception as exc:  # noqa: BLE001
            print(f"[twin_tools] dateparser: {exc}")

    rid = f"rem_{uuid.uuid4().hex[:12]}"
    doc = {
        "reminder_id": rid,
        "user_id": user_id,
        "text": what,
        "notes": None,
        "due_at": due_iso,
        "status": "open",
        "snooze_until": None,
        "completed_at": None,
        "delivered_at": None,
        "created_at": _now_iso(),
    }
    await db.reminders.insert_one(doc)
    when_label = due_iso or "(no time set)"
    return {
        "summary": f"Reminder created: '{what}' — due {when_label}{parsed_hint}.",
        "ui": {"created": True, "reminder_id": rid, "text": what, "due_at": due_iso},
    }


async def exec_list_recent_memories(user_id: str, args: dict) -> dict:
    days = int(args.get("days") or 7)
    limit = min(25, max(1, int(args.get("limit") or 10)))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cursor = db.entries.find(
        {"user_id": user_id, "created_at": {"$gte": since}},
        {"_id": 0, "entry_id": 1, "type": 1, "title": 1, "content": 1, "created_at": 1},
    ).sort("created_at", -1).limit(limit)
    rows = await cursor.to_list(length=limit)
    if not rows:
        return {"summary": f"No archive entries in the last {days} days.", "ui": {"count": 0}}
    lines = [f"Last {days} days — {len(rows)} entries:"]
    for r in rows:
        lines.append(f"- {r.get('created_at', '')[:10]} [{r.get('type')}] {r.get('title') or '(untitled)'} — {_truncate(r.get('content', ''), 140)}")
    return {"summary": "\n".join(lines), "ui": {"count": len(rows), "days": days}}


def _sync_weather(location: str) -> dict:
    """Runs in a thread — Open-Meteo geocoding + current weather."""
    loc = location.strip()
    lat: float | None = None
    lon: float | None = None
    label = loc
    # Direct lat,lon form
    if "," in loc and all(part.strip().replace("-", "").replace(".", "").isdigit() for part in loc.split(",", 1)):
        try:
            lat_s, lon_s = loc.split(",", 1)
            lat = float(lat_s.strip())
            lon = float(lon_s.strip())
        except ValueError:
            pass
    if lat is None or lon is None:
        # Geocode
        gr = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": loc, "count": 1},
            timeout=10,
        )
        if gr.status_code != 200:
            return {"error": f"Geocoding failed ({gr.status_code})."}
        results = (gr.json() or {}).get("results") or []
        if not results:
            return {"error": f"No location match for '{loc}'."}
        hit = results[0]
        lat = hit["latitude"]
        lon = hit["longitude"]
        label = ", ".join(
            v for v in [hit.get("name"), hit.get("admin1"), hit.get("country")] if v
        )
    wr = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,wind_speed_10m,weather_code",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
        },
        timeout=10,
    )
    if wr.status_code != 200:
        return {"error": f"Weather fetch failed ({wr.status_code})."}
    data = (wr.json() or {}).get("current") or {}
    return {"label": label, "data": data}


_WEATHER_CODES = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog",
    51: "drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "rain", 63: "rain", 65: "heavy rain",
    71: "snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm w/ hail", 99: "thunderstorm w/ heavy hail",
}


async def exec_get_weather(user_id: str, args: dict) -> dict:
    location = (args.get("location") or "").strip()
    if not location:
        return {"summary": "No location provided.", "ui": {"ok": False}}
    try:
        result = await asyncio.to_thread(_sync_weather, location)
    except Exception as exc:  # noqa: BLE001
        return {"summary": f"Weather lookup failed: {exc!s}", "ui": {"ok": False}}
    if "error" in result:
        return {"summary": result["error"], "ui": {"ok": False}}
    d = result["data"]
    code = int(d.get("weather_code") or 0)
    conditions = _WEATHER_CODES.get(code, f"code {code}")
    summary = (
        f"Weather for {result['label']}: {conditions}. "
        f"Temp {d.get('temperature_2m')}°F "
        f"(feels {d.get('apparent_temperature')}°F). "
        f"Humidity {d.get('relative_humidity_2m')}%. Wind {d.get('wind_speed_10m')} mph."
    )
    return {"summary": summary, "ui": {"ok": True, "label": result["label"], "conditions": conditions}}


def _sync_ddg_search(query: str, max_results: int) -> list[dict]:
    from ddgs import DDGS

    with DDGS() as d:
        return list(d.text(query, max_results=max_results))


async def exec_web_search(user_id: str, args: dict) -> dict:
    query = (args.get("query") or "").strip()
    max_results = min(10, max(1, int(args.get("max_results") or 5)))
    if not query:
        return {"summary": "No search query.", "ui": {"count": 0}}
    try:
        rows = await asyncio.to_thread(_sync_ddg_search, query, max_results)
    except Exception as exc:  # noqa: BLE001
        return {"summary": f"Web search failed: {exc!s}", "ui": {"count": 0}}
    if not rows:
        return {"summary": f"No web results for '{query}'.", "ui": {"count": 0}}
    lines = [f"Top {len(rows)} web results for '{query}':"]
    for r in rows:
        title = _truncate(r.get("title") or "", 100)
        body = _truncate(r.get("body") or "", 200)
        href = r.get("href") or ""
        lines.append(f"- {title} — {body}\n  {href}")
    return {"summary": "\n".join(lines), "ui": {"count": len(rows), "query": query}}


def _sync_fetch_readable(url: str) -> dict:
    r = requests.get(url, timeout=15, headers={"User-Agent": "HeirloomTwin/0.3"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    # Kill scripts/styles/nav
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    # Prefer <article> / main; fall back to body
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = re.sub(r"\n{3,}", "\n\n", main.get_text("\n", strip=True))
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else url
    return {"title": title, "text": text[:6000]}


async def exec_web_fetch(user_id: str, args: dict) -> dict:
    url = (args.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return {"summary": "Invalid URL — must start with http(s)://", "ui": {"ok": False}}
    try:
        result = await asyncio.to_thread(_sync_fetch_readable, url)
    except Exception as exc:  # noqa: BLE001
        return {"summary": f"Fetch failed: {exc!s}", "ui": {"ok": False, "url": url}}
    summary = f"Fetched '{result['title']}' ({url}):\n\n{result['text']}"
    return {"summary": summary, "ui": {"ok": True, "url": url, "title": result["title"]}}


async def exec_run_skill(user_id: str, args: dict) -> dict:
    from routers.skills import invoke_skill_internal

    skill_id = (args.get("skill_id") or "").strip()
    if not skill_id:
        return {"summary": "No skill_id given.", "ui": {"ok": False}}
    try:
        result = await invoke_skill_internal(user_id, skill_id)
    except Exception as exc:  # noqa: BLE001
        return {"summary": f"Skill invocation failed: {exc!s}", "ui": {"ok": False, "skill_id": skill_id}}
    if result.get("ok"):
        return {
            "summary": f"Skill '{skill_id}' fired successfully (status {result.get('status', 200)}).",
            "ui": {"ok": True, "skill_id": skill_id},
        }
    err = result.get("error") or f"HTTP {result.get('status')}"
    return {"summary": f"Skill '{skill_id}' failed: {err}", "ui": {"ok": False, "skill_id": skill_id, "error": err}}


# ---------------- PC control (companion) tools ---------------- #
# These queue commands to the user's connected companion PC and (when useful)
# wait for the result to come back through /companion/result or the screenshot
# upload. If no PC is connected/awake, they return a friendly note so the twin
# can tell the user to open their Heirloom desktop app.

_DEVICE_ONLINE_WINDOW_SEC = 120  # a device that polled within this window is "awake"


async def _active_device(user_id: str) -> dict | None:
    dev = await db.companion_devices.find_one(
        {"user_id": user_id, "revoked": False},
        {"_id": 0},
        sort=[("last_seen", -1)],
    )
    return dev


def _device_is_awake(dev: dict | None) -> bool:
    if not dev or not dev.get("last_seen"):
        return False
    try:
        seen = datetime.fromisoformat(dev["last_seen"].replace("Z", "+00:00"))
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return False
    return (datetime.now(timezone.utc) - seen).total_seconds() <= _DEVICE_ONLINE_WINDOW_SEC


async def _queue_pc_command(user_id: str, kind: str, payload: dict) -> str:
    cmd_id = f"cmd_{uuid.uuid4().hex[:10]}"
    await db.companion_commands.insert_one({
        "cmd_id": cmd_id,
        "user_id": user_id,
        "kind": kind,
        "payload": payload,
        "status": "queued",
        "result": None,
        "created_at": _now_iso(),
        "completed_at": None,
    })
    return cmd_id


async def _wait_for_command_result(cmd_id: str, user_id: str, timeout: float = 12.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        doc = await db.companion_commands.find_one(
            {"cmd_id": cmd_id, "user_id": user_id}, {"_id": 0}
        )
        if doc and doc.get("status") in ("done", "error"):
            return doc
        await asyncio.sleep(0.8)
    return None


async def _pc_precheck(user_id: str) -> tuple[dict | None, dict | None]:
    """Returns (device, error_result). If error_result is not None, bail early."""
    dev = await _active_device(user_id)
    if not dev:
        return None, {
            "summary": "No companion PC is connected to this account. The user needs to install and open the Heirloom desktop app first.",
            "ui": {"ok": False, "reason": "no_device"},
        }
    if not _device_is_awake(dev):
        return dev, {
            "summary": (
                f"The companion PC '{dev.get('name', 'PC')}' is registered but appears to be offline "
                f"(last seen {dev.get('last_seen') or 'never'}). The command was queued and will run when the PC comes online."
            ),
            "ui": {"ok": False, "reason": "offline", "device": dev.get("name")},
        }
    return dev, None


async def _queue_fire_and_forget(user_id: str, kind: str, payload: dict, label: str, wait: float = 8.0) -> dict:
    dev, err = await _pc_precheck(user_id)
    cmd_id = await _queue_pc_command(user_id, kind, payload)
    if err:  # offline: queued, will run later
        return err
    res = await _wait_for_command_result(cmd_id, user_id, timeout=wait)
    if res is None:
        return {"summary": f"{label} — sent to your PC (still running).", "ui": {"ok": True, "kind": kind, "pending": True}}
    if res.get("status") == "error":
        return {"summary": f"{label} failed on the PC: {res.get('result', 'unknown error')}", "ui": {"ok": False, "kind": kind}}
    out = (res.get("result") or "").strip()
    return {"summary": f"{label} — done{(': ' + out) if out and out not in ('opened', 'ok', 'spoken') else ''}.", "ui": {"ok": True, "kind": kind, "output": out[:200]}}


async def exec_open_on_pc(user_id: str, args: dict) -> dict:
    target = (args.get("target") or "").strip()
    if not target:
        return {"summary": "No app or website given.", "ui": {"ok": False}}
    kind_hint = (args.get("kind") or "auto").lower()
    is_url = target.lower().startswith(("http://", "https://")) or (
        kind_hint == "website"
    ) or (kind_hint == "auto" and "." in target and " " not in target and "/" not in target[:1])
    if is_url:
        url = target if target.lower().startswith(("http://", "https://")) else f"https://{target}"
        return await _queue_fire_and_forget(user_id, "open_url", {"url": url}, f"Opening {target}")
    return await _queue_fire_and_forget(user_id, "open_app", {"name": target}, f"Opening {target}")


async def exec_control_media(user_id: str, args: dict) -> dict:
    action = (args.get("action") or "").strip().lower()
    valid = {"playpause", "play", "pause", "next", "previous", "prev", "volume_up", "volume_down", "mute"}
    if action not in valid:
        return {"summary": f"Unknown media action '{action}'. Use one of: {', '.join(sorted(valid))}.", "ui": {"ok": False}}
    return await _queue_fire_and_forget(user_id, "media_key", {"action": action}, f"Media: {action}", wait=6.0)


async def exec_set_volume(user_id: str, args: dict) -> dict:
    try:
        level = int(args.get("level"))
    except (TypeError, ValueError):
        return {"summary": "Volume level must be a number 0-100.", "ui": {"ok": False}}
    level = max(0, min(100, level))
    return await _queue_fire_and_forget(user_id, "set_volume", {"level": level}, f"Setting volume to {level}%", wait=6.0)


async def exec_power_action(user_id: str, args: dict) -> dict:
    action = (args.get("action") or "").strip().lower()
    valid = {"lock", "sleep", "shutdown", "restart"}
    if action not in valid:
        return {"summary": f"Unknown power action '{action}'. Use lock, sleep, shutdown, or restart.", "ui": {"ok": False}}
    destructive = action in ("shutdown", "restart")
    if destructive and not bool(args.get("confirmed")):
        return {
            "summary": (
                f"'{action}' is destructive and needs confirmation. Tell the user exactly what will happen "
                f"and ask them to confirm. Only after they clearly say yes, call power_action again with confirmed=true."
            ),
            "ui": {"ok": False, "needs_confirm": True, "action": action},
        }
    return await _queue_fire_and_forget(user_id, "power", {"action": action}, f"Power: {action}", wait=5.0)


async def exec_notify_on_pc(user_id: str, args: dict) -> dict:
    title = (args.get("title") or "Heirloom").strip()
    message = (args.get("message") or "").strip()
    if not message:
        return {"summary": "No notification message given.", "ui": {"ok": False}}
    return await _queue_fire_and_forget(user_id, "notify", {"title": title, "message": message}, "Notification shown on your PC", wait=6.0)


async def exec_type_text(user_id: str, args: dict) -> dict:
    text = (args.get("text") or "")
    if not text.strip():
        return {"summary": "No text to type.", "ui": {"ok": False}}
    return await _queue_fire_and_forget(user_id, "type_text", {"text": text}, "Typed into your active window", wait=8.0)


async def exec_clipboard(user_id: str, args: dict) -> dict:
    mode = (args.get("mode") or "get").strip().lower()
    if mode == "set":
        text = args.get("text") or ""
        if not text:
            return {"summary": "No text to copy.", "ui": {"ok": False}}
        return await _queue_fire_and_forget(user_id, "clipboard_set", {"text": text}, "Copied to your PC clipboard", wait=6.0)
    # get
    dev, err = await _pc_precheck(user_id)
    if err:
        return err
    cmd_id = await _queue_pc_command(user_id, "clipboard_get", {})
    res = await _wait_for_command_result(cmd_id, user_id, timeout=15.0)
    if res is None:
        return {"summary": "The PC didn't return the clipboard in time.", "ui": {"ok": False}}
    if res.get("status") == "error":
        return {"summary": f"Couldn't read clipboard: {res.get('result')}", "ui": {"ok": False}}
    content = res.get("result") or "(clipboard is empty)"
    return {"summary": f"Clipboard contents:\n{_truncate(content, 1500)}", "ui": {"ok": True, "chars": len(content)}}


async def exec_system_status(user_id: str, args: dict) -> dict:
    dev, err = await _pc_precheck(user_id)
    if err:
        return err
    cmd_id = await _queue_pc_command(user_id, "system_status", {})
    res = await _wait_for_command_result(cmd_id, user_id, timeout=18.0)
    if res is None:
        return {"summary": "The PC didn't report its status in time.", "ui": {"ok": False}}
    if res.get("status") == "error":
        return {"summary": f"Status check failed: {res.get('result')}", "ui": {"ok": False}}
    return {"summary": f"System status for {dev.get('name', 'the PC')}:\n{res.get('result', '')}", "ui": {"ok": True}}


async def exec_run_command(user_id: str, args: dict) -> dict:
    command = (args.get("command") or "").strip()
    if not command:
        return {"summary": "No command given.", "ui": {"ok": False}}
    if not bool(args.get("confirmed")):
        return {
            "summary": (
                f"Running a shell command is powerful and needs confirmation. Show the user the exact command "
                f"(`{command}`), explain what it does, and ask them to confirm. Only after a clear yes, call "
                f"run_command again with confirmed=true."
            ),
            "ui": {"ok": False, "needs_confirm": True, "command": command[:200]},
        }
    dev, err = await _pc_precheck(user_id)
    if err:
        return err
    cmd_id = await _queue_pc_command(user_id, "shell", {"command": command})
    res = await _wait_for_command_result(cmd_id, user_id, timeout=25.0)
    if res is None:
        return {"summary": "Command sent — still running on the PC.", "ui": {"ok": True, "pending": True}}
    status = res.get("status")
    out = _truncate(res.get("result") or "", 1500)
    return {"summary": f"Command {'succeeded' if status == 'done' else 'failed'}:\n{out}", "ui": {"ok": status == "done"}}


async def exec_find_file(user_id: str, args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"summary": "No file/folder name given.", "ui": {"ok": False}}
    open_it = bool(args.get("open_it"))
    dev, err = await _pc_precheck(user_id)
    if err:
        return err
    cmd_id = await _queue_pc_command(user_id, "find_file", {"query": query, "open": open_it})
    res = await _wait_for_command_result(cmd_id, user_id, timeout=20.0)
    if res is None:
        return {"summary": "The PC didn't finish searching in time.", "ui": {"ok": False}}
    if res.get("status") == "error":
        return {"summary": f"File search failed: {res.get('result')}", "ui": {"ok": False}}
    return {"summary": res.get("result") or "No matches found.", "ui": {"ok": True, "opened": open_it}}


async def exec_see_screen(user_id: str, args: dict) -> dict:
    question = (args.get("question") or "Describe what is currently on the screen in a clear, concise way.").strip()
    dev, err = await _pc_precheck(user_id)
    if err:
        return err
    cmd_id = await _queue_pc_command(user_id, "screenshot", {})
    # Wait for the companion to upload the capture (stored in companion_screens by cmd_id).
    deadline = time.monotonic() + 22.0
    shot: dict | None = None
    while time.monotonic() < deadline:
        shot = await db.companion_screens.find_one({"cmd_id": cmd_id, "user_id": user_id}, {"_id": 0})
        if shot:
            break
        cmd = await db.companion_commands.find_one({"cmd_id": cmd_id, "user_id": user_id}, {"_id": 0})
        if cmd and cmd.get("status") == "error":
            return {"summary": f"Couldn't capture the screen: {cmd.get('result')}", "ui": {"ok": False}}
        await asyncio.sleep(0.8)
    if not shot or not shot.get("image_b64"):
        return {"summary": "The PC didn't send a screenshot in time.", "ui": {"ok": False}}
    try:
        from emergentintegrations.llm.chat import ImageContent, LlmChat, StreamDone, TextDelta, UserMessage

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"see_{cmd_id}",
            system_message="You are looking at a screenshot of the user's computer screen. Answer their question about it directly and briefly.",
        ).with_model("anthropic", "claude-sonnet-4-6")
        text = ""
        async for ev in chat.stream_message(
            UserMessage(text=question, file_contents=[ImageContent(image_base64=shot["image_b64"])])
        ):
            if isinstance(ev, TextDelta):
                text += ev.content
            elif isinstance(ev, StreamDone):
                break
        text = text.strip() or "(no description returned)"
    except Exception as exc:  # noqa: BLE001
        return {"summary": f"Screen analysis failed: {exc!s}", "ui": {"ok": False}}
    finally:
        # Clean up the stored image so we don't retain screen contents.
        try:
            await db.companion_screens.delete_one({"cmd_id": cmd_id})
        except Exception:  # noqa: BLE001
            pass
    return {"summary": f"Looking at your screen: {text}", "ui": {"ok": True}}


COMPUTER_TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "open_on_pc",
        "description": "Open an application OR a website on the user's connected companion PC. Use for 'open Spotify', 'launch Steam', 'pull up youtube.com'.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "App name (e.g. 'Spotify', 'notepad') or a website/URL (e.g. 'youtube.com')"},
            "kind": {"type": "string", "enum": ["app", "website", "auto"], "default": "auto"},
        }, "required": ["target"]},
    }},
    {"type": "function", "function": {
        "name": "control_media",
        "description": "Control media playback / system volume on the PC: play/pause, skip track, nudge volume up/down, or mute.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["playpause", "next", "previous", "volume_up", "volume_down", "mute"]},
        }, "required": ["action"]},
    }},
    {"type": "function", "function": {
        "name": "set_volume",
        "description": "Set the PC's system volume to an absolute level (0-100).",
        "parameters": {"type": "object", "properties": {
            "level": {"type": "integer", "description": "0 = mute, 100 = max"},
        }, "required": ["level"]},
    }},
    {"type": "function", "function": {
        "name": "power_action",
        "description": "Lock, sleep, shut down, or restart the PC. shutdown/restart are destructive: you MUST confirm with the user first, then call again with confirmed=true.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["lock", "sleep", "shutdown", "restart"]},
            "confirmed": {"type": "boolean", "default": False, "description": "Set true ONLY after the user explicitly confirms a shutdown/restart"},
        }, "required": ["action"]},
    }},
    {"type": "function", "function": {
        "name": "notify_on_pc",
        "description": "Pop a native desktop notification (toast) on the user's PC.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "default": "Heirloom"},
            "message": {"type": "string"},
        }, "required": ["message"]},
    }},
    {"type": "function", "function": {
        "name": "type_text",
        "description": "Type text into whatever window is currently focused on the PC (e.g. draft an email, fill a field).",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
        }, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "clipboard",
        "description": "Read the PC clipboard (mode='get') or write text to it (mode='set').",
        "parameters": {"type": "object", "properties": {
            "mode": {"type": "string", "enum": ["get", "set"], "default": "get"},
            "text": {"type": "string", "description": "Text to copy (only for mode='set')"},
        }, "required": ["mode"]},
    }},
    {"type": "function", "function": {
        "name": "see_screen",
        "description": "Take a screenshot of the user's PC and analyse it with vision to answer a question about what's on screen. Use for 'what's on my screen?', 'read this error for me', 'what tab am I on?'.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "What to look for / answer about the screen"},
        }},
    }},
    {"type": "function", "function": {
        "name": "system_status",
        "description": "Report the PC's live hardware status: CPU, RAM, disk, GPU (incl. NVIDIA), and battery. Use for 'how's my rig doing?'.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a shell/terminal command on the PC. Powerful and risky: you MUST show the command, explain it, and confirm with the user, then call again with confirmed=true.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "confirmed": {"type": "boolean", "default": False},
        }, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "find_file",
        "description": "Search the user's common folders (Desktop, Documents, Downloads) for a file or folder by name, and optionally open it.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Name or partial name to search for"},
            "open_it": {"type": "boolean", "default": False, "description": "Open the top match after finding it"},
        }, "required": ["query"]},
    }},
]

TOOL_SCHEMAS += COMPUTER_TOOL_SCHEMAS


TOOL_EXECUTORS: dict[str, Callable[[str, dict], Coroutine[Any, Any, dict]]] = {
    "search_archive": exec_search_archive,
    "save_memory": exec_save_memory,
    "set_reminder": exec_set_reminder,
    "list_recent_memories": exec_list_recent_memories,
    "get_weather": exec_get_weather,
    "web_search": exec_web_search,
    "web_fetch": exec_web_fetch,
    "run_skill": exec_run_skill,
    "open_on_pc": exec_open_on_pc,
    "control_media": exec_control_media,
    "set_volume": exec_set_volume,
    "power_action": exec_power_action,
    "notify_on_pc": exec_notify_on_pc,
    "type_text": exec_type_text,
    "clipboard": exec_clipboard,
    "see_screen": exec_see_screen,
    "system_status": exec_system_status,
    "run_command": exec_run_command,
    "find_file": exec_find_file,
}


async def execute_tool(name: str, user_id: str, args: dict) -> dict:
    """Public entrypoint. Returns {summary, ui?} — never raises."""
    fn = TOOL_EXECUTORS.get(name)
    if fn is None:
        return {"summary": f"Unknown tool '{name}'.", "ui": {"error": "unknown_tool"}}
    try:
        return await fn(user_id, args or {})
    except Exception as exc:  # noqa: BLE001
        return {"summary": f"Tool '{name}' errored: {exc!s}", "ui": {"error": str(exc)[:200]}}
