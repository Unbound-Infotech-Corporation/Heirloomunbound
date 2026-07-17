"""Public Heir Portal — read-only access for an heir using their release_token.

After the owner's release workflow has fired (date or inactivity trigger), the
heir receives a portal token (held in the heirs.release_token field). This
router authenticates via that token alone; the heir has read-only access to:
- The owner's name + final message (the heir.note)
- All sealed letters whose trigger has fired
- The archive entries (read-only)
- A high-fidelity twin chat (same personality + memory pack + fence as the
  owner twin — no tools/skills) plus optional cloned-voice TTS.

No POST/PATCH/DELETE on owner data — strictly read-only.
"""
import base64
import io
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db
from routers.memory import build_memory_pack, format_memory_pack_for_prompt
from twin_prompt import build_twin_system, load_personality_blob

router = APIRouter(prefix="/heir-portal", tags=["heir-portal"])


async def get_released_heir(token: str) -> dict:
    if not token or not token.startswith("hr_tok_"):
        raise HTTPException(status_code=401, detail="Invalid heir token")
    heir = await db.heirs.find_one(
        {"release_token": token, "released": True}, {"_id": 0}
    )
    if not heir:
        raise HTTPException(status_code=401, detail="Invalid or revoked heir token")
    return heir


async def _owner(heir: dict) -> dict:
    user = await db.users.find_one({"user_id": heir["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Owner not found")
    return user


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _letter_unlocked(letter: dict, heir: dict, now: datetime) -> bool:
    """A sealed letter is visible to the heir iff it's been sealed AND its
    trigger has fired."""
    if not letter.get("sealed"):
        return False
    rid = letter.get("recipient_heir_id")
    if rid and rid != heir["heir_id"]:
        return False

    trig = letter.get("trigger", "on_release")
    if trig == "on_release":
        return True
    if trig == "on_date":
        dd = letter.get("delivery_date")
        if not dd:
            return False
        try:
            target = datetime.fromisoformat(dd)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return now >= target
        except Exception:
            return False
    if trig == "on_age":
        # Best-effort: unlock after release until we collect heir birth dates.
        return True
    return False


async def _archive_blob(user_id: str, query_hint: str = "", limit_recent: int = 20, limit_relevant: int = 40) -> str:
    """Same retrieval shape as the owner twin — recent + keyword matches."""
    docs: dict[str, dict] = {}
    recent = await db.entries.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(limit_recent).to_list(length=limit_recent)
    for e in recent:
        docs[e["entry_id"]] = e

    if query_hint:
        import re as _re
        STOP = {"the","a","an","of","in","on","to","for","was","is","are","what","where","when","who","why","how","my","me","i","did","do","does","that","this","at","with","and","you","your","them","their","about"}
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
    return "\n".join(
        f"[{e['type'].upper()}] {e['title']}\n{e['content']}\n" for e in docs.values()
    )


@router.get("/{token}")
async def portal_summary(token: str):
    heir = await get_released_heir(token)
    owner = await _owner(heir)
    now = _now()
    cursor = db.sealed_letters.find({"user_id": owner["user_id"]}, {"_id": 0})
    letters = await cursor.to_list(length=500)
    visible = [l for l in letters if _letter_unlocked(l, heir, now)]
    total_entries = await db.entries.count_documents({"user_id": owner["user_id"]})
    voice_ready = bool(
        (await db.elevenlabs_settings.find_one({"user_id": owner["user_id"]}, {"_id": 0}) or {}).get("voice_id")
        or owner.get("elevenlabs_voice_id")
    )

    return {
        "heir": {
            "heir_id": heir["heir_id"],
            "name": heir.get("name"),
            "relationship": heir.get("relationship", ""),
            "note": heir.get("note", ""),
            "released_at": heir.get("released_at"),
        },
        "owner": {
            "name": owner.get("name", ""),
            "picture": owner.get("picture", ""),
            "preferred_name": owner.get("preferred_name") or owner.get("name", ""),
        },
        "letters_available": len(visible),
        "entries_available": total_entries,
        "voice_available": voice_ready,
        "fidelity": "full",  # signals to the UI that heir twin matches owner fidelity
    }


@router.get("/{token}/letters")
async def portal_letters(token: str):
    heir = await get_released_heir(token)
    owner_id = heir["user_id"]
    now = _now()
    cursor = db.sealed_letters.find({"user_id": owner_id}, {"_id": 0}).sort("created_at", -1)
    letters = await cursor.to_list(length=500)
    out = []
    for l in letters:
        if _letter_unlocked(l, heir, now):
            if not l.get("delivered"):
                await db.sealed_letters.update_one(
                    {"letter_id": l["letter_id"]},
                    {"$set": {"delivered": True, "delivered_at": now.isoformat()}},
                )
                l["delivered"] = True
                l["delivered_at"] = now.isoformat()
            out.append({
                "letter_id": l["letter_id"],
                "title": l.get("title"),
                "body": l.get("body"),
                "trigger": l.get("trigger"),
                "delivery_date": l.get("delivery_date"),
                "recipient_name": l.get("recipient_name"),
                "created_at": l.get("created_at"),
                "delivered_at": l.get("delivered_at"),
            })
    return {"letters": out}


@router.get("/{token}/entries")
async def portal_entries(token: str, limit: int = 100, offset: int = 0):
    heir = await get_released_heir(token)
    owner_id = heir["user_id"]
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    cursor = db.entries.find(
        {"user_id": owner_id},
        {"_id": 0, "user_id": 0},
    ).sort("created_at", -1).skip(offset).limit(limit)
    items = await cursor.to_list(length=limit)
    total = await db.entries.count_documents({"user_id": owner_id})
    return {"entries": items, "total": total, "offset": offset, "limit": limit}


class HeirChatReq(BaseModel):
    message: str
    session_id: Optional[str] = None


@router.post("/{token}/twin/chat")
async def portal_twin_chat(token: str, payload: HeirChatReq):
    """High-fidelity chat with the owner's Twin — personality + memory pack + fence."""
    heir = await get_released_heir(token)
    owner = await _owner(heir)

    text = (payload.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="Message too long")
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="Twin is offline (LLM key not configured)")

    archive = await _archive_blob(owner["user_id"], query_hint=text)
    memory_pack = await build_memory_pack(owner["user_id"], query_hint=text)
    memory_blob = format_memory_pack_for_prompt(memory_pack)
    personality_blob = await load_personality_blob(db, owner["user_id"])
    safe_topics = list(owner.get("safe_topics") or [])

    system = build_twin_system(
        owner.get("preferred_name") or owner.get("name", ""),
        memory_blob=memory_blob,
        archive_blob=archive,
        safe_topics=safe_topics,
        personality_blob=personality_blob,
        heir_mode=True,
        heir_name=heir.get("name"),
        heir_relationship=heir.get("relationship"),
    )

    session_id = payload.session_id or f"heir_{heir['heir_id']}"

    # Replay prior heir turns so the twin remembers the conversation.
    prior = await db.conversations.find_one(
        {"conversation_id": session_id, "user_id": owner["user_id"]}, {"_id": 0}
    )
    initial_messages = [{"role": "system", "content": system}]
    if prior:
        for m in (prior.get("messages") or [])[-20:]:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                initial_messages.append({"role": m["role"], "content": m["content"]})

    chat = (
        LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id,
            system_message=system,
            initial_messages=initial_messages,
        ).with_model("anthropic", "claude-sonnet-4-6")
    )
    try:
        reply = await chat.send_message(UserMessage(text=text))
        reply_text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Twin reply failed: {exc!s}") from exc

    now_iso = datetime.now(timezone.utc).isoformat()
    await db.conversations.update_one(
        {"conversation_id": session_id, "user_id": owner["user_id"]},
        {
            "$setOnInsert": {
                "conversation_id": session_id,
                "user_id": owner["user_id"],
                "kind": "heir_portal",
                "heir_id": heir["heir_id"],
                "created_at": now_iso,
            },
            "$set": {"updated_at": now_iso},
            "$push": {"messages": {"$each": [
                {"role": "user", "content": text, "ts": now_iso},
                {"role": "assistant", "content": reply_text, "ts": now_iso},
            ]}},
        },
        upsert=True,
    )

    return {
        "reply": reply_text,
        "session_id": session_id,
        "fidelity": "full",
        "used_personality": bool(personality_blob),
        "used_memory_pack": bool(memory_blob),
    }


