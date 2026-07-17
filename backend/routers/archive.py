"""Archive (memories / stories / values / advice / quotes / chapters) CRUD."""
import re as _re
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import EMERGENT_LLM_KEY, db, get_current_user

router = APIRouter(prefix="/archive", tags=["archive"])

EntryType = Literal["memory", "story", "value", "advice", "quote", "chapter", "voice", "import"]


class EntryCreate(BaseModel):
    type: EntryType
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    audio_url: Optional[str] = None
    source: Optional[str] = None  # e.g. "interviewer", "voice_journal", "manual"


class EntryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None


@router.post("")
async def create_entry(payload: EntryCreate, user: dict = Depends(get_current_user)):
    from routers.executor_lock import assert_writable
    await assert_writable(user["user_id"])
    entry_id = f"ent_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "entry_id": entry_id,
        "user_id": user["user_id"],
        "type": payload.type,
        "title": payload.title,
        "content": payload.content,
        "tags": payload.tags,
        "audio_url": payload.audio_url,
        "source": payload.source or "manual",
        "created_at": now,
        "updated_at": now,
    }
    await db.entries.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_entries(
    type: Optional[EntryType] = None,
    q: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    user: dict = Depends(get_current_user),
):
    query: dict = {"user_id": user["user_id"]}
    if type:
        query["type"] = type
    if q:
        safe = _re.escape(q)  # SECURITY: prevent ReDoS / operator injection
        query["$or"] = [
            {"title": {"$regex": safe, "$options": "i"}},
            {"content": {"$regex": safe, "$options": "i"}},
            {"tags": {"$regex": safe, "$options": "i"}},
        ]
    cursor = db.entries.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


@router.get("/{entry_id}")
async def get_entry(entry_id: str, user: dict = Depends(get_current_user)):
    doc = await db.entries.find_one(
        {"entry_id": entry_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Entry not found")
    return doc


@router.patch("/{entry_id}")
async def update_entry(entry_id: str, payload: EntryUpdate, user: dict = Depends(get_current_user)):
    from routers.executor_lock import assert_writable
    await assert_writable(user["user_id"])
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.entries.update_one(
        {"entry_id": entry_id, "user_id": user["user_id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Entry not found")
    doc = await db.entries.find_one({"entry_id": entry_id}, {"_id": 0})
    return doc


@router.delete("/{entry_id}")
async def delete_entry(entry_id: str, user: dict = Depends(get_current_user)):
    from routers.executor_lock import assert_writable
    await assert_writable(user["user_id"])
    res = await db.entries.delete_one({"entry_id": entry_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}


# ----------- Ask the Archive (StoryFile-style Q&A retrieval) -----------
class AskReq(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)


def _score_entry(entry: dict, tokens: list[str]) -> int:
    """Simple keyword-overlap score. Good enough until we add embeddings."""
    text = f"{entry.get('title','')} {entry.get('content','')} {' '.join(entry.get('tags') or [])}".lower()
    return sum(text.count(t) for t in tokens)


@router.post("/ask")
async def ask_archive(payload: AskReq, user: dict = Depends(get_current_user)):
    """Returns a Claude-synthesised answer based on the most relevant archive
    entries, plus the IDs cited so the UI can highlight them."""
    q = payload.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Question is empty")

    top: list[dict] = []
    try:
        from semantic_search import semantic_search
        top = await semantic_search(user["user_id"], q, limit=12)
    except Exception:
        top = []

    if not top:
        STOP = {
            "the","a","an","of","in","on","to","for","was","is","are","what","where","when",
            "who","why","how","my","me","i","did","do","does","that","this","at","with","and","you","your",
        }
        tokens = [
            t for t in _re.split(r"\W+", q.lower()) if len(t) > 2 and t not in STOP
        ][:10]

        cursor = db.entries.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).limit(400)
        entries = await cursor.to_list(length=400)
        if not entries:
            return {"answer": "Your archive is empty — nothing to look back on yet.", "citations": []}

        if tokens:
            scored = [(e, _score_entry(e, tokens)) for e in entries]
            scored.sort(key=lambda x: x[1], reverse=True)
            top = [e for e, s in scored if s > 0][:12]
            if not top:
                top = entries[:8]
        else:
            top = entries[:8]

    cite_lines = []
    for e in top:
        cite_lines.append(
            f"[id={e.get('entry_id')}] [{e.get('type','').upper()}] {e.get('title','')}\n{(e.get('content') or '')[:1200]}"
        )

    system = (
        "You answer questions about the user's life using ONLY the entries below. "
        "Quote exact phrases when relevant. If the entries don't answer the question, say so honestly. "
        "Be concise — 2-5 sentences. Refer to the user as 'you'."
    )
    body = (
        f"Question: {q}\n\n=== ARCHIVE ENTRIES ({len(top)}) ===\n"
        + "\n\n".join(cite_lines)
    )
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"ask_{user['user_id']}_{int(datetime.now(timezone.utc).timestamp())}",
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-6")
    try:
        reply = await chat.send_message(UserMessage(text=body))
        reply_text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc!s}") from exc

    return {
        "answer": reply_text,
        "citations": [
            {
                "entry_id": e.get("entry_id"),
                "title": e.get("title"),
                "type": e.get("type"),
                "snippet": (e.get("content") or "")[:280],
                "created_at": e.get("created_at"),
            }
            for e in top
        ],
    }
