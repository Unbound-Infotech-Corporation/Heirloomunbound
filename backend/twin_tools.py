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
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Coroutine

import requests
from bs4 import BeautifulSoup

from deps import db

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
    # Cheap regex-anywhere search over title+content — fine for archive sizes < few thousand
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
        # Fall back to most recent — helps when the query is a broad topic
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


TOOL_EXECUTORS: dict[str, Callable[[str, dict], Coroutine[Any, Any, dict]]] = {
    "search_archive": exec_search_archive,
    "save_memory": exec_save_memory,
    "set_reminder": exec_set_reminder,
    "list_recent_memories": exec_list_recent_memories,
    "get_weather": exec_get_weather,
    "web_search": exec_web_search,
    "web_fetch": exec_web_fetch,
    "run_skill": exec_run_skill,
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