class HeirSpeakReq(BaseModel):
    text: str


@router.post("/{token}/twin/speak")
async def portal_twin_speak(token: str, payload: HeirSpeakReq):
    """Speak a twin reply in the owner's cloned voice (ElevenLabs) when available."""
    heir = await get_released_heir(token)
    owner = await _owner(heir)
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")
    if len(text) > 5000:
        text = text[:5000]

    # Resolve ElevenLabs key + voice the same way voice_clone does, without auth dependency.
    settings = await db.elevenlabs_settings.find_one({"user_id": owner["user_id"]}, {"_id": 0}) or {}
    key = (
        settings.get("api_key")
        or owner.get("elevenlabs_api_key")
        or __import__("os").environ.get("ELEVENLABS_API_KEY", "")
    )
    voice_id = settings.get("voice_id") or owner.get("elevenlabs_voice_id")
    if not key or not voice_id:
        raise HTTPException(status_code=400, detail="Owner voice clone not configured")

    try:
        from elevenlabs.client import AsyncElevenLabs
        client = AsyncElevenLabs(api_key=key)
        lang_pref = (owner.get("tts_language") or "auto").strip().lower()
        convert_kwargs = dict(
            voice_id=voice_id,
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        if lang_pref and lang_pref != "auto" and len(lang_pref) <= 8:
            convert_kwargs["language_code"] = lang_pref
        stream = client.text_to_speech.convert(**convert_kwargs)
        audio = b""
        async for chunk in stream:
            if chunk:
                audio += chunk
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"TTS failed: {exc!s}") from exc

    return {
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "mime": "audio/mpeg",
    }
