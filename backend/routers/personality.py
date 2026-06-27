"""Structured Personality Profile.

Closes the "what does the twin actually know about me?" gap that
HereAfter AI, Eternos, and Replika 2026 all expose visibly.

Generates a JSON portrait of the user from their archive:
  - Big Five (OCEAN) traits 0-100 with a one-line reason each
  - Top values
  - Voice tone description + signature phrases
  - Life themes
  - Key relationships (extracted from archive mentions)
  - Generated_at + entry_count_at_generation for staleness checks
"""
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db, get_current_user

router = APIRouter(prefix="/personality", tags=["personality"])

STALE_AFTER_HOURS = 24 * 7  # auto-refresh after one week if entry count moved


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first {...} JSON object out of an LLM reply, tolerating fences."""
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _empty_profile() -> dict:
    return {
        "bigfive": {},
        "top_values": [],
        "voice_tone": {"description": "", "signature_phrases": []},
        "life_themes": [],
        "key_relationships": [],
        "summary": "",
    }


async def _gather_corpus(user_id: str) -> tuple[str, int]:
    cursor = db.entries.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(300)
    entries = await cursor.to_list(length=300)
    chunks = []
    for e in entries:
        chunks.append(
            f"[{e.get('type','').upper()}] {e.get('title','')}\n{(e.get('content') or '')[:1200]}\n"
        )
    return "\n".join(chunks), len(entries)


SYSTEM_PROMPT = """You are a personality analyst building a portrait of a person from their archive of memories, stories, values, advice, and quotes.

Return ONLY a valid JSON object — no prose, no markdown fences — with EXACTLY this shape:

{
  "bigfive": {
    "openness":          {"score": <int 0-100>, "reason": "<one short clause>"},
    "conscientiousness": {"score": <int 0-100>, "reason": "<one short clause>"},
    "extraversion":      {"score": <int 0-100>, "reason": "<one short clause>"},
    "agreeableness":     {"score": <int 0-100>, "reason": "<one short clause>"},
    "neuroticism":       {"score": <int 0-100>, "reason": "<one short clause>"}
  },
  "top_values": ["<value1>", "<value2>", "<value3>", "<value4>", "<value5>"],
  "voice_tone": {
    "description": "<3-5 sentences describing how this person speaks — vocabulary, rhythm, humor, what they avoid>",
    "signature_phrases": ["<phrase1>", "<phrase2>", "<phrase3>"]
  },
  "life_themes": ["<theme1>", "<theme2>", "<theme3>", "<theme4>"],
  "key_relationships": [
    {"name": "<name>", "role": "<son/daughter/partner/friend/etc>", "note": "<one short clause about them>"}
  ],
  "summary": "<3-4 sentence portrait of this person in second person, addressed to them. e.g. 'You are a...'>"
}

Be honest. If the archive is sparse, set scores to 50 and reasons to "not enough signal yet". Never invent facts about specific people the archive doesn't mention.
"""


async def _generate_profile(user_id: str, user_name: str) -> dict:
    corpus, entry_count = await _gather_corpus(user_id)
    if entry_count == 0:
        empty = _empty_profile()
        empty["summary"] = "Your archive is empty. Once you've captured a few memories, values, or stories, your twin will have a face here."
        return {**empty, "entry_count": 0, "generated_at": _now_iso()}

    truncated = corpus[:24000]
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"personality_{user_id}_{int(_now().timestamp())}",
        system_message=SYSTEM_PROMPT,
    ).with_model("anthropic", "claude-sonnet-4-6")

    user_msg = f"Analyse the archive of {user_name or 'this person'} below and return the JSON portrait.\n\n=== ARCHIVE ({entry_count} entries) ===\n{truncated}"
    try:
        reply = await chat.send_message(UserMessage(text=user_msg))
        reply_text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc!s}") from exc

    parsed = _extract_json(reply_text) or _empty_profile()
    parsed["entry_count"] = entry_count
    parsed["generated_at"] = _now_iso()
    return parsed


class RefreshReq(BaseModel):
    force: bool = False


@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    """Return cached profile if fresh, else generate."""
    cached = await db.personality_profiles.find_one({"user_id": user["user_id"]}, {"_id": 0})
    entry_count = await db.entries.count_documents({"user_id": user["user_id"]})

    fresh = False
    if cached:
        try:
            gen_at = datetime.fromisoformat(cached.get("generated_at", ""))
            if gen_at.tzinfo is None:
                gen_at = gen_at.replace(tzinfo=timezone.utc)
            hours = (_now() - gen_at).total_seconds() / 3600
            if hours < STALE_AFTER_HOURS and cached.get("entry_count", 0) == entry_count:
                fresh = True
        except Exception:  # noqa: BLE001
            pass

    if cached and fresh:
        cached["fresh"] = True
        return cached

    new_profile = await _generate_profile(user["user_id"], user.get("name", ""))
    new_profile["user_id"] = user["user_id"]
    new_profile["fresh"] = True

    await db.personality_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": new_profile},
        upsert=True,
    )
    new_profile.pop("_id", None)
    return new_profile


@router.post("/refresh")
async def refresh_profile(user: dict = Depends(get_current_user)):
    new_profile = await _generate_profile(user["user_id"], user.get("name", ""))
    new_profile["user_id"] = user["user_id"]
    new_profile["fresh"] = True
    await db.personality_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": new_profile},
        upsert=True,
    )
    new_profile.pop("_id", None)
    return new_profile
