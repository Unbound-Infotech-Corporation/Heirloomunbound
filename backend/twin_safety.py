"""Shared gate for every path that generates a twin reply.

Crisis handling finishes before any language model, including cloud models.
Grief nudges and memorial wording are prompt-only plus a short aside.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from crisis_protocol import (
    CrisisHit,
    build_safety_event,
    crisis_reply,
    resolve_crisis,
    within_dedupe_window,
)
from grief_guard import (
    GriefSignal,
    detect_grief,
    grief_prompt_block,
    session_minutes,
    user_turn_count,
    with_grief_aside,
)
from memorial_mode import memorial_from_user

HEIR_AUDIENCES = frozenset({"heir", "caller"})


def surface_for_source(source: str, *, room: bool = False) -> str:
    if room:
        return "vr"
    key = (source or "").strip().lower()
    if key in {"vr", "room", "rooms"}:
        return "vr"
    if key == "phone":
        return "phone"
    if key in {"companion", "desktop_local", "voice"}:
        return "voice"
    if key in {"heir", "heir_portal"}:
        return "heir_portal"
    if key.startswith("desktop"):
        return "desktop"
    if key in {"winui"}:
        return "winui"
    return "twin"


@dataclass
class CrisisIntercept:
    reply: str
    ts: str
    event: dict[str, Any]


def grief_for_turn(
    text: str,
    *,
    audience: str,
    messages: list[dict] | None = None,
    sessions_today: int = 0,
    settings: Any = None,
    now: Optional[datetime] = None,
) -> Optional[GriefSignal]:
    if (audience or "").strip().lower() not in HEIR_AUDIENCES:
        return None
    memorial = settings
    if isinstance(settings, dict) and "mode" not in settings:
        memorial = memorial_from_user(settings)
    return detect_grief(
        text,
        user_turns=user_turn_count(messages),
        sessions_today=sessions_today,
        session_minutes=session_minutes(messages, now),
        settings=memorial,
    )


def grief_system_block(signal: Optional[GriefSignal]) -> str:
    return grief_prompt_block(signal)


async def sessions_today_count(user_id: str, *, kind: str, now: Optional[datetime] = None) -> int:
    """Best-effort. A missing database counts as zero so phrase detection still works."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    start = current.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        from deps import db

        return int(
            await db.conversations.count_documents(
                {
                    "user_id": user_id,
                    "kind": kind,
                    "updated_at": {"$gte": start.isoformat()},
                }
            )
        )
    except Exception:
        return 0


async def record_crisis_event(
    user: dict,
    hit: CrisisHit,
    *,
    surface: str,
    audience: str,
    heir: dict | None = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Insert one owner-visible flag. A repeat inside two minutes returns the existing row."""
    from deps import db

    stamp = now or datetime.now(timezone.utc)
    memorial = memorial_from_user(user)
    heir_id = str((heir or {}).get("heir_id") or "")
    heir_name = str((heir or {}).get("name") or "")
    try:
        cursor = (
            db.safety_events.find(
                {
                    "user_id": user.get("user_id"),
                    "kind": "crisis",
                    "category": hit.category,
                    "surface": surface,
                },
                {"_id": 0},
            )
            .sort("created_at", -1)
            .limit(1)
        )
        rows = await cursor.to_list(length=1)
        existing = rows[0] if rows else None
    except Exception:
        existing = None
    if existing and within_dedupe_window(existing.get("created_at"), stamp):
        return existing
    doc = build_safety_event(
        user_id=str(user.get("user_id") or ""),
        hit=hit,
        surface=surface,
        audience=audience,
        now=stamp,
        heir_id=heir_id,
        heir_name=heir_name,
        contact_name=str(memorial.get("contact_name") or ""),
        contact_email=str(memorial.get("contact_email") or ""),
        event_id=f"safe_{uuid.uuid4().hex[:12]}",
    )
    try:
        await db.safety_events.insert_one(dict(doc))
    except Exception:
        return doc
    return doc


async def intercept_crisis(
    text: str,
    *,
    user: dict,
    surface: str,
    audience: str,
    conversation: dict | None = None,
    persist: bool = False,
    source: str = "",
    heir: dict | None = None,
    local_check=None,
    allow_local: bool = True,
) -> Optional[CrisisIntercept]:
    """If this message is a crisis, log it and do not call a model."""
    hit = await resolve_crisis(text, local_check=local_check, allow_local=allow_local)
    if hit is None:
        return None
    event = await record_crisis_event(
        user,
        hit,
        surface=surface,
        audience=audience,
        heir=heir,
    )
    stamp = datetime.now(timezone.utc).isoformat()
    reply = crisis_reply()
    if persist and conversation and conversation.get("conversation_id") and user.get("user_id"):
        from twin_runtime import _persist_pair

        await _persist_pair(
            user["user_id"],
            conversation["conversation_id"],
            (text or "").strip(),
            reply,
            stamp,
            source=source or surface,
        )
    return CrisisIntercept(reply=reply, ts=stamp, event=event)
