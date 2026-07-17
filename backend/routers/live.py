"""Live-stream twin — public broadcast at /twin/live/<handle>.

This router is unusual: half of it is owner-side (set handle, enable/disable
broadcast, etc., all session-authed) and half is **public** (no auth, just a
handle in the URL — anyone can watch).

Streaming primitive: a process-local asyncio pub/sub. Each owner has a queue
keyed by user_id; new chat turns + avatar URLs get pushed there from the
hooks in routers/desktop.py and routers/twin.py. Public viewers subscribe via
Server-Sent Events.

Why SSE (not WebSocket)?
- One-way push is all we need (server → viewer, never the reverse)
- Native browser support via EventSource — no library
- Plays nice with HTTP/1.1 and CDN proxies
- Plain text protocol, dead simple to debug

For multi-worker deployments later we'd swap the in-memory bus for Redis.
Single FastAPI worker on Emergent today — in-memory is correct.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from deps import db, get_current_user

router = APIRouter(prefix="/live", tags=["live"])

# ---------- Reserved handles + validator ----------
_RESERVED = {
    "admin", "administrator", "api", "app", "apps", "auth", "billing",
    "buy", "checkout", "companion", "dashboard", "desktop", "docs", "email",
    "help", "heirloom", "home", "login", "logout", "mail", "me",
    "memory", "memories", "noreply", "policy", "privacy", "profile",
    "refund", "refunds", "root", "settings", "signin", "signup", "static",
    "status", "support", "system", "terms", "test", "tests", "twin",
    "user", "users", "vault", "voice", "www", "live", "stream", "obs",
}
_HANDLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{1,28}[a-z0-9])?$")


def _validate_handle(raw: str) -> str:
    h = (raw or "").strip().lower()
    if not _HANDLE_RE.match(h):
        raise HTTPException(
            status_code=400,
            detail="Handle must be 3–30 chars, a-z 0-9 _ - only, can't start or end with dash/underscore.",
        )
    if h in _RESERVED:
        raise HTTPException(status_code=400, detail="That handle is reserved — pick another.")
    return h


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Pub/sub bus ----------
class _Bus:
    """Process-local fan-out. Each owner has 0..N subscriber queues."""

    def __init__(self):
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, user_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subs.setdefault(user_id, set()).add(q)
        return q

    def unsubscribe(self, user_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(user_id)
        if not subs:
            return
        subs.discard(q)
        if not subs:
            self._subs.pop(user_id, None)

    def subscriber_count(self, user_id: str) -> int:
        return len(self._subs.get(user_id, ()))

    async def publish(self, user_id: str, event: dict) -> None:
        subs = self._subs.get(user_id)
        if not subs:
            return
        # Best-effort; drop on slow subscribers rather than back-pressuring the
        # chat pipeline. Each subscriber's reader will time-out + reconnect.
        for q in list(subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


BUS = _Bus()


async def publish_turn(user_id: str, role: str, text: str, *, source: str = "web") -> None:
    """Called from chat handlers when a new turn is created."""
    if not text:
        return
    # Respect the owner's broadcast settings — silently drop if disabled
    profile = await db.live_profiles.find_one(
        {"user_id": user_id}, {"_id": 0, "enabled": 1, "private_mode": 1}
    )
    if not profile or not profile.get("enabled") or profile.get("private_mode"):
        return
    await BUS.publish(
        user_id,
        {
            "type": "turn",
            "role": role,
            "content": text[:2000],
            "ts": _now_iso(),
            "source": source,
        },
    )


async def publish_avatar(user_id: str, video_url: str) -> None:
    """Called when D-ID finishes rendering a talking-head — viewers swap to video."""
    profile = await db.live_profiles.find_one(
        {"user_id": user_id}, {"_id": 0, "enabled": 1, "private_mode": 1}
    )
    if not profile or not profile.get("enabled") or profile.get("private_mode"):
        return
    await BUS.publish(user_id, {"type": "avatar", "video_url": video_url, "ts": _now_iso()})


# ---------- Owner endpoints ----------
class HandleReq(BaseModel):
    handle: str = Field(..., min_length=3, max_length=30)


@router.get("/me")
async def live_me(user: dict = Depends(get_current_user)):
    """Get the owner's broadcast profile (or `{enabled: false}` if not set up)."""
    from routers.avatar import DEFAULT_SOURCE_URL

    profile = await db.live_profiles.find_one(
        {"user_id": user["user_id"]},
        {"_id": 0, "handle": 1, "enabled": 1, "private_mode": 1, "created_at": 1, "updated_at": 1},
    )
    out = profile or {"handle": None, "enabled": False, "private_mode": False}
    src = (user.get("avatar_source_url") or "").strip()
    out["avatar_source_url"] = src
    out["has_custom_face"] = bool(src) and src != DEFAULT_SOURCE_URL
    out["using_default_face"] = not out["has_custom_face"]
    return out


