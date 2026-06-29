"""Local Vault — server-side endpoints for the desktop app's daily compaction.

The desktop app stores ALL communication locally (text + voice). Once per day
(or on-demand), it ships that day's transcript to /vault/compact, which calls
Claude to extract stable facts + a human-readable summary. Those facts then
flow up to /vault/facts/ingest where they're persisted in `memory_facts` —
the same collection the Twin's system prompt reads from. So things you SAY
to your twin actually become things your twin KNOWS, persistently, across
new conversations.

All endpoints are device-token authed (same as the rest of /desktop/*).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import EMERGENT_LLM_KEY, db
from routers.companion import get_device_user

router = APIRouter(prefix="/vault", tags=["vault"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


COMPACTION_SYSTEM = """You are reviewing a day's worth of conversation between a user
and their digital twin. Extract durable, useful information that the twin should
remember about the user in future conversations.

Return ONLY valid JSON with this exact shape:
{
  "facts": [
    {"fact": "<one concrete sentence, present-tense>", "kind": "<family|place|career|belief|milestone|phrase|interest|skill|relationship|story|other>"}
  ],
  "summary": "<2-4 sentence human-readable journal entry for this day>",
  "themes": ["<short theme labels>"]
}

Rules:
- Facts must be STABLE — true a year from now. Skip transient emotions ("felt tired").
- Skip anything the twin already said (we only learn from the USER's turns).
- If the user revealed nothing durable, return facts: [].
- Quality over quantity — 0 to ~20 facts is healthy. Never more than 40.
- Never invent details that weren't said.
"""


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    ts: Optional[str] = None
    kind: Optional[str] = None  # "chat" | "voice"


class CompactReq(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    turns: List[Turn]


class CompactResp(BaseModel):
    facts: List[dict]
    summary: str
    themes: List[str]
    turns_seen: int


@router.post("/compact", response_model=CompactResp)
async def vault_compact(body: CompactReq, ctx: dict = Depends(get_device_user)):
    """Run Claude on a day's transcript and return extracted facts + summary.

    The desktop app calls this nightly. Stateless — no database writes here;
    the desktop then chooses what to do with the result (typically: pipe the
    facts into /vault/facts/ingest, append the summary to the local journal,
    apply its tier policy to the raw turns).
    """
    if not body.turns:
        return CompactResp(facts=[], summary="(no conversation today)", themes=[], turns_seen=0)

    # Cap the transcript so we never blow context — keep the most recent 240 turns
    capped = body.turns[-240:]
    transcript = "\n".join(
        f"[{t.role.upper()}] {(t.text or '')[:1500]}" for t in capped if t.text
    )[:30000]

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"vault_compact_{ctx['user']['user_id']}_{body.date}",
        system_message=COMPACTION_SYSTEM,
    ).with_model("anthropic", "claude-sonnet-4-6")

    try:
        reply = await chat.send_message(
            UserMessage(text=f"=== {body.date} ({len(capped)} turns) ===\n{transcript}")
        )
        reply_text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Compaction LLM failed: {exc!s}") from exc

    parsed = _extract_json(reply_text)
    if not isinstance(parsed, dict):
        # Be forgiving: if the LLM gave plain prose, still return something usable
        return CompactResp(
            facts=[],
            summary=reply_text.strip()[:1200] or "(no summary)",
            themes=[],
            turns_seen=len(capped),
        )

    raw_facts = parsed.get("facts") or []
    cleaned: list[dict] = []
    for f in raw_facts[:40]:
        if not isinstance(f, dict) or not f.get("fact"):
            continue
        cleaned.append({
            "fact": str(f["fact"])[:280].strip(),
            "kind": str(f.get("kind", "other"))[:32],
        })

    return CompactResp(
        facts=cleaned,
        summary=(parsed.get("summary") or "").strip()[:1200],
        themes=[str(t)[:48] for t in (parsed.get("themes") or [])[:8] if t],
        turns_seen=len(capped),
    )


class IngestReq(BaseModel):
    facts: List[dict]
    date: Optional[str] = None


@router.post("/facts/ingest")
async def vault_ingest_facts(body: IngestReq, ctx: dict = Depends(get_device_user)):
    """Persist compaction-extracted facts into `memory_facts` so the Twin
    reads them in every future conversation. Idempotent: skips facts that
    already exist verbatim for this user."""
    user_id = ctx["user"]["user_id"]
    if not body.facts:
        return {"inserted": 0, "skipped": 0}

    existing_cursor = db.memory_facts.find(
        {"user_id": user_id, "source": {"$in": ["desktop_compaction", "vault_compaction"]}},
        {"_id": 0, "fact": 1},
    )
    existing = {(r.get("fact") or "").lower().strip() for r in await existing_cursor.to_list(length=10000)}

    docs = []
    skipped = 0
    for f in body.facts[:60]:
        if not isinstance(f, dict):
            skipped += 1
            continue
        text = (f.get("fact") or "").strip()
        if not text:
            skipped += 1
            continue
        if text.lower() in existing:
            skipped += 1
            continue
        existing.add(text.lower())
        docs.append({
            "fact_id": f"fact_{uuid.uuid4().hex[:10]}",
            "user_id": user_id,
            "fact": text[:280],
            "kind": str(f.get("kind", "other"))[:32],
            "source": "desktop_compaction",
            "source_date": body.date,
            "created_at": _now_iso(),
        })

    if docs:
        await db.memory_facts.insert_many(docs)
    return {"inserted": len(docs), "skipped": skipped}


@router.get("/status")
async def vault_status(ctx: dict = Depends(get_device_user)):
    """Cloud-side counts so the desktop app can show the user how much their
    twin actually knows, post-compaction."""
    user_id = ctx["user"]["user_id"]
    total_facts = await db.memory_facts.count_documents({"user_id": user_id})
    vault_facts = await db.memory_facts.count_documents({
        "user_id": user_id,
        "source": "desktop_compaction",
    })
    total_entries = await db.entries.count_documents({"user_id": user_id})
    last_fact = await db.memory_facts.find_one(
        {"user_id": user_id, "source": "desktop_compaction"},
        {"_id": 0, "created_at": 1, "source_date": 1},
        sort=[("created_at", -1)],
    )
    return {
        "total_facts": total_facts,
        "facts_from_vault": vault_facts,
        "total_archive_entries": total_entries,
        "last_compaction_at": (last_fact or {}).get("created_at"),
        "last_compaction_date": (last_fact or {}).get("source_date"),
    }
