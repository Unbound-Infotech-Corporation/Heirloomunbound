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
            "name": "list_reminders",
            "description": "List the owner's open reminders and to-dos. Use for 'what's on my list', 'what did I ask you to remind me'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 12},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_reminder",
            "description": "Mark a reminder done after the owner says it is finished. Use the reminder_id from list_reminders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string"},
                },
                "required": ["reminder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "whats_on_my_plate",
            "description": (
                "Daily briefing: today's calendar, open reminders, a peek at recent mail, and on-this-day memories. "
                "Use for 'good morning', 'what's on today', 'catch me up', 'what's on my plate'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "How many days ahead (1-7)", "default": 1},
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

    # 1. Try semantic search first — best recall when the user has an
    #    embeddings provider configured. Silent fall-through on any error
    #    keeps the twin working even if the local server is down.
    try:
        from routers.memory import semantic_lookup  # local import to avoid cycles
        mode, sem_rows = await semantic_lookup(user_id, query, limit=limit)
    except Exception:  # noqa: BLE001
        mode, sem_rows = "keyword", []

    if sem_rows and mode == "semantic":
        header = f"Found {len(sem_rows)} entries semantically related to '{query}':"
        lines = [header]
        for r in sem_rows:
            score = r.get("score")
            score_str = f" · {score:.2f}" if isinstance(score, (int, float)) else ""
            lines.append(
                f"- [{r.get('type', 'note')}] {r.get('title') or '(untitled)'}{score_str} — "
                f"{_truncate(r.get('content', ''), 200)}"
            )
        return {"summary": "\n".join(lines), "ui": {"count": len(sem_rows), "query": query, "mode": "semantic"}}

    # 2. Keyword fallback (also what runs when no embeddings provider is set)
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
    return {"summary": "\n".join(lines), "ui": {"count": len(rows), "query": query, "mode": "keyword"}}


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


async def exec_list_reminders(user_id: str, args: dict) -> dict:
    limit = min(20, max(1, int(args.get("limit") or 12)))
    rows = await db.reminders.find(
        {"user_id": user_id, "status": "open"},
        {"_id": 0, "reminder_id": 1, "text": 1, "due_at": 1, "status": 1},
    ).sort([("due_at", 1), ("created_at", -1)]).to_list(length=limit)
    if not rows:
        return {"summary": "No open reminders.", "ui": {"kind": "reminders", "items": []}}
    lines = ["Open reminders:"]
    for r in rows:
        due = (r.get("due_at") or "no date")[:16]
        lines.append(f"- {r.get('reminder_id')}: {r.get('text')} (due {due})")
    return {"summary": "\n".join(lines), "ui": {"kind": "reminders", "items": rows}}


async def exec_complete_reminder(user_id: str, args: dict) -> dict:
    rid = (args.get("reminder_id") or "").strip()
    if not rid:
        return {"summary": "Need a reminder_id from list_reminders.", "ui": {"ok": False}}
    res = await db.reminders.update_one(
        {"reminder_id": rid, "user_id": user_id, "status": "open"},
        {"$set": {"status": "done", "completed_at": _now_iso()}},
    )
    if res.matched_count == 0:
        return {"summary": "I couldn't find that open reminder.", "ui": {"ok": False}}
    return {"summary": f"Marked {rid} done.", "ui": {"ok": True, "reminder_id": rid}}


def _parse_when(when_str: str) -> datetime | None:
    raw = (when_str or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        import dateparser
        dt = dateparser.parse(raw, settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": True})
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


async def exec_whats_on_my_plate(user_id: str, args: dict) -> dict:
    days = max(1, min(int(args.get("days") or 1), 7))
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    sections: list[str] = []
    ui: dict[str, Any] = {"kind": "briefing", "days": days}

    rem_rows = await db.reminders.find(
        {
            "user_id": user_id,
            "status": "open",
            "$or": [{"due_at": None}, {"due_at": {"$lte": end.isoformat()}}],
        },
        {"_id": 0, "reminder_id": 1, "text": 1, "due_at": 1},
    ).sort("due_at", 1).to_list(length=12)
    ui["reminders"] = rem_rows
    if rem_rows:
        lines = [f"- {r.get('text')} (due {(r.get('due_at') or 'sometime')[:16]})" for r in rem_rows]
        sections.append("Reminders:\n" + "\n".join(lines))
    else:
        sections.append("Reminders: none open for this window.")

    cal_lines = "Calendar isn't connected. Tap Connect Gmail if they want the twin to see the day."
    bundle, status = await _mail_bundle(user_id)
    if bundle:
        provider, token, _profile = bundle
        from services.day_assist import (
            CALENDAR_RECONNECT,
            format_events,
            list_google_events,
            list_graph_events,
            scope_has_calendar,
        )
        conn = await db.oauth_connections.find_one(
            {"user_id": user_id, "provider": provider},
            {"_id": 0, "scope": 1},
        )
        if not scope_has_calendar((conn or {}).get("scope") or ""):
            cal_lines = CALENDAR_RECONNECT
        else:
            try:
                events = list_google_events(token, days=days) if provider == "google" else list_graph_events(token, days=days)
                ui["events"] = events
                cal_lines = "Calendar:\n" + (format_events(events) or "(nothing on the calendar)")
            except RuntimeError as exc:
                cal_lines = str(exc)
    elif (status or {}).get("connected"):
        cal_lines = "Calendar sign-in expired. Tap Connect Gmail again."
    sections.append(cal_lines)

    if bundle:
        from services import mail_inbox as mail
        try:
            rows = _list_owner_mail(bundle[0], bundle[1])
            ui["mail"] = [mail.public_row(r) for r in rows[:5]]
            if rows:
                sections.append("Recent mail:\n" + _mail_summary(rows[:5]))
        except RuntimeError:
            pass

    mm, dd = f"{now.month:02d}", f"{now.day:02d}"
    memory_rows = await db.entries.find(
        {"user_id": user_id, "created_at": {"$regex": f"-{mm}-{dd}T"}},
        {"_id": 0, "title": 1, "created_at": 1, "type": 1},
    ).sort("created_at", -1).to_list(length=3)
    ui["on_this_day"] = memory_rows
    if memory_rows:
        bits = [f"- {r.get('created_at', '')[:10]} {r.get('title') or r.get('type')}" for r in memory_rows]
        sections.append("On this day in the archive:\n" + "\n".join(bits))

    header = f"What's on their plate ({days} day{'s' if days != 1 else ''}):"
    return {"summary": header + "\n\n" + "\n\n".join(sections), "ui": ui}


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
    from services.screen_coach import VISION_SYSTEM, coach_question_for

    raw_q = (args.get("question") or "").strip()
    question = raw_q or coach_question_for("")
    dev, err = await _pc_precheck(user_id)
    if err:
        return err
    cmd_id = await _queue_pc_command(user_id, "screenshot", {})
    # Wait for the companion to upload the capture (stored in companion_screens by cmd_id).
    deadline = time.monotonic() + 30.0
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
        return {
            "summary": "The PC didn't send a screenshot in time. Open the Heirloom app on the home computer and try again.",
            "ui": {"ok": False},
        }
    try:
        from emergentintegrations.llm.chat import ImageContent, LlmChat, StreamDone, TextDelta, UserMessage

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"see_{cmd_id}",
            system_message=VISION_SYSTEM,
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


MAIL_CONNECT_HINT = (
    "Email isn't connected. Tell them: tap Connect my email (Gmail or Outlook) on Settings or Avatar Studio. "
    "Google or Microsoft will ask — Heirloom never sees the password. "
    "Do not ask them to type an email password here."
)
MAIL_EXPIRED_HINT = (
    "Email sign-in expired. Tell them to tap Connect my email again. Never ask for their password."
)


async def _mail_bundle(user_id: str):
    from routers.oauth import get_fresh_mail_token, public_mail_status
    bundle = await get_fresh_mail_token(user_id)
    if bundle:
        return bundle, None
    status = await public_mail_status(user_id)
    return None, status


def _list_owner_mail(provider: str, token: str, *, query: str = "", setup_only: bool = False):
    from services import mail_inbox as mail
    if provider == "google":
        return mail.list_gmail(token, query=query, setup_only=setup_only)
    return mail.list_graph(token, query=query, setup_only=setup_only)


def _mail_summary(rows: list, *, setup: bool = False) -> str:
    from services import mail_inbox as mail
    if not rows:
        return ""
    lines = []
    for raw in rows:
        row = mail.public_row(raw, setup=setup)
        line = f"{row['from']} — {row['subject']}: {row['snippet']}"
        if setup and row.get("links"):
            line += "\n  Links: " + " · ".join(row["links"])
        lines.append(line)
    return "\n".join(lines)


async def exec_read_inbox(user_id: str, args: dict) -> dict:
    bundle, status = await _mail_bundle(user_id)
    if not bundle:
        hint = MAIL_EXPIRED_HINT if (status or {}).get("connected") else MAIL_CONNECT_HINT
        return {"summary": hint, "ui": {"kind": "mail", "connected": False}}
    provider, token, _profile = bundle
    from services import mail_inbox as mail
    try:
        rows = _list_owner_mail(provider, token, query=str(args.get("query") or ""))
    except RuntimeError as exc:
        return {"summary": str(exc), "ui": {"kind": "mail", "error": str(exc)}}
    public = [mail.public_row(r) for r in rows]
    if not public:
        return {"summary": "No recent mail matched.", "ui": {"kind": "mail", "messages": []}}
    return {"summary": "Recent mail:\n" + _mail_summary(rows), "ui": {"kind": "mail", "messages": public}}


async def exec_search_mail(user_id: str, args: dict) -> dict:
    query = (args.get("query") or "").strip()
    if not query:
        return {"summary": "Need a search phrase.", "ui": {"kind": "mail", "error": "missing_query"}}
    return await exec_read_inbox(user_id, {"query": query})


async def exec_find_setup_mail(user_id: str, args: dict) -> dict:
    bundle, status = await _mail_bundle(user_id)
    if not bundle:
        hint = MAIL_EXPIRED_HINT if (status or {}).get("connected") else MAIL_CONNECT_HINT
        return {"summary": hint, "ui": {"kind": "mail", "connected": False, "setup": True}}
    provider, token, _profile = bundle
    from services import mail_inbox as mail
    try:
        rows = _list_owner_mail(provider, token, setup_only=True)
    except RuntimeError as exc:
        return {"summary": str(exc), "ui": {"kind": "mail", "error": str(exc), "setup": True}}
    public = [mail.public_row(r, setup=True) for r in rows]
    if not public:
        return {
            "summary": (
                "No setup or confirmation emails in the last few weeks. "
                "Pinokio and ComfyUI usually don't send mail — they install on the home computer without accounts."
            ),
            "ui": {"kind": "mail", "messages": [], "setup": True},
        }
    return {
        "summary": (
            "Setup / confirmation mail (show the links; they tap them — do not create accounts for them):\n"
            + _mail_summary(rows, setup=True)
        ),
        "ui": {"kind": "mail", "messages": public, "setup": True},
    }


async def exec_send_email(user_id: str, args: dict) -> dict:
    from services import mail_inbox as mail
    to = (args.get("to") or "").strip()
    subject = (args.get("subject") or "").strip()
    body = (args.get("body") or "").strip()
    if not mail.valid_recipient(to):
        return {"summary": "That doesn't look like an email address.", "ui": {"kind": "mail", "error": "bad_to"}}
    if not subject or not body:
        return {"summary": "Need a subject and a message.", "ui": {"kind": "mail", "error": "missing_fields"}}
    if not bool(args.get("confirmed")):
        return {
            "summary": mail.draft_preview(to, subject, body),
            "ui": {"kind": "mail", "needs_confirm": True, "to": to, "subject": subject},
        }
    bundle, status = await _mail_bundle(user_id)
    if not bundle:
        hint = MAIL_EXPIRED_HINT if (status or {}).get("connected") else MAIL_CONNECT_HINT
        return {"summary": hint, "ui": {"kind": "mail", "connected": False}}
    provider, token, _profile = bundle
    try:
        if provider == "google":
            mail.send_gmail(token, to, subject, body)
        else:
            mail.send_graph(token, to, subject, body)
    except RuntimeError as exc:
        return {"summary": str(exc), "ui": {"kind": "mail", "error": str(exc)}}
    return {
        "summary": f"Sent to {to} with subject '{subject}'.",
        "ui": {"kind": "mail", "sent": True, "to": to},
    }


async def exec_find_follow_ups(user_id: str, args: dict) -> dict:
    bundle, status = await _mail_bundle(user_id)
    if not bundle:
        hint = MAIL_EXPIRED_HINT if (status or {}).get("connected") else MAIL_CONNECT_HINT
        return {"summary": hint, "ui": {"kind": "mail", "connected": False, "follow_ups": True}}
    provider, token, _profile = bundle
    from services import mail_inbox as mail
    try:
        rows = _list_owner_mail(provider, token)
    except RuntimeError as exc:
        return {"summary": str(exc), "ui": {"kind": "mail", "error": str(exc)}}
    hits = [r for r in rows if mail.looks_like_follow_up(r.get("subject") or "", r.get("snippet") or "", r.get("from") or "")]
    public = [mail.public_row(r) for r in hits]
    if not public:
        return {
            "summary": "Nothing in recent mail looks like it is waiting on them.",
            "ui": {"kind": "mail", "messages": [], "follow_ups": True},
        }
    return {
        "summary": (
            "Mail that may need a reply (draft with send_email — do not send until they say yes):\n"
            + _mail_summary(hits)
        ),
        "ui": {"kind": "mail", "messages": public, "follow_ups": True},
    }


async def _calendar_session(user_id: str):
    from services.day_assist import CALENDAR_RECONNECT, scope_has_calendar
    bundle, status = await _mail_bundle(user_id)
    if not bundle:
        hint = MAIL_EXPIRED_HINT if (status or {}).get("connected") else MAIL_CONNECT_HINT
        return None, hint
    provider, token, _profile = bundle
    conn = await db.oauth_connections.find_one(
        {"user_id": user_id, "provider": provider},
        {"_id": 0, "scope": 1},
    )
    if not scope_has_calendar((conn or {}).get("scope") or ""):
        return None, CALENDAR_RECONNECT
    return (provider, token), None


async def exec_list_events(user_id: str, args: dict) -> dict:
    from services.day_assist import format_events, list_google_events, list_graph_events, public_event
    days = max(1, min(int(args.get("days") or 1), 14))
    session, err = await _calendar_session(user_id)
    if not session:
        return {"summary": err or MAIL_CONNECT_HINT, "ui": {"kind": "calendar", "connected": False}}
    provider, token = session
    try:
        rows = list_google_events(token, days=days) if provider == "google" else list_graph_events(token, days=days)
    except RuntimeError as exc:
        return {"summary": str(exc), "ui": {"kind": "calendar", "error": str(exc)}}
    public = [public_event(r) for r in rows]
    if not public:
        return {"summary": "Nothing on the calendar in that window.", "ui": {"kind": "calendar", "events": []}}
    return {"summary": "Upcoming:\n" + format_events(rows), "ui": {"kind": "calendar", "events": public}}


async def exec_create_event(user_id: str, args: dict) -> dict:
    from services.day_assist import create_google_event, create_graph_event, event_preview
    title = (args.get("title") or "").strip()
    when_str = (args.get("when") or "").strip()
    where = (args.get("where") or "").strip()
    notes = (args.get("notes") or "").strip()
    try:
        minutes = int(args.get("duration_minutes") or 60)
    except (TypeError, ValueError):
        minutes = 60
    minutes = max(15, min(minutes, 480))
    if not title:
        return {"summary": "Need a title for the event.", "ui": {"kind": "calendar", "error": "missing_title"}}
    start = _parse_when(when_str)
    if not start:
        return {"summary": "I couldn't tell when that is. Ask for a day and time.", "ui": {"kind": "calendar", "error": "bad_when"}}
    end = start + timedelta(minutes=minutes)
    start_iso, end_iso = start.isoformat(), end.isoformat()
    if not bool(args.get("confirmed")):
        return {
            "summary": event_preview(title, start_iso, end_iso, where, notes),
            "ui": {"kind": "calendar", "needs_confirm": True, "title": title, "start": start_iso},
        }
    session, err = await _calendar_session(user_id)
    if not session:
        return {"summary": err or MAIL_CONNECT_HINT, "ui": {"kind": "calendar", "connected": False}}
    provider, token = session
    try:
        if provider == "google":
            create_google_event(token, title, start_iso, end_iso, where=where, notes=notes)
        else:
            create_graph_event(token, title, start_iso, end_iso, where=where, notes=notes)
    except RuntimeError as exc:
        return {"summary": str(exc), "ui": {"kind": "calendar", "error": str(exc)}}
    return {
        "summary": f"Added '{title}' to the calendar at {start_iso[:16]}.",
        "ui": {"kind": "calendar", "created": True, "title": title},
    }


async def exec_find_contact(user_id: str, args: dict) -> dict:
    name = (args.get("name") or "").strip()
    if not name:
        return {"summary": "Need a name to look up.", "ui": {"kind": "people", "error": "missing_name"}}
    rows = await db.contacts.find(
        {"user_id": user_id},
        {"_id": 0, "contact_id": 1, "name": 1, "phone": 1, "note": 1},
    ).sort("name", 1).to_list(length=200)
    needle = name.lower()
    hits = [c for c in rows if needle in (c.get("name") or "").lower()]
    if not hits:
        return {
            "summary": f"No one named '{name}' in the Heirloom address book. They can add people on the Phone page.",
            "ui": {"kind": "people", "contacts": []},
        }
    lines = [f"- {c.get('name')} ({c.get('phone')})" + (f" — {c.get('note')}" if c.get("note") else "") for c in hits[:8]]
    return {"summary": "Address book:\n" + "\n".join(lines), "ui": {"kind": "people", "contacts": hits[:8]}}


async def exec_call_contact(user_id: str, args: dict) -> dict:
    name = (args.get("name") or "").strip()
    if not name:
        return {"summary": "Need a name to call.", "ui": {"kind": "people", "error": "missing_name"}}
    rows = await db.contacts.find(
        {"user_id": user_id},
        {"_id": 0, "contact_id": 1, "name": 1, "phone": 1},
    ).to_list(length=200)
    needle = name.lower()
    hits = [c for c in rows if needle in (c.get("name") or "").lower()]
    if not hits:
        return {
            "summary": f"I don't have '{name}' in the address book. Add them on the Phone page first. Never invent a number.",
            "ui": {"kind": "people", "contacts": []},
        }
    if len(hits) > 1 and not args.get("contact_id"):
        names = ", ".join(c.get("name") or "" for c in hits[:6])
        return {
            "summary": f"A few people match '{name}': {names}. Ask which one, then call that exact name.",
            "ui": {"kind": "people", "contacts": hits[:6], "needs_pick": True},
        }
    chosen = hits[0]
    if args.get("contact_id"):
        chosen = next((c for c in hits if c.get("contact_id") == args.get("contact_id")), chosen)
    opening = (args.get("opening_line") or "").strip() or f"Hi {chosen['name'].split()[0]}, this is a call from the digital twin."
    if not bool(args.get("confirmed")):
        return {
            "summary": (
                f"I'm about to call {chosen['name']} at the number in the address book. "
                "Ask them to confirm, then call call_contact again with confirmed=true."
            ),
            "ui": {"kind": "people", "needs_confirm": True, "name": chosen["name"], "contact_id": chosen.get("contact_id")},
        }
    from fastapi import HTTPException
    from routers.twilio_voice import OutboundReq, outbound_call
    try:
        result = await outbound_call(
            OutboundReq(to_number=chosen["phone"], opening_line=opening[:400]),
            user={"user_id": user_id},
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Couldn't place the call."
        if "Twilio" in detail or "Outbound" in detail:
            detail = "Phone isn't ready. Tell them to open Connect → Phone and turn on outbound calls."
        return {"summary": detail, "ui": {"kind": "people", "error": detail}}
    except Exception as exc:  # noqa: BLE001
        return {"summary": f"Couldn't place the call: {exc!s}"[:200], "ui": {"kind": "people", "ok": False}}
    return {
        "summary": f"Calling {chosen['name']} now.",
        "ui": {"kind": "people", "calling": True, "name": chosen["name"], "call_sid": (result or {}).get("call_sid")},
    }


async def _google_workspace_token(user_id: str, *, sheets: bool = False):
    from routers.oauth import get_fresh_google_token
    from services.google_workspace import DOCS_EXPIRED, DOCS_RECONNECT, scope_has_docs, scope_has_sheets
    row = await db.oauth_connections.find_one(
        {"user_id": user_id, "provider": "google"},
        {"_id": 0, "scope": 1},
    )
    if not row:
        return None, (
            "Google isn't connected. Tap Connect Gmail on Settings. Google will ask — "
            "we never see the password. That same tap also shares Docs and Sheets."
        )
    token = await get_fresh_google_token(user_id)
    if not token:
        return None, DOCS_EXPIRED
    scope = row.get("scope") or ""
    ok = scope_has_sheets(scope) if sheets else scope_has_docs(scope)
    if not ok:
        return None, DOCS_RECONNECT
    return token, None


async def _maybe_open_url(user_id: str, url: str) -> str:
    if not url:
        return ""
    try:
        dev = await _active_device(user_id)
        if not dev or not _device_is_awake(dev):
            return ""
        await _queue_pc_command(user_id, "open_url", {"url": url})
        return " I opened it on your computer."
    except Exception:  # noqa: BLE001
        return ""


async def exec_write_google_doc(user_id: str, args: dict) -> dict:
    from services.google_workspace import (
        business_plan_outline,
        create_google_document,
        doc_preview,
    )
    title = (args.get("title") or "").strip()[:120]
    body = (args.get("body") or "").strip()
    kind = (args.get("kind") or "").strip().lower()
    offering = (args.get("offering") or "").strip()
    audience = (args.get("audience") or "").strip()
    if not title:
        title = "Business plan" if kind in ("business_plan", "plan") else "Untitled"
    if not body and kind in ("business_plan", "plan"):
        body = business_plan_outline(title, offering, audience)
    if not body:
        return {
            "summary": "Need the words for the Doc. Write the plan in `body`, then try again.",
            "ui": {"kind": "docs", "error": "missing_body"},
        }
    if not bool(args.get("confirmed")):
        return {
            "summary": doc_preview(title, body),
            "ui": {"kind": "docs", "needs_confirm": True, "title": title},
        }
    token, err = await _google_workspace_token(user_id, sheets=False)
    if not token:
        return {"summary": err, "ui": {"kind": "docs", "connected": False}}
    try:
        created = await asyncio.to_thread(create_google_document, token, title, body)
    except RuntimeError as exc:
        return {"summary": str(exc), "ui": {"kind": "docs", "error": str(exc)}}
    opened = await _maybe_open_url(user_id, created["url"])
    return {
        "summary": f"Created Google Doc '{created['title']}': {created['url']}.{opened}",
        "ui": {"kind": "docs", "created": True, "url": created["url"], "title": created["title"]},
    }


async def exec_write_google_sheet(user_id: str, args: dict) -> dict:
    from services.google_workspace import (
        create_google_spreadsheet,
        normalize_headers,
        normalize_rows,
        sheet_preview,
    )
    title = (args.get("title") or "").strip()[:120] or "Untitled sheet"
    headers = normalize_headers(args.get("headers"))
    rows = normalize_rows(args.get("rows"), column_count=len(headers) or 1)
    if not headers and not rows:
        return {
            "summary": "Need columns or rows for the spreadsheet.",
            "ui": {"kind": "sheets", "error": "empty"},
        }
    if not bool(args.get("confirmed")):
        return {
            "summary": sheet_preview(title, headers, rows),
            "ui": {"kind": "sheets", "needs_confirm": True, "title": title},
        }
    token, err = await _google_workspace_token(user_id, sheets=True)
    if not token:
        return {"summary": err, "ui": {"kind": "sheets", "connected": False}}
    try:
        created = await asyncio.to_thread(create_google_spreadsheet, token, title, headers, rows)
    except RuntimeError as exc:
        return {"summary": str(exc), "ui": {"kind": "sheets", "error": str(exc)}}
    opened = await _maybe_open_url(user_id, created["url"])
    return {
        "summary": f"Created spreadsheet '{created['title']}': {created['url']}.{opened}",
        "ui": {"kind": "sheets", "created": True, "url": created["url"], "title": created["title"]},
    }


async def exec_list_workspace_files(user_id: str, args: dict) -> dict:
    from services.google_workspace import format_file_list, list_google_workspace_files
    token, err = await _google_workspace_token(user_id, sheets=False)
    if not token:
        return {"summary": err, "ui": {"kind": "docs", "connected": False}}
    try:
        files = await asyncio.to_thread(list_google_workspace_files, token)
    except RuntimeError as exc:
        return {"summary": str(exc), "ui": {"kind": "docs", "error": str(exc)}}
    return {
        "summary": format_file_list(files),
        "ui": {"kind": "docs", "files": files},
    }


async def exec_research_seo(user_id: str, args: dict) -> dict:
    from services.seo_campaign import assemble_campaign, format_campaign
    topic = (args.get("topic") or "").strip()
    if not topic:
        return {"summary": "Need a topic — what the business does.", "ui": {"kind": "seo", "error": "missing_topic"}}
    location = (args.get("location") or "").strip()
    audience = (args.get("audience") or "").strip()
    query = topic if not location else f"{topic} {location}"
    results: list[dict] = []
    try:
        results = await asyncio.to_thread(_sync_ddg_search, f"{query} marketing", 6)
    except Exception:  # noqa: BLE001
        results = []
    plan = assemble_campaign(topic, location=location, audience=audience, results=results)
    return {
        "summary": format_campaign(plan),
        "ui": {"kind": "seo", "plan": plan},
    }


async def exec_post_to_social(user_id: str, args: dict) -> dict:
    from routers.oauth import get_fresh_linkedin_token, get_fresh_twitter_token
    from services.social_post import (
        SOCIAL_CONNECT,
        clip_post,
        normalize_network,
        post_linkedin,
        post_preview,
        post_tweet,
    )
    network = normalize_network(str(args.get("network") or ""))
    if not network:
        return {
            "summary": "Say whether this is for X (twitter) or LinkedIn.",
            "ui": {"kind": "social", "error": "bad_network"},
        }
    text, warn = clip_post(str(args.get("text") or ""), network)
    if not text:
        return {"summary": warn or "Need some words to post.", "ui": {"kind": "social", "error": "missing_text"}}
    draft = text if not warn else f"{text}\n({warn})"
    if not bool(args.get("confirmed")):
        return {
            "summary": post_preview(network, draft),
            "ui": {"kind": "social", "needs_confirm": True, "network": network, "text": text},
        }
    if network == "twitter":
        token = await get_fresh_twitter_token(user_id)
        if not token:
            return {"summary": SOCIAL_CONNECT, "ui": {"kind": "social", "connected": False, "network": "twitter"}}
        try:
            posted = await asyncio.to_thread(post_tweet, token, text)
        except RuntimeError as exc:
            return {"summary": str(exc), "ui": {"kind": "social", "error": str(exc)}}
        return {
            "summary": "Posted on X." + (f" Id {posted['id']}." if posted.get("id") else ""),
            "ui": {"kind": "social", "posted": True, "network": "twitter", "id": posted.get("id")},
        }
    bundle = await get_fresh_linkedin_token(user_id)
    if not bundle:
        return {"summary": SOCIAL_CONNECT, "ui": {"kind": "social", "connected": False, "network": "linkedin"}}
    token, profile = bundle
    urn = (profile or {}).get("urn") or (profile or {}).get("id") or ""
    if not urn:
        return {"summary": SOCIAL_CONNECT, "ui": {"kind": "social", "connected": False, "network": "linkedin"}}
    try:
        posted = await asyncio.to_thread(post_linkedin, token, str(urn), text)
    except RuntimeError as exc:
        return {"summary": str(exc), "ui": {"kind": "social", "error": str(exc)}}
    return {
        "summary": "Posted on LinkedIn.",
        "ui": {"kind": "social", "posted": True, "network": "linkedin", "id": posted.get("id")},
    }


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
        "description": (
            "Look at the owner's computer screen (screenshot on the home PC, then deleted) and coach them. "
            "Use whenever they ask you to look at the screen, help with a video game, check grammar or writing "
            "that's on screen, identify a movie or show, read an error, or say 'look at this'. "
            "Pass a question that says what kind of help they want."
        ),
        "parameters": {"type": "object", "properties": {
            "question": {
                "type": "string",
                "description": "What to look for — e.g. game advice, grammar edits, what movie this is, read this error",
            },
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
        },         "required": ["query"]},
    }},
]


EMAIL_TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "read_inbox",
        "description": (
            "Read the owner's recent inbox (who it's from, subject, a short snippet). "
            "Use when they ask what's in their email. Never dump full bodies."
        ),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Optional Gmail-style search (from:, subject:, a phrase)"},
        }},
    }},
    {"type": "function", "function": {
        "name": "search_mail",
        "description": "Search the owner's inbox for a phrase, sender, or subject.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "What to look for"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "find_setup_mail",
        "description": (
            "Find recent setup / verification / magic-link mail (Pinokio, Ollama, Heirloom, confirm your email). "
            "Show the links so they can tap them. Do not create accounts for them."
        ),
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "send_email",
        "description": (
            "Send email from the owner's connected inbox. First call WITHOUT confirmed so they see a draft. "
            "Only after they clearly say yes, call again with confirmed=true."
        ),
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string"},
            "body": {"type": "string", "description": "Plain-text body"},
            "confirmed": {"type": "boolean", "default": False, "description": "Set true ONLY after the owner explicitly confirms the draft"},
        }, "required": ["to", "subject", "body"]},
    }},
    {"type": "function", "function": {
        "name": "find_follow_ups",
        "description": (
            "Find recent inbox mail that looks like it is waiting on the owner (questions, RSVPs, please confirm). "
            "Skip newsletters. Offer to draft a reply with send_email."
        ),
        "parameters": {"type": "object", "properties": {}},
    }},
]


