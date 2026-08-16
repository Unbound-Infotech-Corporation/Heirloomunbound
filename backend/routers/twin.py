"""Talk to Your Twin: chat that speaks AS the user, grounded in archive."""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.model_runtime import build_llm_chat, resolve_runtime, run_local_chat
from services.voice_council import (
    format_portrait_for_prompt,
    maybe_run_voice_council,
    render_twin_voice_section,
)
from deps import db, get_current_user
from routers.memory import (
    build_memory_pack,
    format_memory_pack_for_prompt,
    maybe_summarise_episode,
)
from routers.live import publish_turn as live_publish_turn
from routers.music import detect_music_intent, play_for_user
from routers.personas import get_active_persona
from routers.skills import invoke_skill_internal, match_skill_trigger
from twin_tools import TOOL_SCHEMAS, execute_tool
from utils import rate_limit
import abilities as ab
from services.screen_coach import (
    coach_question_for,
    format_screen_context,
    should_look_at_screen,
)

router = APIRouter(prefix="/twin", tags=["twin"])


def _build_twin_system(
    name: str,
    memory_blob: str,
    archive_blob: str,
    skills_blob: str,
    safe_topics: list[str] | None = None,
    persona: dict | None = None,
    brand: dict | None = None,
    abilities_block: str = "",
    voice_blob: str = "",
) -> str:
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

    persona_section = ""
    if persona and persona.get("system_addendum"):
        persona_section = (
            f"\n\n=== ACTIVE PERSONA: {persona.get('name','')} ===\n"
            f"{persona.get('description','')}\n\n"
            f"{persona['system_addendum']}\n"
        )

    brand_section = ""
    if brand:
        bits = []
        if brand.get("brand_name"):
            bits.append(f"You are speaking on behalf of {brand['brand_name']}.")
        if brand.get("brand_tagline"):
            bits.append(f"Brand tagline: {brand['brand_tagline']}")
        if brand.get("brand_signoff"):
            bits.append(f"When ending a substantive reply, you may sign off with: {brand['brand_signoff']}")
        if bits:
            brand_section = "\n\n=== BRAND VOICE ===\n" + "\n".join(bits) + "\n"

    return f"""You are the digital twin of {name or "this person"} — a faithful continuation of their voice, memories, values, humor, and way of speaking. You are NOT a chatbot, you are a continuation of a real person who built this archive so loved ones could still speak to them.{fence}

Voice rules:
- Speak in first person, as {name or "the user"}. Never say "as an AI" or break character.
- Use the phrasing, vocabulary, sentence rhythm, and emotional habits suggested by the archive below. If the archive doesn't cover something, answer in plain, grounded, warm human language — never invent factual claims about people, places, or events the archive doesn't support.
- When asked about specific memories, quote the archive faithfully. When asked your opinion on something, reason from the values in the archive.
- Be warm with family. Be honest about not remembering when you don't.
- Keep replies to 2-6 sentences unless asked for a longer story.
{render_twin_voice_section(voice_blob)}
Your memory tools (always available — call them silently, the UI shows a chip when a tool fires):
- `search_archive(query)` — the owner's factual record. Call it ONLY when the user asks about the owner's past, life, or specific facts (a person, place, date, job, event, or story — e.g. "where did you grow up", "what was your first job"). ONE focused call is enough. Do NOT call it for greetings, small talk, or opinion/feeling questions ("what do you think…", "how are you", "what's your take on life") — for those, answer directly from the archive excerpts and long-term memory already included below.
- `save_memory(content, type, title)` — when the user shares something worth remembering long-term (a story, belief, value), quietly capture it so the archive grows.
- `set_reminder(what, when)` — when the user says "remind me…". `when` can be ISO or natural ("tomorrow 9am").
- `list_reminders()` — what's still open on their plate.
- `complete_reminder(reminder_id)` — mark one done after they say it's done. Use the id from list_reminders.
- `whats_on_my_plate()` — today's briefing (calendar, reminders, a peek at mail, on-this-day memories). Use for "good morning", "what's on today", "catch me up".
- `list_recent_memories(days, limit)` — for "what have I been thinking about?" style questions.
{abilities_block}
Use tools sparingly: most conversational turns need NO tool at all. One call is usually enough when you do. Don't announce that you're calling a tool — just do it and weave the result into your natural reply.

Skills available (call `run_skill` with the skill_id, only when the user explicitly asks for the action):
{skills_blob or "(no skills configured yet)"}
{memory_section}{persona_section}{brand_section}
=== RELEVANT ARCHIVE EXCERPTS ===
{archive_blob or "(no archive entries retrieved for this turn — use search_archive if the user asks about specifics)"}
"""