@router.post("/handle")
async def claim_handle(body: HandleReq, user: dict = Depends(get_current_user)):
    """Claim or change handle. Idempotent for the owner; 409s if a different
    user already has it."""
    h = _validate_handle(body.handle)
    existing = await db.live_profiles.find_one({"handle": h}, {"_id": 0, "user_id": 1})
    if existing and existing.get("user_id") != user["user_id"]:
        raise HTTPException(status_code=409, detail="Handle already taken.")

    now = _now_iso()
    await db.live_profiles.update_one(
        {"user_id": user["user_id"]},
        {
            "$set": {"handle": h, "updated_at": now},
            "$setOnInsert": {
                "user_id": user["user_id"],
                "enabled": False,
                "private_mode": False,
                "created_at": now,
            },
        },
        upsert=True,
    )
    return {"handle": h, "url": f"/twin/live/{h}"}


class SettingsReq(BaseModel):
    enabled: Optional[bool] = None
    private_mode: Optional[bool] = None


@router.patch("/settings")
async def update_settings(body: SettingsReq, user: dict = Depends(get_current_user)):
    """Flip broadcast on/off or enter/exit private mode for the current session."""
    from routers.avatar import DEFAULT_SOURCE_URL

    profile = await db.live_profiles.find_one({"user_id": user["user_id"]}, {"_id": 0, "handle": 1})
    if not profile or not profile.get("handle"):
        raise HTTPException(status_code=400, detail="Claim a handle first.")
    # Warn loudly if they try to go live on the default Emma face
    if body.enabled is True:
        src = (user.get("avatar_source_url") or "").strip()
        if not src or src == DEFAULT_SOURCE_URL:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Upload your face first — open Avatar Studio, drop a front photo, "
                    "and we'll set it as your twin automatically."
                ),
            )
    update: dict = {"updated_at": _now_iso()}
    if body.enabled is not None:
        update["enabled"] = bool(body.enabled)
    if body.private_mode is not None:
        update["private_mode"] = bool(body.private_mode)
    if len(update) == 1:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    await db.live_profiles.update_one({"user_id": user["user_id"]}, {"$set": update})
    return await live_me(user)


# ---------- PUBLIC endpoints (no auth) ----------
async def _resolve_handle(handle: str) -> dict:
    h = handle.strip().lower()
    profile = await db.live_profiles.find_one({"handle": h}, {"_id": 0})
    if not profile:
        raise HTTPException(status_code=404, detail="No twin at that handle.")
    if not profile.get("enabled"):
        raise HTTPException(status_code=404, detail="This twin isn't broadcasting right now.")
    return profile


@router.get("/{handle}/profile")
async def public_profile(handle: str):
    """Owner display info viewers need to render the page header. No auth."""
    profile = await _resolve_handle(handle)
    user = await db.users.find_one(
        {"user_id": profile["user_id"]},
        {"_id": 0, "name": 1, "avatar_source_url": 1, "picture": 1, "tagline": 1},
    )
    if not user:
        raise HTTPException(status_code=404, detail="Profile orphaned.")
    return {
        "handle": profile["handle"],
        "name": user.get("name") or "Heirloom Twin",
        "tagline": user.get("tagline") or "",
        "avatar_url": user.get("avatar_source_url") or user.get("picture") or "",
        "private_mode": profile.get("private_mode", False),
        "viewer_count": BUS.subscriber_count(profile["user_id"]),
    }


@router.get("/{handle}/recent")
async def public_recent(handle: str, limit: int = 10):
    """Initial-load history — last N turns of the public conversation. Public.

    Pulls from both desktop (`companion_twin`) and web (`twin`) conversations
    so the live page matches whichever surface the owner is chatting on.
    Episodic summaries + private archive entries are NEVER exposed.
    """
    profile = await _resolve_handle(handle)
    limit = max(1, min(limit, 50))
    cursor = (
        db.conversations.find(
            {
                "user_id": profile["user_id"],
                "kind": {"$in": ["companion_twin", "twin"]},
            },
            {"_id": 0, "messages": 1, "updated_at": 1, "kind": 1},
        )
        .sort("updated_at", -1)
        .limit(2)
    )
    convs = await cursor.to_list(length=2)
    msgs: list[dict] = []
    for conv in convs:
        for m in conv.get("messages") or []:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                msgs.append(m)
    # Prefer chronological by ts when present
    msgs.sort(key=lambda m: m.get("ts") or "")
    if len(msgs) > limit:
        msgs = msgs[-limit:]
    return {
        "messages": [
            {"role": m.get("role"), "content": (m.get("content") or "")[:2000], "ts": m.get("ts")}
            for m in msgs
        ]
    }


@router.get("/{handle}/stream")
async def public_stream(handle: str, request: Request):
    """Server-Sent Events feed — every new turn + avatar render flows here."""
    profile = await _resolve_handle(handle)
    user_id = profile["user_id"]

    async def _gen() -> AsyncIterator[bytes]:
        q = BUS.subscribe(user_id)
        try:
            # Initial "hello" so the connection is alive immediately
            yield b": connected\n\n"
            yield f"event: hello\ndata: {json.dumps({'handle': handle, 'ts': _now_iso()})}\n\n".encode()
            heartbeat = 0
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=20.0)
                    payload = json.dumps(event)
                    yield f"event: {event.get('type','turn')}\ndata: {payload}\n\n".encode()
                except asyncio.TimeoutError:
                    # Heartbeat keeps proxies + Cloudflare from dropping idle conns
                    heartbeat += 1
                    yield f": heartbeat {heartbeat}\n\n".encode()
        finally:
            BUS.unsubscribe(user_id, q)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disables nginx response buffering
            "Connection": "keep-alive",
        },
    )