CALENDAR_TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "list_events",
        "description": "List upcoming calendar events (same Gmail/Outlook connection). Default is today.",
        "parameters": {"type": "object", "properties": {
            "days": {"type": "integer", "description": "How many days ahead (1-14)", "default": 1},
        }},
    }},
    {"type": "function", "function": {
        "name": "create_event",
        "description": (
            "Add an event to the owner's calendar. First call WITHOUT confirmed so they see a draft. "
            "Only after they clearly say yes, call again with confirmed=true."
        ),
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "when": {"type": "string", "description": "ISO datetime or natural language like 'tomorrow 3pm'"},
            "duration_minutes": {"type": "integer", "default": 60},
            "where": {"type": "string"},
            "notes": {"type": "string"},
            "confirmed": {"type": "boolean", "default": False},
        }, "required": ["title", "when"]},
    }},
]


PEOPLE_TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "find_contact",
        "description": "Look up a person in the owner's Heirloom address book (name, phone). Not their phone SIM.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
        }, "required": ["name"]},
    }},
    {"type": "function", "function": {
        "name": "call_contact",
        "description": (
            "Place a phone call to someone in the address book, in the twin's voice. "
            "First call WITHOUT confirmed. Only after they clearly say yes, call again with confirmed=true."
        ),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"},
            "opening_line": {"type": "string", "description": "Optional first sentence the twin says"},
            "confirmed": {"type": "boolean", "default": False},
        },         "required": ["name"]},
    }},
]