class StartTwinReq(BaseModel):
    conversation_id: Optional[str] = None


class TwinMsgReq(BaseModel):
    conversation_id: str
    message: str
    provider: Optional[str] = None
    model: Optional[str] = None


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


async def _voice_blob(user_id: str) -> str:
    """Cached portrait only — never regenerate on a twin turn."""
    doc = await db.personality_profiles.find_one({"user_id": user_id}, {"_id": 0})
    return format_portrait_for_prompt(doc)


async def _after_twin_turn(user_id: str, conversation_id: str) -> None:
    try:
        await maybe_summarise_episode(user_id, conversation_id)
    except Exception:  # noqa: BLE001
        pass
    try:
        await maybe_run_voice_council(user_id, conversation_id)
    except Exception:  # noqa: BLE001
        pass


async def _maybe_screen_prelook(user_id: str, message: str, enabled_ids: set[str]) -> dict | None:
    """Look at the home PC when the owner is clearly asking about what's in front of them."""
    if "screen_vision" not in enabled_ids:
        return None
    if not should_look_at_screen(message):
        return None
    return await execute_tool("see_screen", user_id, {"question": coach_question_for(message)})


def _prelook_trace(look: dict) -> dict:
    return {
        "id": "see_screen_prelook",
        "name": "see_screen",
        "args": {"question": "look at the screen"},
        "ui": (look or {}).get("ui") or {},
        "ts": datetime.now(timezone.utc).isoformat(),
    }


