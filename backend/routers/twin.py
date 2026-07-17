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
from routers.live import publish_turn as live_publish_turn
from routers.music import detect_music_intent, play_for_user
from routers.personas import get_active_persona
from routers.skills import invoke_skill_internal, match_skill_trigger
from twin_prompt import build_twin_system, load_personality_blob
from twin_tools import TOOL_SCHEMAS, execute_tool
from utils import rate_limit
import abilities as ab

router = APIRouter(prefix="/twin", tags=["twin"])


# Back-compat alias — older imports / tests may reference the private name.
def _build_twin_system(*args, **kwargs):
    return build_twin_system(*args, **kwargs)


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

    # Which abilities has the owner turned on? Gates short-circuits + tool set.
    enabled_ids = await ab.enabled_ability_ids(user["user_id"])
    enabled_tools = await ab.enabled_tool_names(user["user_id"])

    # ---- Music intent short-circuit (only if the Music ability is on) ----
    music_query = detect_music_intent(payload.message) if "music" in enabled_ids else None
    if music_query:
        await rate_limit(user["user_id"], "twin", max_calls=20, per_seconds=60)
        result = await play_for_user(user["user_id"], music_query)
        if result["queued"]:
            reply = f"Putting on {music_query} for you on {result['provider_name']}."
        else:
            reply = f"No companion PC is connected — opening {music_query} on {result['provider_name']} in your browser."

        now_iso = datetime.now(timezone.utc).isoformat()
        await db.conversations.update_one(
            {"conversation_id": payload.conversation_id, "user_id": user["user_id"]},
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

    # ---- Auto-skill intent short-circuit (only if Smart Home ability is on) ----
    matched_skill = await match_skill_trigger(user["user_id"], payload.message) if "smart_home" in enabled_ids else None
    if matched_skill:
        await rate_limit(user["user_id"], "twin", max_calls=20, per_seconds=60)
        result = await invoke_skill_internal(user["user_id"], matched_skill["skill_id"])
        skill_name = matched_skill.get("name", "the skill")
        if result.get("ok"):
            reply = f"Done — running {skill_name}."
        else:
            err = result.get("error") or f"HTTP {result.get('status')}"
            reply = f"I tried to run {skill_name} but it failed: {err}"

        now_iso = datetime.now(timezone.utc).isoformat()
        await db.conversations.update_one(
            {"conversation_id": payload.conversation_id, "user_id": user["user_id"]},
            {
                "$push": {"messages": {"$each": [
                    {"role": "user", "content": payload.message, "ts": now_iso},
                    {
                        "role": "assistant",
                        "content": reply,
                        "ts": now_iso,
                        "action": {
                            "kind": "skill",
                            "skill_id": matched_skill["skill_id"],
                            "skill_name": skill_name,
                            "ok": result.get("ok", False),
                            "status": result.get("status", 0),
                        },
                    },
                ]}},
                "$set": {"updated_at": now_iso},
            },
        )

        async def skill_stream():
            yield "data: " + json.dumps({"text": reply}) + "\n\n"
            yield "event: action\ndata: " + json.dumps({
                "kind": "skill",
                "skill_id": matched_skill["skill_id"],
                "skill_name": skill_name,
                "ok": result.get("ok", False),
                "status": result.get("status", 0),
            }) + "\n\n"
            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(
            skill_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    await rate_limit(user["user_id"], "twin", max_calls=20, per_seconds=60)
    archive = await _archive_blob(user["user_id"], query_hint=payload.message)
    skills = await _skills_blob(user["user_id"])
    memory_pack = await build_memory_pack(user["user_id"], query_hint=payload.message)
    memory_blob = format_memory_pack_for_prompt(memory_pack)
    persona = await get_active_persona(user["user_id"], user)
    # Merge safe topics from user + persona
    merged_safe = list({*(user.get("safe_topics") or []), *((persona or {}).get("extra_safe_topics") or [])})
    brand = {
        "brand_name": user.get("brand_name") or "",
        "brand_tagline": user.get("brand_tagline") or "",
        "brand_signoff": user.get("brand_signoff") or "",
    }
    if not any(brand.values()):
        brand = None
    abilities_block = ab.build_abilities_prompt(enabled_ids)
    personality_blob = await load_personality_blob(db, user["user_id"])
    system = build_twin_system(
        user.get("name", ""), memory_blob, archive, skills, merged_safe,
        persona=persona, brand=brand, abilities_block=abilities_block,
        personality_blob=personality_blob,
    )

    # Replay prior turns so the twin remembers what was just said.
    initial_messages = [{"role": "system", "content": system}]
    for m in conv.get("messages", []):
        if m.get("role") in ("user", "assistant") and m.get("content"):
            initial_messages.append({"role": m["role"], "content": m["content"]})

    # Only expose the tools from abilities the owner has enabled (+ core memory).
    active_schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in enabled_tools]

    chat = (
        LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=payload.conversation_id,
            system_message=system,
            initial_messages=initial_messages,
        )
        .with_model("anthropic", "claude-sonnet-4-6")
        .with_tools(active_schemas)
    )

    user_turn = {"role": "user", "content": payload.message, "ts": datetime.now(timezone.utc).isoformat()}

    async def gen():
        """Streams a tool-use aware conversation.

        Loop:
          1. Send the user message → get ChatResponse
          2. If tool_calls, emit `event: tool` for each, execute, feed results back
          3. Loop until finish_reason != "tool_calls" (max 6 iterations)
          4. Stream the final text as one JSON `data:` event (frontend already
             handles this cleanly — same shape as single-shot deltas)
        """
        full = ""
        tool_trace: list[dict] = []
        try:
            # First call — carries the user message
            resp = await chat.send_message_with_tools(UserMessage(text=payload.message))
            for _iteration in range(6):
                if resp.finish_reason != "tool_calls" or not resp.tool_calls:
                    break
                # Emit tool_start for each call, execute, add result
                for tc in resp.tool_calls:
                    yield "event: tool\ndata: " + json.dumps({
                        "phase": "start",
                        "id": tc.id,
                        "name": tc.name,
                        "args": tc.arguments,
                    }) + "\n\n"
                    result = await execute_tool(tc.name, user["user_id"], tc.arguments or {})
                    chat.add_tool_result(tc.id, result.get("summary", ""))
                    tool_trace.append({
                        "id": tc.id,
                        "name": tc.name,
                        "args": tc.arguments,
                        "ui": result.get("ui") or {},
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
                    yield "event: tool\ndata: " + json.dumps({
                        "phase": "result",
                        "id": tc.id,
                        "name": tc.name,
                        "ui": result.get("ui") or {},
                    }) + "\n\n"
                # Continue the conversation — no new user message
                resp = await chat.send_message_with_tools()
            full = (resp.content or "").strip()
            if full:
                # One-shot delta so the frontend renders it in the same pipeline
                yield "data: " + json.dumps({"text": full}) + "\n\n"
        except Exception as exc:  # noqa: BLE001
            yield "event: error\ndata: " + json.dumps({"error": str(exc)}) + "\n\n"
            return

        assistant_turn = {
            "role": "assistant",
            "content": full,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if tool_trace:
            assistant_turn["tool_trace"] = tool_trace

        await db.conversations.update_one(
            {"conversation_id": payload.conversation_id, "user_id": user["user_id"]},
            {
                "$push": {"messages": {"$each": [user_turn, assistant_turn]}},
                "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
            },
        )
        # Fire-and-forget episodic summary (won't block the SSE close)
        try:
            await maybe_summarise_episode(user["user_id"], payload.conversation_id)
        except Exception:  # noqa: BLE001
            pass
        # Fan out to live-stream viewers (no-op if broadcast is off)
        try:
            await live_publish_turn(user["user_id"], "user", payload.message, source="web")
            await live_publish_turn(user["user_id"], "assistant", full, source="web")
        except Exception:  # noqa: BLE001
            pass
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