BUSINESS_TOOL_SCHEMAS: list[dict] = [
    {"type": "function", "function": {
        "name": "write_google_doc",
        "description": (
            "Create a Google Doc (business plan, letter, campaign). First call WITHOUT confirmed so they see a draft. "
            "Write the full text in body. After they clearly say yes, call again with confirmed=true."
        ),
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "body": {"type": "string", "description": "Full document text"},
            "kind": {
                "type": "string",
                "enum": ["business_plan", "letter", "notes", "campaign"],
                "description": "If business_plan and body is empty, a simple outline is used",
            },
            "offering": {"type": "string", "description": "What they sell — used for a plan outline"},
            "audience": {"type": "string", "description": "Who it's for — used for a plan outline"},
            "confirmed": {"type": "boolean", "default": False},
        }, "required": ["title"]},
    }},
    {"type": "function", "function": {
        "name": "write_google_sheet",
        "description": (
            "Create a Google spreadsheet (budget, keyword list, posting calendar). "
            "First call WITHOUT confirmed. After they say yes, call again with confirmed=true."
        ),
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "headers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Column names",
            },
            "rows": {
                "type": "array",
                "description": "Rows as arrays of strings, or CSV lines",
            },
            "confirmed": {"type": "boolean", "default": False},
        }, "required": ["title"]},
    }},
    {"type": "function", "function": {
        "name": "list_workspace_files",
        "description": "List Google Docs and Sheets Heirloom already created for this owner.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "research_seo",
        "description": (
            "Draft an SEO and posting starter plan from public web pages. "
            "Do not invent ranking numbers. Offer to put it in a Doc or Sheet after they say yes."
        ),
        "parameters": {"type": "object", "properties": {
            "topic": {"type": "string", "description": "What the business does"},
            "location": {"type": "string", "description": "Town or region, optional"},
            "audience": {"type": "string", "description": "Who they want to reach, optional"},
        }, "required": ["topic"]},
    }},
    {"type": "function", "function": {
        "name": "post_to_social",
        "description": (
            "Post as the owner on X (twitter) or LinkedIn. First call WITHOUT confirmed so they see a draft. "
            "After they clearly say yes, call again with confirmed=true. Never ask for a password."
        ),
        "parameters": {"type": "object", "properties": {
            "network": {"type": "string", "enum": ["twitter", "linkedin", "x"]},
            "text": {"type": "string"},
            "confirmed": {"type": "boolean", "default": False},
        }, "required": ["network", "text"]},
    }},
]


