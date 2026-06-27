"""Music control — the twin can play songs/videos through the user's preferred service.

Flow when the user says "play Pink Floyd":
1. Intent detector matches a "play <query>" pattern (capture & twin both call this).
2. We resolve the deep-link for the user's preferred provider
   (YouTube Music, Spotify, YouTube, Apple Music, Amazon Music…).
3. If the user has an active companion device, we queue an `open_url` command
   so the song/video opens on their actual PC. The twin then replies
   conversationally ("Putting on Pink Floyd for you.").
4. If no companion is online, we still return the URL — the web UI can open it.

The user picks their default provider in Settings; per-call override possible.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import db, get_current_user

router = APIRouter(prefix="/music", tags=["music"])


# ------------- Provider catalogue -------------
# Each provider exposes a `search_url` template that takes the query string.
# We deep-link to a search page — the actual song begins playing in one click,
# which is plenty for v1. (True API-level "play" would require OAuth into each
# service, which is a separate, bigger feature.)
PROVIDERS = {
    "youtube_music": {
        "name": "YouTube Music",
        "search_url": "https://music.youtube.com/search?q={q}",
    },
    "youtube": {
        "name": "YouTube",
        "search_url": "https://www.youtube.com/results?search_query={q}",
    },
    "spotify": {
        "name": "Spotify",
        "search_url": "https://open.spotify.com/search/{q}",
    },
    "apple_music": {
        "name": "Apple Music",
        "search_url": "https://music.apple.com/us/search?term={q}",
    },
    "amazon_music": {
        "name": "Amazon Music",
        "search_url": "https://music.amazon.com/search/{q}",
    },
    "soundcloud": {
        "name": "SoundCloud",
        "search_url": "https://soundcloud.com/search?q={q}",
    },
}

DEFAULT_PROVIDER = "youtube_music"


def resolve_provider(provider_id: Optional[str]) -> tuple[str, dict]:
    pid = (provider_id or DEFAULT_PROVIDER).strip().lower()
    if pid not in PROVIDERS:
        pid = DEFAULT_PROVIDER
    return pid, PROVIDERS[pid]


def build_url(provider_id: str, query: str) -> str:
    _, prov = resolve_provider(provider_id)
    return prov["search_url"].format(q=quote(query.strip()))


# ------------- Intent detection (used by twin + capture) -------------
# Compiled once. Captures the part after the trigger as the search query.
_INTENT_PATTERNS = [
    re.compile(r"^\s*(?:hey )?(?:twin[, ]+)?play\s+(?:me\s+)?(?:some\s+)?(?:the\s+)?(?:song\s+|track\s+|music\s+video\s+(?:of\s+|for\s+)?)?([\s\S]+?)\s*[.?!]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:hey )?(?:twin[, ]+)?put\s+on\s+([\s\S]+?)\s*[.?!]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:hey )?(?:twin[, ]+)?queue\s+(?:up\s+)?([\s\S]+?)\s*[.?!]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:hey )?(?:twin[, ]+)?start\s+(?:playing\s+)?([\s\S]+?)\s*[.?!]?\s*$", re.IGNORECASE),
]

_NON_MUSIC_QUERY_BLOCKERS = re.compile(
    r"\b(reminder|reminders|the news|video games?|videogames?|movie|netflix|youtube video|hbo|disney)\b",
    re.IGNORECASE,
)


def detect_music_intent(text: str) -> Optional[str]:
    """Returns the music query if the user said 'play <X>', else None.

    Conservative — only fires when the text starts with a play verb so casual
    references like "I used to play guitar" don't match.
    """
    if not text:
        return None
    s = text.strip()
    if not s:
        return None
    if _NON_MUSIC_QUERY_BLOCKERS.search(s):
        return None
    for pat in _INTENT_PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        q = (m.group(1) or "").strip(" \"'.,!?")
        if not q or len(q) > 200 or len(q) < 2:
            return None
        # Filter out clearly non-music tails ("video games", "the news", "a movie")
        if _NON_MUSIC_QUERY_BLOCKERS.search(q):
            return None
        return q
    return None


# ------------- Command queueing on the user's companion -------------
async def _active_device(user_id: str) -> Optional[dict]:
    """Pick the most-recently-seen, non-revoked companion device."""
    cursor = db.companion_devices.find(
        {"user_id": user_id, "revoked": False}, {"_id": 0}
    ).sort("last_seen", -1).limit(1)
    devs = await cursor.to_list(length=1)
    return devs[0] if devs else None


async def queue_open_url(user_id: str, device_id: str, url: str) -> str:
    cmd_id = f"cmd_{uuid.uuid4().hex[:12]}"
    await db.companion_commands.insert_one({
        "cmd_id": cmd_id,
        "user_id": user_id,
        "device_id": device_id,
        "kind": "open_url",
        "payload": {"url": url},
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
    })
    return cmd_id


async def play_for_user(user_id: str, query: str, provider_id: Optional[str] = None) -> dict:
    """Resolve URL + queue on companion (if any). Returns details for the twin
    to compose its conversational reply."""
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    pref = (user or {}).get("music_provider") or DEFAULT_PROVIDER
    pid, prov = resolve_provider(provider_id or pref)
    url = build_url(pid, query)

    device = await _active_device(user_id)
    queued_cmd = None
    if device:
        queued_cmd = await queue_open_url(user_id, device["device_id"], url)

    return {
        "query": query,
        "provider": pid,
        "provider_name": prov["name"],
        "url": url,
        "device_id": device["device_id"] if device else None,
        "cmd_id": queued_cmd,
        "queued": queued_cmd is not None,
    }


# ------------- HTTP endpoints -------------
class PlayReq(BaseModel):
    query: str = Field(..., min_length=1, max_length=200)
    provider: Optional[str] = None


@router.get("/providers")
async def list_providers():
    return {
        "providers": [
            {"id": k, "name": v["name"]} for k, v in PROVIDERS.items()
        ],
        "default": DEFAULT_PROVIDER,
    }


@router.post("/play")
async def play(payload: PlayReq, user: dict = Depends(get_current_user)):
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query is empty")
    result = await play_for_user(user["user_id"], payload.query.strip(), payload.provider)
    return result


@router.get("/me")
async def my_pref(user: dict = Depends(get_current_user)):
    return {
        "music_provider": user.get("music_provider") or DEFAULT_PROVIDER,
    }
