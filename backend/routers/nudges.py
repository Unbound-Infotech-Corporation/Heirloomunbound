"""Proactive Nudges from your Twin.

Closes the "what can it do for me, unprompted?" gap (Replika's 2026 killer feature).
Once per day, the twin generates a short, personal nudge — drawn from the
archive — that invites action: a journaling prompt, a memory to revisit, or a
small task. Stored per (user_id, UTC date) for idempotency. The user can act
on it (which deep-links to /interviewer with the prompt baked in) or dismiss it.
"""
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db, get_current_user

router = APIRouter(prefix="/nudges", tags=["nudges"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_key() -> str:
    return _now().strftime("%Y-%m-%d")


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


SYSTEM_PROMPT = """You are the digital twin of the user. Write a single nudge — a kind, personal, specific prompt drawn from their archive — that invites them to capture a small piece of themselves today.

Return ONLY valid JSON, no prose:

{
  "title": "<5-8 word headline, e.g. 'A question about your dad'>",
  "body": "<2-3 sentences. Speak in second person, warmly. Reference something specific from the archive when you can. End with a clear question.>",
  "action_type": "<one of: 'journal' | 'memory' | 'value' | 'advice'>",
  "action_prompt": "<the exact question the user will answer when they click 'Answer this'. Should be specific.>"
}

Don't repeat yourself. Don't be saccharine. Be precise — a good nudge feels written for this person, not a horoscope. If the archive is empty, ask for an early-life memory."""


async def _gather_context(user_id: str) -> tuple[str, list[str]]:
    cursor = db.entries.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(80)
    entries = await cursor.to_list(length=80)
    if not entries:
        return "", []
    titles_used = []
    chunks = []
    # Prior nudges (last 14 days) so we don't repeat ourselves
    last14 = await db.nudges.find(
        {"user_id": user_id},
        {"_id": 0, "title": 1, "action_prompt": 1, "date_key": 1},
    ).sort("date_key", -1).limit(14).to_list(length=14)
    titles_used = [f"{n.get('title')}: {n.get('action_prompt','')}" for n in last14]

    for e in entries:
        chunks.append(
            f"[{e.get('type','').upper()}] {e.get('title','')}\n{(e.get('content') or '')[:600]}\n"
        )
    return "\n".join(chunks)[:16000], titles_used


async def _generate_nudge(user_id: str, user_name: str) -> dict:
    corpus, recent_nudges = await _gather_context(user_id)
    prompt = (
        f"User name: {user_name or 'friend'}\n"
        f"Today: {_today_key()}\n\n"
        f"Recent nudges to NOT repeat:\n{json.dumps(recent_nudges, indent=2)}\n\n"
        f"Archive snapshot:\n{corpus or '(empty)'}"
    )
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"nudge_{user_id}_{_today_key()}",
        system_message=SYSTEM_PROMPT,
    ).with_model("anthropic", "claude-sonnet-4-6")
    try:
        reply = await chat.send_message(UserMessage(text=prompt))
        reply_text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc!s}") from exc

    parsed = _extract_json(reply_text)
    if not parsed or not parsed.get("title") or not parsed.get("body"):
        # Fallback nudge so the UI never breaks
        parsed = {
            "title": "Tell me something small",
            "body": "What's one specific thing from the last few days you don't want to forget? A smell, a word, a moment. Capture it before it slips.",
            "action_type": "memory",
            "action_prompt": "What is one small moment from the last week you don't want to forget?",
        }
    # Clamp action_type to the documented enum so a stray model output never
    # ends up persisted.
    if parsed.get("action_type") not in ("journal", "memory", "value", "advice"):
        parsed["action_type"] = "memory"
    return parsed


@router.get("/today")
async def todays_nudge(user: dict = Depends(get_current_user)):
    date_key = _today_key()
    existing = await db.nudges.find_one(
        {"user_id": user["user_id"], "date_key": date_key}, {"_id": 0}
    )
    if existing:
        return existing

    n = await _generate_nudge(user["user_id"], user.get("name", ""))
    nudge_id = f"nud_{uuid.uuid4().hex[:12]}"
    doc = {
        "nudge_id": nudge_id,
        "user_id": user["user_id"],
        "date_key": date_key,
        **n,
        "status": "open",
        "created_at": _now().isoformat(),
    }
    await db.nudges.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


class StatusUpdate(BaseModel):
    status: str  # "dismissed" | "acted"


@router.patch("/{nudge_id}")
async def update_status(
    nudge_id: str, payload: StatusUpdate, user: dict = Depends(get_current_user)
):
    if payload.status not in ("dismissed", "acted", "open"):
        raise HTTPException(status_code=400, detail="Invalid status")
    res = await db.nudges.update_one(
        {"nudge_id": nudge_id, "user_id": user["user_id"]},
        {"$set": {"status": payload.status, "updated_at": _now().isoformat()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Nudge not found")
    return {"ok": True, "status": payload.status}


@router.get("/history")
async def nudge_history(user: dict = Depends(get_current_user), limit: int = 30):
    cursor = (
        db.nudges.find({"user_id": user["user_id"]}, {"_id": 0})
        .sort("date_key", -1)
        .limit(min(limit, 90))
    )
    return await cursor.to_list(length=limit)
