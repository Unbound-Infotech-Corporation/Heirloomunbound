"""Long-term memory for the Twin.

Two kinds of memory beyond the raw archive:

1. **Identity facts** — small, stable claims about the user, extracted from
   the archive. E.g. "Has a son named Elias (born 2014)", "Lives in Vermont".
   Always included in the twin's system prompt so it doesn't forget basics.

2. **Episodic summaries** — short summaries of past twin conversations.
   Generated when a conversation crosses a threshold of messages. Replaces
   the conversation history's bulk while preserving the gist.

Together these let the twin appear to "remember" without re-feeding the
entire archive every turn (closes the Vellum/OpenClaw 2026 gap).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db, get_current_user

router = APIRouter(prefix="/memory", tags=["memory"])

REFRESH_FACTS_AFTER_NEW_ENTRIES = 5  # re-extract when entry count grows by this much
EPISODE_THRESHOLD_MESSAGES = 12       # summarise after this many msgs in one conv
MAX_FACTS_IN_PROMPT = 40              # keep prompt budget sane
MAX_EPISODES_IN_PROMPT = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _extract_json(text: str) -> Optional[dict | list]:
    if not text:
        return None
    m = re.search(r"[\[\{][\s\S]*[\]\}]", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ---------------- Identity facts ----------------
FACT_SYSTEM = """Extract STABLE identity facts about the person from their archive.
A stable fact is one that's likely true a year from now: family members, places lived,
career, signature beliefs, recurring phrases, milestones.

Return ONLY a JSON array (no prose) of up to 40 facts. Each item:
  {"fact": "<one short sentence>", "kind": "<family|place|career|belief|milestone|phrase|other>", "source_entry_id": "<id or null>"}

Rules:
- One sentence each, factual and concrete.
- Skip emotions ("felt sad") — keep things that are durable.
- If unsure, omit. Quality > quantity.
"""


async def _gather_corpus(user_id: str) -> tuple[str, int]:
    cursor = db.entries.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(300)
    entries = await cursor.to_list(length=300)
    chunks = []
    for e in entries:
        chunks.append(
            f"[id={e.get('entry_id')}] [{e.get('type','').upper()}] {e.get('title','')}\n{(e.get('content') or '')[:1000]}\n"
        )
    return "\n".join(chunks)[:24000], len(entries)


async def _extract_facts(user_id: str) -> list[dict]:
    corpus, entry_count = await _gather_corpus(user_id)
    if entry_count == 0:
        return []
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"facts_{user_id}_{int(_now().timestamp())}",
        system_message=FACT_SYSTEM,
    ).with_model("anthropic", "claude-sonnet-4-6")
    try:
        reply = await chat.send_message(UserMessage(text=f"=== ARCHIVE ({entry_count} entries) ===\n{corpus}"))
        reply_text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM fact extraction failed: {exc!s}") from exc

    parsed = _extract_json(reply_text)
    if not isinstance(parsed, list):
        return []
    facts: list[dict] = []
    for raw in parsed[:MAX_FACTS_IN_PROMPT]:
        if not isinstance(raw, dict) or not raw.get("fact"):
            continue
        facts.append({
            "fact_id": f"fact_{uuid.uuid4().hex[:10]}",
            "fact": str(raw["fact"])[:280],
            "kind": str(raw.get("kind", "other"))[:32],
            "source": "archive",
            "source_entry_id": raw.get("source_entry_id") if isinstance(raw.get("source_entry_id"), str) else None,
            "created_at": _now_iso(),
        })
    return facts


async def get_or_refresh_facts(user_id: str) -> list[dict]:
    """Returns the cached fact-pack, regenerating only when the archive has
    grown by REFRESH_FACTS_AFTER_NEW_ENTRIES since last extraction."""
    entry_count = await db.entries.count_documents({"user_id": user_id})
    state = await db.memory_state.find_one({"user_id": user_id}, {"_id": 0}) or {}
    last_count = int(state.get("facts_entry_count", -1))

    stale = (
        last_count < 0
        or (entry_count - last_count) >= REFRESH_FACTS_AFTER_NEW_ENTRIES
        or entry_count < last_count
    )

    if stale and entry_count > 0:
        facts = await _extract_facts(user_id)
        # Keep phrases/beliefs the Quick-replies brain learned from twin chats.
        await db.memory_facts.delete_many({
            "user_id": user_id,
            "source": {"$nin": ["voice_council"]},
        })
        if facts:
            await db.memory_facts.insert_many(
                [{**f, "user_id": user_id} for f in facts]
            )
        await db.memory_state.update_one(
            {"user_id": user_id},
            {"$set": {"facts_entry_count": entry_count, "facts_updated_at": _now_iso()}},
            upsert=True,
        )

    cursor = db.memory_facts.find({"user_id": user_id}, {"_id": 0}).limit(MAX_FACTS_IN_PROMPT)
    return await cursor.to_list(length=MAX_FACTS_IN_PROMPT)


# ---------------- Episodic summaries ----------------
EPISODE_SYSTEM = """You are a journal keeper. Summarise this conversation between the user and their own digital twin in 2-3 short sentences. Focus on what was learned, what the user revealed about themselves, or any commitments they made. Refer to the user as 'they'.