TOOL_SCHEMAS += COMPUTER_TOOL_SCHEMAS
TOOL_SCHEMAS += EMAIL_TOOL_SCHEMAS
TOOL_SCHEMAS += CALENDAR_TOOL_SCHEMAS
TOOL_SCHEMAS += PEOPLE_TOOL_SCHEMAS
TOOL_SCHEMAS += BUSINESS_TOOL_SCHEMAS


TOOL_EXECUTORS: dict[str, Callable[[str, dict], Coroutine[Any, Any, dict]]] = {
    "search_archive": exec_search_archive,
    "save_memory": exec_save_memory,
    "set_reminder": exec_set_reminder,
    "list_recent_memories": exec_list_recent_memories,
    "list_reminders": exec_list_reminders,
    "complete_reminder": exec_complete_reminder,
    "whats_on_my_plate": exec_whats_on_my_plate,
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
    "read_inbox": exec_read_inbox,
    "search_mail": exec_search_mail,
    "find_setup_mail": exec_find_setup_mail,
    "send_email": exec_send_email,
    "find_follow_ups": exec_find_follow_ups,
    "list_events": exec_list_events,
    "create_event": exec_create_event,
    "find_contact": exec_find_contact,
    "call_contact": exec_call_contact,
    "write_google_doc": exec_write_google_doc,
    "write_google_sheet": exec_write_google_sheet,
    "list_workspace_files": exec_list_workspace_files,
    "research_seo": exec_research_seo,
    "post_to_social": exec_post_to_social,
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
