"""Shared twin turn runtime — used by web twin, desktop chat, and companion voice.

Gives every surface the same brain: abilities-gated tools, memory pack,
archive retrieval, music/skill short-circuits, and safe-topic fences.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage

from deps import EMERGENT_LLM_KEY, db
import abilities as ab
from routers.memory import (
    build_memory_pack,
    format_memory_pack_for_prompt,
    maybe_summarise_episode,
)
from routers.music import detect_music_intent, play_for_user
from routers.personas import get_active_persona
from routers.skills import invoke_skill_internal, match_skill_trigger
from twin_tools import TOOL_SCHEMAS, execute_tool
from utils import rate_limit

_MAX_HISTORY_TURNS = 24
_ARCHIVE_CONTENT_CHARS = 900
_STOP_WORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "to", "for", "was", "is", "are",
    "what", "where", "when", "who", "why", "how", "my", "me", "i", "did",
    "do", "does", "that", "this", "at", "with", "and", "you", "your",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_twin_system(
    name: str,
    memory_blob: str,
    archive_blob: str,
    skills_blob: str,
    safe_topics: list[str] | None = None,
    persona: dict | None = None,
    brand: dict | None = None,
    abilities_block: str = "",
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

Your memory tools (always available — call them silently, the UI shows a chip when a tool fires):
- `search_archive(query)` — the owner's factual record. Call it ONLY when the user asks about the owner's past, life, or specific facts (a person, place, date, job, event, or story — e.g. "where did you grow up", "what was your first job"). ONE focused call is enough. Do NOT call it for greetings, small talk, or opinion/feeling questions ("what do you think…", "how are you", "what's your take on life") — for those, answer directly from the archive excerpts and long-term memory already included below.
- `save_memory(content, type, title)` — when the user shares something worth remembering long-term (a story, belief, value), quietly capture it so the archive grows.
- `set_reminder(what, when)` — when the user says "remind me…". `when` can be ISO or natural ("tomorrow 9am").
- `list_recent_memories(days, limit)` — for "what have I been thinking about?" style questions.
{abilities_block}
Use tools sparingly: most conversational turns need NO tool at all. One call is usually enough when you do. Don't announce that you're calling a tool — just do it and weave the result into your natural reply.

Skills available (call `run_skill` with the skill_id, only when the user explicitly asks for the action):
{skills_blob or "(no skills configured yet)"}
{memory_section}{persona_section}{brand_section}
=== RELEVANT ARCHIVE EXCERPTS ===
{archive_blob or "(no archive entries retrieved for this turn — use search_archive if the user asks about specifics)"}
"""


def _score_entry(entry: dict, tokens: list[str]) -> int:
    if not tokens:
        return 0
    hay = " ".join(
        [
            str(entry.get("title") or ""),
            str(entry.get("content") or ""),
            " ".join(entry.get("tags") or []),
            str(entry.get("type") or ""),
        ]
    ).lower()
    score = 0
    for t in tokens:
        if t in hay:
            score += hay.count(t) + 2
    return score


async def archive_blob(
    user_id: str,
    query_hint: str = "",
    limit_recent: int = 20,
    limit_relevant: int = 30,
) -> str:
    projection = {"_id": 0, "entry_id": 1, "type": 1, "title": 1, "content": 1, "tags": 1, "created_at": 1}
    recent_coro = (
        db.entries.find({"user_id": user_id}, projection)
        .sort("created_at", -1)
        .limit(limit_recent)
        .to_list(length=limit_recent)
    )

    tokens = [
        t for t in re.split(r"\W+", query_hint.lower())
        if len(t) > 2 and t not in _STOP_WORDS
    ]
    match_coro = None
    if tokens:
        or_clauses = []
        for t in tokens[:10]:
            esc = re.escape(t)
            or_clauses.extend([
                {"title": {"$regex": esc, "$options": "i"}},
                {"content": {"$regex": esc, "$options": "i"}},
                {"tags": {"$regex": esc, "$options": "i"}},
            ])
        match_coro = (
            db.entries.find({"user_id": user_id, "$or": or_clauses}, projection)
            .limit(limit_relevant * 2)
            .to_list(length=limit_relevant * 2)
        )

    if match_coro is not None:
        recent, matched = await asyncio.gather(recent_coro, match_coro)
    else:
        recent = await recent_coro
        matched = []

    ranked: dict[str, tuple[int, dict]] = {}
    for e in recent:
        ranked[e["entry_id"]] = (0, e)
    for e in matched:
        score = _score_entry(e, tokens)
        prev = ranked.get(e["entry_id"])
        if not prev or score > prev[0]:
            ranked[e["entry_id"]] = (score, e)

    ordered = sorted(ranked.values(), key=lambda pair: pair[0], reverse=True)
    if tokens:
        docs = [e for score, e in ordered if score > 0][:limit_relevant]
        if len(docs) < 8:
            seen = {d["entry_id"] for d in docs}
            for _score, e in ordered:
                if e["entry_id"] in seen:
                    continue
                docs.append(e)
                seen.add(e["entry_id"])
                if len(docs) >= limit_recent:
                    break
    else:
        docs = [e for _score, e in ordered[:limit_recent]]

    if not docs:
        return ""
    chunks = []
    for e in docs:
        content = (e.get("content") or "")[:_ARCHIVE_CONTENT_CHARS]
        chunks.append(f"[{(e.get('type') or 'note').upper()}] {e.get('title', '')}\n{content}\n")
    return "\n".join(chunks)


