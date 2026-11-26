"""Notes and reminder lookups for the local assistant.

Notes are the owner's scratch pad ("note that the plumber is coming Tuesday").
They are not memory cards: a note never grounds a life answer and never reaches
an heir. They live in ``owner_notes`` and only owner turns can read or write
them.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

MAX_NOTE_CHARS = 4000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    from deps import db

    return db


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9']+", (text or "").lower()) if len(t) > 2]


def score_note(note: dict, query: str) -> int:
    words = _tokens(query)
    if not words:
        return 1
    hay = (str(note.get("title") or "") + " " + str(note.get("text") or "")).lower()
    return sum(1 for w in words if w in hay)


def note_title(text: str) -> str:
    first = " ".join((text or "").split())[:60]
    return first.rstrip(" ,.;:") or "Note"


async def exec_save_note(user_id: str, args: dict, *, store: Any = None) -> dict:
    text = " ".join(str(args.get("text") or args.get("content") or "").split())
    if not text:
        return {"summary": "No note text given.", "ui": {"saved": False}}
    text = text[:MAX_NOTE_CHARS]
    doc = {
        "note_id": f"note_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "title": str(args.get("title") or "").strip()[:80] or note_title(text),
        "text": text,
        "created_at": _now_iso(),
    }
    db = store or _db()
    await db.owner_notes.insert_one(dict(doc))
    return {"summary": f"Saved a note: {doc['title']}", "ui": {"saved": True, "note_id": doc["note_id"], "title": doc["title"]}}


async def exec_search_notes(user_id: str, args: dict, *, store: Any = None) -> dict:
    query = str(args.get("query") or "").strip()
    limit = min(10, max(1, int(args.get("limit") or 5)))
    db = store or _db()
    rows = await db.owner_notes.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).to_list(300)
    scored = [(score_note(r, query), r) for r in rows]
    hits = [r for s, r in sorted(scored, key=lambda p: -p[0]) if s > 0][:limit]
    if not hits:
        return {"summary": f"No notes match '{query}'." if query else "No notes yet.", "ui": {"count": 0}}
    lines = [f"{len(hits)} note(s):"]
    for r in hits:
        lines.append(f"- {r.get('created_at', '')[:10]} {r.get('title')}: {str(r.get('text') or '')[:300]}")
    return {"summary": "\n".join(lines), "ui": {"count": len(hits)}}


async def exec_list_reminders(user_id: str, args: dict, *, store: Any = None) -> dict:
    db = store or _db()
    rows = await db.reminders.find(
        {"user_id": user_id, "status": {"$in": ["open", "snoozed"]}}, {"_id": 0}
    ).sort("due_at", 1).to_list(50)
    if not rows:
        return {"summary": "No open reminders.", "ui": {"count": 0}}
    lines = [f"{len(rows)} open reminder(s):"]
    for r in rows[:15]:
        lines.append(f"- {r.get('text')} (due {r.get('due_at') or 'no time set'})")
    return {"summary": "\n".join(lines), "ui": {"count": len(rows)}}
