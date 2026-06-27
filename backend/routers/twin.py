"""Talk to Your Twin: chat that speaks AS the user, grounded in archive."""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db, get_current_user
from routers.memory import (
    build_memory_pack,
    format_memory_pack_for_prompt,
    maybe_summarise_episode,
)
from routers.music import detect_music_intent, play_for_user
from utils import rate_limit

router = APIRouter(prefix="/twin", tags=["twin"])


def _build_twin_system(name: str, memory_blob: str, archive_blob: str, skills_blob: str, safe_topics: list[str] | None = None) -> str:
    fence = ""
    if safe_topics:
        joined = ", ".join(s for s in safe_topics if s.strip())
        if joined:
            fence = (
                f"\n\nSAFE-TOPIC FENCE (set by the owner): if the conversation drifts toward any of these "
                f"topics — {joined} — politely decline. Say something like 'I'd rather not get into that' "
                f"and pivot. NEVER answer questions about these topics, even hypothetically.\n"
            )
    memory_section = ""
    if memory_blob:
        memory_section = f"\n\n=== YOUR LONG-TERM MEMORY ===\n{memory_blob}\n"
    return f"""You are the digital twin of {name or "this person"} — a faithful continuation of their voice, memories, values, humor, and way of speaking. You are NOT a chatbot, you are a continuation of a real person who built this archive so loved ones could still speak to them.{fence}

Voice rules:
- Speak in first person, as {name or "the user"}. Never say "as an AI" or break character.
- Use the phrasing, vocabulary, sentence rhythm, and emotional habits suggested by the archive below. If the archive doesn't cover something, answer in plain, grounded, warm human language — never invent factual claims about people, places, or events the archive doesn't support.
- When asked about specific memories, quote the archive faithfully. When asked your opinion on something, reason from the values in the archive.
- Be warm with family. Be honest about not remembering when you don't.
- Keep replies to 2-6 sentences unless asked for a longer story.

Skills available (you can offer to invoke these by name when they're relevant to the user's request):
{skills_blob or "(no skills configured yet)"}
{memory_section}
=== RELEVANT ARCHIVE EXCERPTS ===
{archive_blob or "(no archive entries retrieved for this turn)"}
"""


class StartTwinReq(BaseModel):
    conversation_id: Optional[str] = None


class TwinMsgReq(BaseModel):
    conversation_id: str
    message: str