async def skills_blob(user_id: str) -> str:
    cursor = db.skills.find({"user_id": user_id, "enabled": True}, {"_id": 0})
    skills = await cursor.to_list(length=50)
    if not skills:
        return ""
    return "\n".join(f"- {s['name']}: {s.get('description', '')}" for s in skills)


def history_turns(messages: list[dict], limit: int = _MAX_HISTORY_TURNS) -> list[dict]:
    turns = [
        m for m in messages
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    return turns[-limit:]


@dataclass
class TwinTurnResult:
    reply: str
    tool_trace: list[dict] = field(default_factory=list)
    action: Optional[dict] = None
    conversation_id: str = ""
    ts: str = ""
    backend: str = "cloud_claude"


@dataclass
class TwinBrainPack:
    system: str
    history: list[dict]
    conversation_id: str
    twin_backend: str


async def ensure_conversation(
    user_id: str,
    *,
    kind: str,
    conversation_id: Optional[str] = None,
) -> dict:
    """Load an existing conversation or create one for the given kind."""
    if conversation_id:
        conv = await db.conversations.find_one(
            {"conversation_id": conversation_id, "user_id": user_id}, {"_id": 0}
        )
        if conv:
            return conv
    if kind:
        conv = await db.conversations.find_one(
            {"user_id": user_id, "kind": kind}, {"_id": 0}
        )
        if conv:
            return conv
    prefix = "twin" if kind == "twin" else "comp"
    conv = {
        "conversation_id": f"{prefix}_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "kind": kind or "twin",
        "messages": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.conversations.insert_one(dict(conv))
    return conv


async def build_brain_pack(
    user: dict,
    message: str,
    *,
    conversation: dict,
) -> TwinBrainPack:
    """Assemble system + history for a twin turn without calling the LLM."""
    from model_router import resolve_twin_backend, runtime_probe_from_user

    user_id = user["user_id"]
    text = (message or "").strip()
    if not text:
        raise ValueError("Empty message")

    enabled_ids = await ab.enabled_ability_ids(user_id)
    archive, skills, memory_pack, persona = await asyncio.gather(
        archive_blob(user_id, query_hint=text),
        skills_blob(user_id),
        build_memory_pack(user_id, query_hint=text),
        get_active_persona(user_id, user),
    )
    memory_blob = format_memory_pack_for_prompt(memory_pack)
    merged_safe = list({
        *(user.get("safe_topics") or []),
        *((persona or {}).get("extra_safe_topics") or []),
    })
    brand = {
        "brand_name": user.get("brand_name") or "",
        "brand_tagline": user.get("brand_tagline") or "",
        "brand_signoff": user.get("brand_signoff") or "",
    }
    if not any(brand.values()):
        brand = None

    system = build_twin_system(
        user.get("name", ""),
        memory_blob,
        archive,
        skills,
        merged_safe,
        persona=persona,
        brand=brand,
        abilities_block=ab.build_abilities_prompt(enabled_ids),
    )
    probe = runtime_probe_from_user(user)
    twin_backend = resolve_twin_backend(user.get("studio_models"), probe)
    return TwinBrainPack(
        system=system,
        history=history_turns(conversation.get("messages", [])),
        conversation_id=conversation["conversation_id"],
        twin_backend=twin_backend,
    )


async def run_twin_turn(
    user: dict,
    message: str,
    *,
    conversation: dict,
    source: str = "web",
    persist: bool = True,
    summarise: bool = True,
    twin_backend: str | None = None,
) -> TwinTurnResult:
    """One full twin turn with tools. Non-streaming — for desktop + companion voice.

    Short-circuits music / skill intents the same way the web SSE path does.
    """
    user_id = user["user_id"]
    conversation_id = conversation["conversation_id"]
    text = (message or "").strip()
    if not text:
        raise ValueError("Empty message")

    enabled_ids = await ab.enabled_ability_ids(user_id)
    enabled_tools = ab.tool_names_for_abilities(enabled_ids)

    # Music short-circuit
    music_query = detect_music_intent(text) if "music" in enabled_ids else None
    if music_query:
        await rate_limit(user_id, "twin", max_calls=20, per_seconds=60)
        result = await play_for_user(user_id, music_query)
        if result["queued"]:
            reply = f"Putting on {music_query} for you on {result['provider_name']}."
        else:
            reply = (
                f"No companion PC is connected — opening {music_query} on "
                f"{result['provider_name']} in your browser."
            )
        action = {
            "kind": "music",
            "query": music_query,
            "provider": result["provider"],
            "provider_name": result["provider_name"],
            "url": result["url"],
            "queued": result["queued"],
        }
        ts = _now_iso()
        if persist:
            await _persist_pair(
                user_id, conversation_id, text, reply, ts,
                source=source, action=action,
            )
        return TwinTurnResult(
            reply=reply, action=action, conversation_id=conversation_id, ts=ts,
        )

    # Skill short-circuit
    matched_skill = (
        await match_skill_trigger(user_id, text) if "smart_home" in enabled_ids else None
    )
    if matched_skill:
        await rate_limit(user_id, "twin", max_calls=20, per_seconds=60)
        result = await invoke_skill_internal(user_id, matched_skill["skill_id"])
        skill_name = matched_skill.get("name", "the skill")
        if result.get("ok"):
            reply = f"Done — running {skill_name}."
        else:
            err = result.get("error") or f"HTTP {result.get('status')}"
            reply = f"I tried to run {skill_name} but it failed: {err}"
        action = {
            "kind": "skill",
            "skill_id": matched_skill["skill_id"],
            "skill_name": skill_name,
            "ok": result.get("ok", False),
            "status": result.get("status", 0),
        }
        ts = _now_iso()
        if persist:
            await _persist_pair(
                user_id, conversation_id, text, reply, ts,
                source=source, action=action,
            )
        return TwinTurnResult(
            reply=reply, action=action, conversation_id=conversation_id, ts=ts,
        )

    await rate_limit(user_id, "twin", max_calls=20, per_seconds=60)

    pack = await build_brain_pack(user, text, conversation=conversation)
    system = pack.system
    backend_used = twin_backend or pack.twin_backend

    tool_trace: list[dict] = []
    if backend_used == "ollama":
        from local_inference import ollama_chat, ollama_ready

        if not ollama_ready():
            backend_used = "cloud_claude"
        else:
            history = list(pack.history)
            history.append({"role": "user", "content": text})
            try:
                reply = await ollama_chat(system, history)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Local twin (Ollama) failed: {exc!s}") from exc
            ts = _now_iso()
            if persist:
                await _persist_pair(
                    user_id, conversation_id, text, reply, ts,
                    source=source, tool_trace=tool_trace,
                )
                if summarise:
                    try:
                        asyncio.create_task(_safe_summarise(user_id, conversation_id))
                    except Exception:  # noqa: BLE001
                        pass
            return TwinTurnResult(
                reply=reply,
                tool_trace=tool_trace,
                conversation_id=conversation_id,
                ts=ts,
                backend=backend_used,
            )

    initial_messages = [{"role": "system", "content": system}]
    for m in pack.history:
        initial_messages.append({"role": m["role"], "content": m["content"]})

    active_schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in enabled_tools]
    chat = (
        LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=conversation_id,
            system_message=system,
            initial_messages=initial_messages,
        )
        .with_model("anthropic", "claude-sonnet-4-6")
        .with_tools(active_schemas)
    )

    try:
        resp = await chat.send_message_with_tools(UserMessage(text=text))
        for _ in range(6):
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
                    "ts": _now_iso(),
                })
            resp = await chat.send_message_with_tools()
        reply = (resp.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"LLM failed: {exc!s}") from exc
    backend_used = "cloud_claude"

    ts = _now_iso()
    if persist:
        await _persist_pair(
            user_id, conversation_id, text, reply, ts,
            source=source, tool_trace=tool_trace,
        )
        if summarise:
            try:
                asyncio.create_task(_safe_summarise(user_id, conversation_id))
            except Exception:  # noqa: BLE001
                pass

    return TwinTurnResult(
        reply=reply,
        tool_trace=tool_trace,
        conversation_id=conversation_id,
        ts=ts,
        backend=backend_used,
    )


async def _safe_summarise(user_id: str, conversation_id: str) -> None:
    try:
        await maybe_summarise_episode(user_id, conversation_id)
    except Exception:  # noqa: BLE001
        pass


async def _persist_pair(
    user_id: str,
    conversation_id: str,
    user_text: str,
    reply: str,
    ts: str,
    *,
    source: str,
    action: Optional[dict] = None,
    tool_trace: Optional[list[dict]] = None,
) -> None:
    user_turn: dict[str, Any] = {
        "role": "user", "content": user_text, "ts": ts, "source": source,
    }
    assistant_turn: dict[str, Any] = {
        "role": "assistant", "content": reply, "ts": ts, "source": source,
    }
    if action:
        assistant_turn["action"] = action
    if tool_trace:
        assistant_turn["tool_trace"] = tool_trace
    await db.conversations.update_one(
        {"conversation_id": conversation_id, "user_id": user_id},
        {
            "$push": {"messages": {"$each": [user_turn, assistant_turn]}},
            "$set": {"updated_at": ts},
        },
    )