Return ONLY plain text — no JSON, no markdown headers, no preface. Just the summary."""


async def maybe_summarise_episode(user_id: str, conversation_id: str) -> Optional[str]:
    """Called from twin/message AFTER a turn is saved. If the conversation has
    grown past the threshold since the last episode, summarise + truncate the
    in-memory history pointer. Idempotent."""
    conv = await db.conversations.find_one(
        {"conversation_id": conversation_id, "user_id": user_id}, {"_id": 0}
    )
    if not conv:
        return None
    msgs = conv.get("messages") or []
    summarised_through = int(conv.get("summarised_through", 0))
    new_count = len(msgs) - summarised_through
    if new_count < EPISODE_THRESHOLD_MESSAGES:
        return None

    turns = msgs[summarised_through:]
    transcript = "\n".join(
        f"{m.get('role','user').upper()}: {m.get('content','')[:1500]}" for m in turns
    )

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"episode_{conversation_id}_{int(_now().timestamp())}",
        system_message=EPISODE_SYSTEM,
    ).with_model("anthropic", "claude-sonnet-4-6")
    try:
        reply = await chat.send_message(UserMessage(text=transcript[:14000]))
        summary = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception:  # noqa: BLE001
        return None  # best-effort; never block the chat

    summary = (summary or "").strip()[:1200]
    if not summary:
        return None

    await db.memory_episodes.insert_one({
        "episode_id": f"ep_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "conversation_id": conversation_id,
        "summary": summary,
        "message_span": [summarised_through, len(msgs)],
        "created_at": _now_iso(),
    })
    await db.conversations.update_one(
        {"conversation_id": conversation_id, "user_id": user_id},
        {"$set": {"summarised_through": len(msgs)}},
    )
    return summary


async def get_recent_episodes(user_id: str, limit: int = MAX_EPISODES_IN_PROMPT) -> list[dict]:
    cursor = (
        db.memory_episodes.find({"user_id": user_id}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


# ---------------- Build the memory pack for the twin ----------------
async def build_memory_pack(user_id: str, query_hint: str = "") -> dict:
    """Returns {facts:[], episodes:[]} ready to be inserted into the twin's
    system prompt. The query_hint is currently used only by /archive retrieval
    (twin.py); facts + episodes are static per user."""
    facts = await get_or_refresh_facts(user_id)
    episodes = await get_recent_episodes(user_id)
    return {"facts": facts, "episodes": episodes}


def format_memory_pack_for_prompt(pack: dict) -> str:
    facts = pack.get("facts") or []
    episodes = pack.get("episodes") or []
    parts: list[str] = []
    if facts:
        lines = [f"- {f['fact']}" for f in facts[:MAX_FACTS_IN_PROMPT]]
        parts.append("STABLE FACTS ABOUT YOU (don't contradict these):\n" + "\n".join(lines))
    if episodes:
        ep_lines = []
        for ep in episodes[:MAX_EPISODES_IN_PROMPT]:
            ts = (ep.get("created_at") or "")[:10]
            ep_lines.append(f"- [{ts}] {ep.get('summary','')}")
        parts.append("RECENT CONVERSATIONS WITH YOUR LOVED ONES (most recent first):\n" + "\n".join(ep_lines))
    return "\n\n".join(parts)


# ---------------- Endpoints (debug + UI surface) ----------------
@router.get("/facts")
async def list_facts(user: dict = Depends(get_current_user)):
    facts = await get_or_refresh_facts(user["user_id"])
    return {"facts": facts, "count": len(facts)}


@router.get("/episodes")
async def list_episodes(user: dict = Depends(get_current_user), limit: int = 30):
    limit = max(1, min(int(limit), 100))
    cursor = (
        db.memory_episodes.find({"user_id": user["user_id"]}, {"_id": 0})
        .sort("created_at", -1)
        .limit(limit)
    )
    items = await cursor.to_list(length=limit)
    return {"episodes": items, "count": len(items)}


class RebuildReq(BaseModel):
    pass


@router.post("/facts/rebuild")
async def rebuild_facts(user: dict = Depends(get_current_user)):
    """Force-regenerate identity facts from the current archive."""
    facts = await _extract_facts(user["user_id"])
    await db.memory_facts.delete_many({
        "user_id": user["user_id"],
        "source": {"$nin": ["voice_council"]},
    })
    if facts:
        await db.memory_facts.insert_many(
            [{**f, "user_id": user["user_id"]} for f in facts]
        )
    entry_count = await db.entries.count_documents({"user_id": user["user_id"]})
    await db.memory_state.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"facts_entry_count": entry_count, "facts_updated_at": _now_iso()}},
        upsert=True,
    )
    return {"facts": facts, "count": len(facts)}


@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: str, user: dict = Depends(get_current_user)):
    """User can prune a wrong fact — the twin will stop using it immediately."""
    res = await db.memory_facts.delete_one(
        {"fact_id": fact_id, "user_id": user["user_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"ok": True}



# ==================================================================
# Semantic search — user's archive indexed via their configured
# embeddings provider (see /api/providers, subsystem "embeddings").
# Falls back to keyword search when no provider is enabled.
# ==================================================================
import logging as _sem_logging  # noqa: E402

from fastapi import BackgroundTasks  # noqa: E402
from pydantic import Field  # noqa: E402

from services import embeddings as _emb  # noqa: E402

_sem_log = _sem_logging.getLogger("memory.semantic")

_SEM_MAX_BATCH = 100
_SEM_MIN_SCORE = 0.20


def _sem_entry_text(entry: dict) -> str:
    """Build the string we embed. Metadata is part of the vector because
    retrieval is dramatically stronger when tags/type/title are included."""
    bits: list[str] = []
    if entry.get("type"):
        bits.append(f"[{entry['type']}]")
    if entry.get("title"):
        bits.append(entry["title"])
    if entry.get("tags"):
        tags = entry["tags"]
        if isinstance(tags, list):
            bits.append("tags: " + ", ".join(str(t) for t in tags))
        else:
            bits.append(f"tags: {tags}")
    if entry.get("content"):
        bits.append(str(entry["content"]))
    return "\n".join(bits).strip()


class SemSearchReq(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=6, ge=1, le=25)


class SemEmbedReq(BaseModel):
    force: bool = False


@router.get("/search/status")
async def sem_status(user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    cfg = await _emb.get_config(uid)
    total = await db.entries.count_documents({"user_id": uid})
    if cfg is None:
        return {"has_provider": False, "total_entries": total, "embedded": 0, "model": None}
    embedded = await db.archive_embeddings.count_documents(
        {"user_id": uid, "embedding_model": cfg["model"]}
    )
    return {
        "has_provider": True,
        "provider_type": cfg.get("provider_type", "openai_compat"),
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "total_entries": total,
        "embedded": embedded,
        "pending": max(0, total - embedded),
    }


async def _sem_run_job(user_id: str, force: bool = False) -> dict:
    cfg = await _emb.get_config(user_id)
    if cfg is None:
        return {"embedded": 0, "skipped": 0, "reason": "no_provider"}
    model = cfg["model"]

    entries = await db.entries.find(
        {"user_id": user_id},
        {"_id": 0, "entry_id": 1, "type": 1, "title": 1, "content": 1, "tags": 1},
    ).to_list(length=5000)
    if not entries:
        return {"embedded": 0, "skipped": 0}

    existing: dict[str, str] = {}
    async for doc in db.archive_embeddings.find(
        {"user_id": user_id, "embedding_model": model},
        {"_id": 0, "entry_id": 1, "content_sha": 1},
    ):
        existing[doc["entry_id"]] = doc["content_sha"]

    pending: list[tuple[str, str, str]] = []
    for e in entries:
        text = _sem_entry_text(e)
        if not text:
            continue
        sha = _emb.content_sha(text, model)
        if not force and existing.get(e["entry_id"]) == sha:
            continue
        pending.append((e["entry_id"], text, sha))

    if not pending:
        return {"embedded": 0, "skipped": len(entries)}

    embedded_count = 0
    for i in range(0, len(pending), _SEM_MAX_BATCH):
        chunk = pending[i:i + _SEM_MAX_BATCH]
        try:
            vectors = await _emb.embed_texts(user_id, [c[1] for c in chunk])
        except _emb.NoProviderError:
            break
        except Exception as exc:  # noqa: BLE001
            _sem_log.exception("embed job failed at chunk %d for user=%s: %s", i, user_id, exc)
            return {"embedded": embedded_count, "skipped": 0, "error": str(exc)[:200]}
        for (entry_id, _text, sha), vec in zip(chunk, vectors):
            await db.archive_embeddings.update_one(
                {"user_id": user_id, "entry_id": entry_id, "embedding_model": model},
                {"$set": {
                    "user_id": user_id, "entry_id": entry_id, "embedding_model": model,
                    "embedding_dims": len(vec), "content_sha": sha, "vector": vec,
                    "embedded_at": _now_iso(),
                }},
                upsert=True,
            )
            embedded_count += 1
    return {"embedded": embedded_count, "skipped": len(entries) - embedded_count}


@router.post("/search/embed")
async def sem_embed(
    payload: SemEmbedReq,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    if not await _emb.has_provider(user["user_id"]):
        raise HTTPException(
            status_code=400,
            detail="No embeddings provider configured. Set one up in Local AI settings first.",
        )
    background.add_task(_sem_run_job, user["user_id"], payload.force)
    return {"ok": True, "queued": True}


@router.post("/search/embed/sync")
async def sem_embed_sync(payload: SemEmbedReq, user: dict = Depends(get_current_user)):
    if not await _emb.has_provider(user["user_id"]):
        raise HTTPException(status_code=400, detail="No embeddings provider configured.")
    return await _sem_run_job(user["user_id"], payload.force)


async def _sem_keyword_fallback(uid: str, query: str, limit: int, reason: str) -> dict:
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    rows = await db.entries.find(
        {"user_id": uid,
         "$or": [
             {"title": {"$regex": pattern}},
             {"content": {"$regex": pattern}},
             {"tags": {"$regex": pattern}},
         ]},
        {"_id": 0, "entry_id": 1, "type": 1, "title": 1, "content": 1, "created_at": 1, "tags": 1},
    ).sort("created_at", -1).limit(limit).to_list(length=limit)
    return {"mode": "keyword", "reason": reason, "results": rows}


@router.post("/search")
async def sem_search(payload: SemSearchReq, user: dict = Depends(get_current_user)):
    uid = user["user_id"]
    cfg = await _emb.get_config(uid)
    if cfg is None:
        return await _sem_keyword_fallback(uid, payload.query, payload.limit, "no_provider")
    try:
        vecs = await _emb.embed_texts(uid, [payload.query])
    except Exception as exc:  # noqa: BLE001
        _sem_log.warning("query embed failed for %s: %s", uid, exc)
        return await _sem_keyword_fallback(uid, payload.query, payload.limit, "embed_failed")
    q_vec = vecs[0]

    docs = await db.archive_embeddings.find(
        {"user_id": uid, "embedding_model": cfg["model"]},
        {"_id": 0, "entry_id": 1, "vector": 1},
    ).to_list(length=5000)
    if not docs:
        return await _sem_keyword_fallback(uid, payload.query, payload.limit, "no_index")

    scores = _emb.cosine_scores(q_vec, [d["vector"] for d in docs])
    ranked = sorted(zip(scores.tolist(), docs), key=lambda p: p[0], reverse=True)
    top = [(s, d["entry_id"]) for s, d in ranked if s >= _SEM_MIN_SCORE][: payload.limit]
    if not top:
        return await _sem_keyword_fallback(uid, payload.query, payload.limit, "no_matches")

    ids = [t[1] for t in top]
    id_to_score = {t[1]: t[0] for t in top}
    entries = await db.entries.find(
        {"user_id": uid, "entry_id": {"$in": ids}},
        {"_id": 0, "entry_id": 1, "type": 1, "title": 1, "content": 1, "created_at": 1, "tags": 1},
    ).to_list(length=len(ids))
    entries.sort(key=lambda e: id_to_score.get(e["entry_id"], 0), reverse=True)
    for e in entries:
        e["score"] = round(id_to_score.get(e["entry_id"], 0), 4)
    return {"mode": "semantic", "results": entries, "model": cfg["model"]}


async def semantic_lookup(user_id: str, query: str, limit: int = 6) -> tuple[str, list[dict]]:
    """Twin-facing helper. Returns (mode, entries) where mode is 'semantic'
    or 'keyword'. Never raises — falls back all the way to []."""
    try:
        result = await sem_search(
            SemSearchReq(query=query, limit=limit),
            user={"user_id": user_id},
        )
        return result.get("mode", "keyword"), result.get("results") or []
    except HTTPException:
        return "keyword", []
    except Exception as exc:  # noqa: BLE001
        _sem_log.warning("semantic_lookup failed for %s: %s", user_id, exc)
        return "keyword", []

