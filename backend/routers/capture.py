"""Quick-capture: the always-visible smart input that routes a thought into the right place."""
import json
import re as _re
import uuid
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db, get_current_user
from utils import escape_regex, rate_limit

router = APIRouter(prefix="/capture", tags=["capture"])


CAPTURE_SYSTEM_TEMPLATE = """You are the Live Assistant inside Heirloom — a private "second brain" attached to a personality archive that someone is building over years.

The current date and time (UTC) is: {now}. When parsing relative dates ("Saturday", "tomorrow", "in 2 hours"), always anchor to this exact moment.

Each user message is a single quick thought captured in a hurry. Decide what to do with it. Output a SINGLE valid JSON object — no prose, no code fences — with this exact shape:

{{
  "kind": "reminder" | "memory" | "value" | "advice" | "quote" | "note" | "question",
  "text": "<cleaned, first-person text>",
  "title": "<short evocative title, max 90 chars>",
  "tags": ["short","tags"],
  "due_at": "<ISO8601 UTC if a date/time was mentioned, else null>",
  "answer_hint": "<if kind=question, restate the question concisely, else null>"
}}

Rules:
- "reminder" = a future task, todo, errand, or scheduled obligation. Extract a date/time if present. Use the current date above as the anchor for relative phrases. Otherwise due_at = null.
- "memory" = a recollection of something that happened. "value" = a belief or principle. "advice" = guidance for descendants. "quote" = a saying. "note" = an idea/observation without a clear category.
- "question" = the user is asking the archive about something they captured before. Set answer_hint.
- DO NOT include any other keys. DO NOT explain. Output ONLY the JSON.
"""


class CaptureReq(BaseModel):
    text: str


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    return s.strip()


async def _classify(text: str) -> dict:
    if not EMERGENT_LLM_KEY:
        return {"kind": "note", "text": text, "title": text[:80], "tags": [], "due_at": None}
    now_iso = datetime.now(timezone.utc).isoformat()
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"capture_{uuid.uuid4().hex[:8]}",
        system_message=CAPTURE_SYSTEM_TEMPLATE.format(now=now_iso),
    ).with_model("anthropic", "claude-sonnet-4-6")
    try:
        raw = await chat.send_message(UserMessage(text=text))
        raw = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
        data = json.loads(_strip_fences(raw))
        if not isinstance(data, dict):
            raise ValueError("non-object")
        return data
    except Exception:  # noqa: BLE001
        return {"kind": "note", "text": text, "title": text[:80], "tags": [], "due_at": None}


async def _search_archive(user_id: str, query: str, limit: int = 8) -> list[dict]:
    """Tokenized OR-match — splits on whitespace, escapes each token, drops short stopwords."""
    if not query.strip():
        return []
    STOP = {"the","a","an","of","in","on","to","for","was","is","are","what","where","when","who","why","how","my","me","i","did","do","does","that","this","at","with","and"}
    tokens = [
        _re.escape(t) for t in _re.split(r"\W+", query.lower())
        if len(t) > 2 and t not in STOP
    ]
    if not tokens:
        tokens = [_re.escape(query.strip()[:80])]
    or_clauses = []
    for t in tokens[:8]:
        or_clauses.extend([
            {"title": {"$regex": t, "$options": "i"}},
            {"content": {"$regex": t, "$options": "i"}},
            {"tags": {"$regex": t, "$options": "i"}},
        ])
    cursor = db.entries.find({"user_id": user_id, "$or": or_clauses}, {"_id": 0}).limit(limit)
    return await cursor.to_list(length=limit)


async def _answer_question(user: dict, question: str, related: list[dict]) -> str:
    if not EMERGENT_LLM_KEY:
        return "(no LLM configured)"
    context = "\n".join(f"- [{e['type']}] {e['title']}: {e['content'][:400]}" for e in related)
    sys = f"""You are a careful, warm assistant helping {user.get('name','this person')} recall things from their personal archive. Use ONLY the entries provided below — do not invent facts. If the answer isn't in the entries, say so plainly. Keep the answer 1-3 sentences. Cite entry titles in [brackets]. If multiple entries are relevant, mention each briefly.

Entries (most relevant first):
{context or '(no entries match)'}
"""
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"recall_{uuid.uuid4().hex[:8]}",
        system_message=sys,
    ).with_model("anthropic", "claude-sonnet-4-6")
    reply = await chat.send_message(UserMessage(text=question))
    return reply if isinstance(reply, str) else getattr(reply, "content", str(reply))


@router.post("")
async def capture(payload: CaptureReq, user: dict = Depends(get_current_user)):
    from routers.executor_lock import assert_writable
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty capture")
    if len(text) > 4000:
        raise HTTPException(status_code=400, detail="Capture too long (4000 char max)")
    await rate_limit(user["user_id"], "capture", max_calls=30, per_seconds=60)

    classification = await _classify(text)
    kind = classification.get("kind", "note")
    # Questions against the archive are always allowed (read-only).
    if kind != "question":
        await assert_writable(user["user_id"])
    title = (classification.get("title") or text[:80])[:120]
    cleaned = classification.get("text") or text
    tags = classification.get("tags") or []
    due_at = classification.get("due_at")
    now = datetime.now(timezone.utc).isoformat()

    response: dict = {"kind": kind, "title": title}

    if kind == "question":
        # Search archive + answer
        related = await _search_archive(user["user_id"], cleaned, limit=6)
        try:
            answer = await _answer_question(user, cleaned, related)
        except Exception as exc:  # noqa: BLE001
            answer = f"(could not answer: {exc!s})"
        response["question"] = cleaned
        response["answer"] = answer
        response["sources"] = [
            {"entry_id": r["entry_id"], "title": r["title"], "type": r["type"]} for r in related
        ]
        return response

    if kind == "reminder":
        rid = f"rem_{uuid.uuid4().hex[:12]}"
        await db.reminders.insert_one({
            "reminder_id": rid,
            "user_id": user["user_id"],
            "text": cleaned,
            "notes": None,
            "due_at": due_at,
            "status": "open",
            "snooze_until": None,
            "completed_at": None,
            "delivered_at": None,
            "created_at": now,
        })
        response["reminder_id"] = rid
        response["due_at"] = due_at
        response["text"] = cleaned
        return response

    # Everything else → an archive entry
    if kind not in ("memory", "value", "advice", "quote", "note"):
        kind = "note"
    archive_kind = kind if kind != "note" else "memory"
    entry_id = f"ent_{uuid.uuid4().hex[:12]}"
    doc = {
        "entry_id": entry_id,
        "user_id": user["user_id"],
        "type": archive_kind,
        "title": title,
        "content": cleaned,
        "tags": tags,
        "source": "quick_capture",
        "created_at": now,
        "updated_at": now,
    }
    await db.entries.insert_one(doc)
    doc.pop("_id", None)
    response["entry"] = doc
    return response