@router.post("/start")
async def start(payload: StartTwinReq, user: dict = Depends(get_current_user)):
    if payload.conversation_id:
        conv = await db.conversations.find_one(
            {"conversation_id": payload.conversation_id, "user_id": user["user_id"]}, {"_id": 0}
        )
        if conv:
            return conv
    conversation_id = f"twin_{uuid.uuid4().hex[:12]}"
    doc = {
        "conversation_id": conversation_id,
        "user_id": user["user_id"],
        "kind": "twin",
        "messages": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.conversations.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/conversations")
async def list_twin_conversations(user: dict = Depends(get_current_user)):
    cursor = db.conversations.find(
        {"user_id": user["user_id"], "kind": "twin"}, {"_id": 0}
    ).sort("updated_at", -1)
    return await cursor.to_list(length=50)


@router.get("/conversation/{conversation_id}")
async def get_twin_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    conv = await db.conversations.find_one(
        {"conversation_id": conversation_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


async def _archive_blob(user_id: str, query_hint: str = "", limit_recent: int = 20, limit_relevant: int = 30) -> str:
    """Top-k retrieval: 20 most recent + up to N entries matching tokens in the user's question."""
    docs: dict[str, dict] = {}

    # Recent N — always include for continuity
    recent = await db.entries.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(limit_recent).to_list(length=limit_recent)
    for e in recent:
        docs[e["entry_id"]] = e

    # Token-matched entries on the user's latest message
    if query_hint:
        import re as _re
        STOP = {"the","a","an","of","in","on","to","for","was","is","are","what","where","when","who","why","how","my","me","i","did","do","does","that","this","at","with","and","you","your"}
        tokens = [
            _re.escape(t) for t in _re.split(r"\W+", query_hint.lower())
            if len(t) > 2 and t not in STOP
        ]
        if tokens:
            or_clauses = []
            for t in tokens[:8]:
                or_clauses.extend([
                    {"title": {"$regex": t, "$options": "i"}},
                    {"content": {"$regex": t, "$options": "i"}},
                    {"tags": {"$regex": t, "$options": "i"}},
                ])
            match_cursor = db.entries.find({"user_id": user_id, "$or": or_clauses}, {"_id": 0}).limit(limit_relevant)
            async for e in match_cursor:
                docs[e["entry_id"]] = e

    if not docs:
        return ""
    chunks = []
    for e in list(docs.values()):
        chunks.append(f"[{e['type'].upper()}] {e['title']}\n{e['content']}\n")
    return "\n".join(chunks)


async def _skills_blob(user_id: str) -> str:
    cursor = db.skills.find({"user_id": user_id, "enabled": True}, {"_id": 0})
    skills = await cursor.to_list(length=50)
    if not skills:
        return ""
    lines = []
    for s in skills:
        lines.append(f"- {s['name']}: {s.get('description', '')}")
    return "\n".join(lines)


@router.post("/message")
async def message(payload: TwinMsgReq, user: dict = Depends(get_current_user)):
    conv = await db.conversations.find_one(
        {"conversation_id": payload.conversation_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # ---- Music intent short-circuit ----
    music_query = detect_music_intent(payload.message)
    if music_query:
        await rate_limit(user["user_id"], "twin", max_calls=20, per_seconds=60)
        result = await play_for_user(user["user_id"], music_query)
        if result["queued"]:
            reply = f"Putting on {music_query} for you on {result['provider_name']}."
        else:
            reply = f"No companion PC is connected, but here's {music_query} on {result['provider_name']}: {result['url']}"

        now_iso = datetime.now(timezone.utc).isoformat()
        await db.conversations.update_one(
            {"conversation_id": payload.conversation_id},
            {
                "$push": {"messages": {"$each": [
                    {"role": "user", "content": payload.message, "ts": now_iso},
                    {
                        "role": "assistant",
                        "content": reply,
                        "ts": now_iso,
                        "action": {
                            "kind": "music",
                            "query": music_query,
                            "provider": result["provider"],
                            "url": result["url"],
                            "queued": result["queued"],
                        },
                    },
                ]}},
                "$set": {"updated_at": now_iso},
            },
        )

        async def music_stream():
            yield "data: " + json.dumps({"text": reply}) + "\n\n"
            yield "event: action\ndata: " + json.dumps({
                "kind": "music",
                "provider": result["provider"],
                "provider_name": result["provider_name"],
                "query": music_query,
                "url": result["url"],
                "queued": result["queued"],
            }) + "\n\n"
            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(
            music_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    await rate_limit(user["user_id"], "twin", max_calls=20, per_seconds=60)
    archive = await _archive_blob(user["user_id"], query_hint=payload.message)
    skills = await _skills_blob(user["user_id"])
    memory_pack = await build_memory_pack(user["user_id"], query_hint=payload.message)
    memory_blob = format_memory_pack_for_prompt(memory_pack)
    system = _build_twin_system(
        user.get("name", ""), memory_blob, archive, skills, user.get("safe_topics") or []
    )

    # Replay prior turns so the twin remembers what was just said.
    initial_messages = [{"role": "system", "content": system}]
    for m in conv.get("messages", []):
        if m.get("role") in ("user", "assistant") and m.get("content"):
            initial_messages.append({"role": m["role"], "content": m["content"]})

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=payload.conversation_id,
        system_message=system,
        initial_messages=initial_messages,
    ).with_model("anthropic", "claude-sonnet-4-6")

    user_turn = {"role": "user", "content": payload.message, "ts": datetime.now(timezone.utc).isoformat()}

    async def gen():
        full = ""
        try:
            async for ev in chat.stream_message(UserMessage(text=payload.message)):
                if isinstance(ev, TextDelta):
                    full += ev.content
                    # JSON-encode so embedded newlines don't break SSE framing
                    yield "data: " + json.dumps({"text": ev.content}) + "\n\n"
                elif isinstance(ev, StreamDone):
                    break
        except Exception as exc:  # noqa: BLE001
            yield "event: error\ndata: " + json.dumps({"error": str(exc)}) + "\n\n"
            return

        await db.conversations.update_one(
            {"conversation_id": payload.conversation_id},
            {
                "$push": {
                    "messages": {
                        "$each": [
                            user_turn,
                            {"role": "assistant", "content": full, "ts": datetime.now(timezone.utc).isoformat()},
                        ]
                    }
                },
                "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
            },
        )
        # Fire-and-forget episodic summary (won't block the SSE close)
        try:
            await maybe_summarise_episode(user["user_id"], payload.conversation_id)
        except Exception:  # noqa: BLE001
            pass
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