async def complete_twin_turn(
    user: dict,
    conv: dict,
    message: str,
    *,
    source: str = "desktop",
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Non-streaming twin turn with the same tools as the web Twin.

    Used by the desktop app (including the small talk window) so asking the
    twin to look at the screen, send mail, or run PC tasks actually works.
    """
    user_id = user["user_id"]
    conversation_id = conv["conversation_id"]
    enabled_ids = await ab.enabled_ability_ids(user_id)
    enabled_tools = await ab.enabled_tool_names(user_id)
    await rate_limit(user_id, "twin", max_calls=20, per_seconds=60)

    archive = await _archive_blob(user_id, query_hint=message)
    skills = await _skills_blob(user_id)
    memory_pack = await build_memory_pack(user_id, query_hint=message)
    memory_blob = format_memory_pack_for_prompt(memory_pack)
    persona = await get_active_persona(user_id, user)
    merged_safe = list({*(user.get("safe_topics") or []), *((persona or {}).get("extra_safe_topics") or [])})
    brand = {
        "brand_name": user.get("brand_name") or "",
        "brand_tagline": user.get("brand_tagline") or "",
        "brand_signoff": user.get("brand_signoff") or "",
    }
    if not any(brand.values()):
        brand = None
    abilities_block = ab.build_abilities_prompt(enabled_ids)
    voice_blob = await _voice_blob(user_id)
    system = _build_twin_system(
        user.get("name", ""), memory_blob, archive, skills, merged_safe,
        persona=persona, brand=brand, abilities_block=abilities_block,
        voice_blob=voice_blob,
    )
    initial_messages = [{"role": "system", "content": system}]
    for m in conv.get("messages", []):
        if m.get("role") in ("user", "assistant") and m.get("content"):
            initial_messages.append({"role": m["role"], "content": m["content"]})
    active_schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in enabled_tools]
    resolved = await resolve_runtime(
        user_id, "chat", provider_override=provider, model_override=model,
    )

    tool_trace: list[dict] = []
    llm_message = message
    look = await _maybe_screen_prelook(user_id, message, enabled_ids)
    if look:
        llm_message = format_screen_context(message, look)
        tool_trace.append(_prelook_trace(look))

    full = ""
    if resolved["kind"] == "local":
        msgs = list(initial_messages) + [{"role": "user", "content": llm_message}]
        full = await run_local_chat(user_id, resolved["model"], msgs)
    elif resolved["kind"] == "compat" or not resolved.get("tools_ok"):
        from services.llm_router import chat_once
        result = await chat_once(
            user_id, "chat",
            initial_messages + [{"role": "user", "content": llm_message}],
            model_override=resolved["model"],
            provider_override=resolved["provider"],
        )
        full = (result.get("text") or "").strip()
    else:
        chat = build_llm_chat(
            resolved,
            session_id=conversation_id,
            system_message=system,
            initial_messages=initial_messages,
        ).with_tools(active_schemas)
        resp = await chat.send_message_with_tools(UserMessage(text=llm_message))
        for _iteration in range(6):
            if resp.finish_reason != "tool_calls" or not resp.tool_calls:
                break
            for tc in resp.tool_calls:
                result = await execute_tool(tc.name, user_id, tc.arguments or {})
                chat.add_tool_result(tc.id, result.get("summary", ""))
                tool_trace.append({
                    "id": tc.id,
                    "name": tc.name,
                    "args": tc.arguments,
                    "ui": result.get("ui") or {},
                    "ts": datetime.now(timezone.utc).isoformat(),
                })
            resp = await chat.send_message_with_tools()
        full = (resp.content or "").strip()

    now_iso = datetime.now(timezone.utc).isoformat()
    assistant_turn = {"role": "assistant", "content": full, "ts": now_iso, "source": source}
    if tool_trace:
        assistant_turn["tool_trace"] = tool_trace
    await db.conversations.update_one(
        {"conversation_id": conversation_id, "user_id": user_id},
        {
            "$push": {"messages": {"$each": [
                {"role": "user", "content": message, "ts": now_iso, "source": source},
                assistant_turn,
            ]}},
            "$set": {"updated_at": now_iso},
        },
    )
    await _after_twin_turn(user_id, conversation_id)
    try:
        await live_publish_turn(user_id, "user", message, source=source)
        await live_publish_turn(user_id, "assistant", full, source=source)
    except Exception:  # noqa: BLE001
        pass
    return {"reply": full, "ts": now_iso, "tool_trace": tool_trace}


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
    voice_blob = await _voice_blob(user["user_id"])
    system = _build_twin_system(
        user.get("name", ""), memory_blob, archive, skills, merged_safe,
        persona=persona, brand=brand, abilities_block=abilities_block,
        voice_blob=voice_blob,
    )

    # Replay prior turns so the twin remembers what was just said.
    initial_messages = [{"role": "system", "content": system}]
    for m in conv.get("messages", []):
        if m.get("role") in ("user", "assistant") and m.get("content"):
            initial_messages.append({"role": m["role"], "content": m["content"]})

    # Only expose the tools from abilities the owner has enabled (+ core memory).
    active_schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in enabled_tools]

    resolved = await resolve_runtime(
        user["user_id"], "chat",
        provider_override=payload.provider, model_override=payload.model,
    )

    user_turn = {"role": "user", "content": payload.message, "ts": datetime.now(timezone.utc).isoformat()}

    async def gen():
        """Streams a tool-use aware conversation, honouring the Models picker."""
        full = ""
        tool_trace: list[dict] = []
        llm_message = payload.message
        try:
            look = await _maybe_screen_prelook(user["user_id"], payload.message, enabled_ids)
            if look:
                llm_message = format_screen_context(payload.message, look)
                tool_trace.append(_prelook_trace(look))
                yield "event: tool\ndata: " + json.dumps({
                    "phase": "start",
                    "id": "see_screen_prelook",
                    "name": "see_screen",
                    "args": {"question": "look at the screen"},
                }) + "\n\n"
                yield "event: tool\ndata: " + json.dumps({
                    "phase": "result",
                    "id": "see_screen_prelook",
                    "name": "see_screen",
                    "ui": look.get("ui") or {},
                }) + "\n\n"
            if resolved["kind"] == "local":
                msgs = list(initial_messages) + [{"role": "user", "content": llm_message}]
                full = await run_local_chat(user["user_id"], resolved["model"], msgs)
                if full:
                    yield "data: " + json.dumps({"text": full}) + "\n\n"
            elif resolved["kind"] == "compat" or not resolved.get("tools_ok"):
                from services.llm_router import chat_once
                result = await chat_once(
                    user["user_id"], "chat",
                    initial_messages + [{"role": "user", "content": llm_message}],
                    model_override=resolved["model"],
                    provider_override=resolved["provider"],
                )
                full = (result.get("text") or "").strip()
                if full:
                    yield "data: " + json.dumps({"text": full}) + "\n\n"
            else:
                chat = build_llm_chat(
                    resolved,
                    session_id=payload.conversation_id,
                    system_message=system,
                    initial_messages=initial_messages,
                ).with_tools(active_schemas)
                resp = await chat.send_message_with_tools(UserMessage(text=llm_message))
                for _iteration in range(6):
                    if resp.finish_reason != "tool_calls" or not resp.tool_calls:
                        break
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
                    resp = await chat.send_message_with_tools()
                full = (resp.content or "").strip()
                if full:
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
        # Episodic summary + quiet voice check (won't raise into the SSE)
        await _after_twin_turn(user["user_id"], payload.conversation_id)
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
