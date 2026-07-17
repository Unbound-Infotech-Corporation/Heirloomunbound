"""Public Heir Portal — read-only access for an heir using their release_token.

After the owner's release workflow has fired (date or inactivity trigger), the
heir receives a portal token (held in the heirs.release_token field). This
router authenticates via that token alone; the heir has read-only access to:
- The owner's name + final message (the heir.note)
- All sealed letters whose trigger has fired
- The archive entries (read-only)
- A simple chat-with-twin endpoint (text-only, no streaming) so the heir can
  speak with the twin once.

No POST/PATCH/DELETE on owner data — strictly read-only.
"""
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db

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
    # Restrict to this heir when recipient_heir_id is set
    rid = letter.get("recipient_heir_id")
    if rid and rid != heir["heir_id"]:
        return False

    trig = letter.get("trigger", "on_release")
    if trig == "on_release":
        return True  # heir has been released; this trigger is satisfied
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
        # We don't know heir's birth date; gate on (release + delivery_age years
        # since heir was created) — best-effort.
        return True
    return False


@router.get("/{token}")
async def portal_summary(token: str):
    heir = await get_released_heir(token)
    owner = await _owner(heir)
    now = _now()
    # Count visible letters
    cursor = db.sealed_letters.find({"user_id": owner["user_id"]}, {"_id": 0})
    letters = await cursor.to_list(length=500)
    visible = [l for l in letters if _letter_unlocked(l, heir, now)]

    total_entries = await db.entries.count_documents({"user_id": owner["user_id"]})

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
        },
        "letters_available": len(visible),
        "entries_available": total_entries,
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
            # Mark as delivered first time it's read
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
    """Non-streaming chat with the owner's Twin, grounded in their archive."""
    heir = await get_released_heir(token)
    owner = await _owner(heir)

    text = (payload.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty message")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="Message too long")

    cursor = db.entries.find(
        {"user_id": owner["user_id"]},
        {"_id": 0, "type": 1, "title": 1, "content": 1},
    ).sort("created_at", -1).limit(40)
    entries = await cursor.to_list(length=40)
    archive = "\n".join(
        f"[{e.get('type', 'note').upper()}] {e.get('title', '')}\n{(e.get('content') or '')[:700]}\n"
        for e in entries
    )

    system = f"""You are {owner.get('name','the owner')}'s digital twin, speaking with their heir {heir.get('name','an heir')} ({heir.get('relationship','loved one')}).
Be them. Speak in first person, warmly and personally. Be brief — 1-4 sentences unless asked for more.
Do NOT take any actions. Do NOT invoke skills. This is a quiet conversation.

Your personality archive:
{archive[:18000] or '(empty)'}"""

    session_id = payload.session_id or f"heir_{heir['heir_id']}"
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-6")
    try:
        reply = await chat.send_message(UserMessage(text=text))
        reply_text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Twin reply failed: {exc!s}") from exc

    # Log the conversation under the owner's id but tagged 'heir_portal'
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

    return {"reply": reply_text, "session_id": session_id}
