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
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db
from heir_guards import heir_archive_query, portal_conversation_id, portal_turn_update
from letter_unlock import letter_unlocked

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


def _letter_unlocked(letter: dict, heir: dict, now: datetime, heirs: list[dict] | None = None) -> bool:
    return letter_unlocked(letter, heir, now, heirs)


async def _family(owner_id: str) -> list[dict]:
    """Heir names for this owner. Used only to resolve a unique recipient name."""
    return await db.heirs.find(
        {"user_id": owner_id},
        {"_id": 0, "heir_id": 1, "name": 1},
    ).to_list(length=500)


async def _persist_portal_turn(
    owner_id: str,
    heir: dict,
    requested_session: Optional[str],
    user_text: str,
    reply_text: str,
) -> str:
    """Append a portal turn. Never write into an owner Sit / Twin / Assist thread."""
    session_id = portal_conversation_id(heir["heir_id"], requested_session)
    existing = await db.conversations.find_one(
        {"conversation_id": session_id, "user_id": owner_id},
        {"_id": 0, "kind": 1, "heir_id": 1},
    )
    if existing:
        kind = existing.get("kind")
        other_heir = existing.get("heir_id")
        if kind not in (None, "heir_portal") or (
            other_heir and other_heir != heir["heir_id"]
        ):
            raise HTTPException(status_code=400, detail="Invalid session")
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.conversations.update_one(
        {"conversation_id": session_id, "user_id": owner_id},
        portal_turn_update(
            owner_id=owner_id,
            heir_id=heir["heir_id"],
            session_id=session_id,
            user_text=user_text,
            reply_text=reply_text,
            now_iso=now_iso,
        ),
        upsert=True,
    )
    return session_id


@router.get("/{token}")
async def portal_summary(token: str):
    heir = await get_released_heir(token)
    owner = await _owner(heir)
    now = _now()
    # Count visible letters
    cursor = db.sealed_letters.find({"user_id": owner["user_id"]}, {"_id": 0})
    letters = await cursor.to_list(length=500)
    family = await _family(owner["user_id"])
    visible = [l for l in letters if _letter_unlocked(l, heir, now, family)]

    total_entries = await db.entries.count_documents(heir_archive_query(owner["user_id"]))

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
    family = await _family(owner_id)
    out = []
    for l in letters:
        if _letter_unlocked(l, heir, now, family):
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
                "sealed": True,
            })
    return {"letters": out}


@router.get("/{token}/entries")
async def portal_entries(token: str, limit: int = 100, offset: int = 0):
    heir = await get_released_heir(token)
    owner_id = heir["user_id"]
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    query = heir_archive_query(owner_id)
    cursor = db.entries.find(
        query,
        {"_id": 0, "user_id": 0},
    ).sort("created_at", -1).skip(offset).limit(limit)
    items = await cursor.to_list(length=limit)
    for item in items:
        item.pop("cleanup", None)
    total = await db.entries.count_documents(query)
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

    from grief_guard import with_grief_aside
    from memorial_mode import memorial_from_user
    from observer_prompt import attach_observer_context
    from memory_cards import history_without_invented_claims
    from twin_pack import TwinPack, compile_twin_prompt, stance_line
    from twin_runtime import _fence_from_user
    from twin_safety import grief_for_turn, intercept_crisis, sessions_today_count

    crisis = await intercept_crisis(
        text,
        user=owner,
        surface="heir_portal",
        audience="heir",
        persist=False,
        source="heir_portal",
        heir=heir,
    )
    if crisis:
        session_id = await _persist_portal_turn(
            owner["user_id"], heir, payload.session_id, text, crisis.reply
        )
        return {
            "reply": crisis.reply,
            "session_id": session_id,
            "crisis": True,
        }

    memorial = memorial_from_user(owner)
    prior_id = portal_conversation_id(heir["heir_id"], payload.session_id)
    existing = await db.conversations.find_one(
        {"conversation_id": prior_id, "user_id": owner["user_id"]},
        {"_id": 0, "messages": 1},
    )
    prior_messages = list((existing or {}).get("messages") or [])
    prior_messages.append({"role": "user", "content": text})
    sessions = await sessions_today_count(owner["user_id"], kind="heir_portal")
    grief = grief_for_turn(
        text,
        audience="heir",
        messages=prior_messages,
        sessions_today=sessions,
        settings=memorial,
    )

    # Grounded like the owner Twin: only rows this heir may see, then fact-checked.
    from heir_grounding import alias_lines, heir_reply
    from memory_cards import grounding_block

    rows = await heir_evidence_rows(owner["user_id"], heir, text)
    attached = attach_observer_context("", text, audience="heir", heir_surface=True)
    observer = None
    if attached.block:
        observer = {"card_id": "observer", "title": "From what I've watched", "story": attached.block,
                    "status": "approved", "people": [], "kind": "observer"}
    session_id = portal_conversation_id(heir["heir_id"], payload.session_id)
    history = [
        m for m in history_without_invented_claims(prior_messages[:-1])
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]

    async def draft(used: list[dict]) -> str:
        pack = TwinPack(
            core={
                "stance": stance_line("family"),
                "portrait": "",
                "values": "",
                "fence": _fence_from_user(owner, None),
            },
            passages=[],
            facts=[],
            citation_line="",
            grounded=True,
            audience="heir",
        )
        system = compile_twin_prompt(pack, owner.get("name", "the owner"), memorial=memorial, grief=grief)
        block = grounding_block(used)
        if block:
            system += "\n\n" + block
        system += (
            f"\nYou are speaking with their heir {heir.get('name', 'an heir')} "
            f"({heir.get('relationship', 'loved one')}). Be brief: 1-4 sentences. "
            "Only state memories written above; never invent one. Do NOT take any actions. Do NOT invoke skills."
        )
        known = alias_lines(heir)
        if known:
            system += "\nNames the family uses (to understand the question, not memories): " + " ".join(known)
        from llm_provider import complete_text, prefer_local, refuse_cloud

        if prefer_local():
            return await complete_text(system, text, history=history, session_id=session_id)
        refuse_cloud("anthropic", "claude-sonnet-4-6", caller="heir_portal")
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id,
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-4-6")
        reply = await chat.send_message(UserMessage(text=text))
        return reply if isinstance(reply, str) else getattr(reply, "content", str(reply))

    try:
        turn = await heir_reply(text, owner=owner, heir=heir, rows=rows, draft=draft, observer=observer)
        reply_text = with_grief_aside(turn["reply"], grief, history=prior_messages)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Twin reply failed. Try again.") from None

    session_id = await _persist_portal_turn(
        owner["user_id"], heir, session_id, text, reply_text
    )
    out = {"reply": reply_text, "session_id": session_id, "grounded": turn["grounded"],
           "citations": turn["cited"]}
    if turn["cited"]:
        out["citation_line"] = "From: " + "; ".join(c["title"] for c in turn["cited"][:3])
    if observer and any(c["kind"] == "observer" for c in turn["cited"]):
        out["source_label"] = "from what I've watched"
    return out


async def heir_evidence_rows(owner_id: str, heir: dict, question: str) -> list[dict]:
    """Everything this heir may hear about, fenced in the queries.

    Approved cards the heir may see; archive entries past the memory_guard fence;
    letters already unlocked for this heir. Rows with ``heir_ids`` go only to those heirs.
    """
    import re as _re

    from heir_grounding import entry_as_card, heir_cards, letter_as_card, per_heir_clause
    from memory_guard import mongo_query
    from routers.memory_loop import _cards

    heir_id = heir["heir_id"]
    rows = heir_cards(await _cards(owner_id, approved_only=True), heir_id)

    projection = {"_id": 0, "entry_id": 1, "type": 1, "title": 1, "content": 1, "tags": 1, "heir_ids": 1}
    fenced = mongo_query(owner_id, "heir", kind="entry", extra=per_heir_clause(heir_id))
    recent = await db.entries.find(fenced, projection).sort("created_at", -1).limit(200).to_list(length=200)
    tokens = [t for t in _re.split(r"\W+", question.lower()) if len(t) > 3][:8]
    matched: list[dict] = []
    if tokens:
        ors = [{"content": {"$regex": _re.escape(t), "$options": "i"}} for t in tokens]
        ors += [{"title": {"$regex": _re.escape(t), "$options": "i"}} for t in tokens]
        query = mongo_query(owner_id, "heir", kind="entry", extra={"$and": [per_heir_clause(heir_id), {"$or": ors}]})
        matched = await db.entries.find(query, projection).limit(100).to_list(length=100)
    seen: set[str] = set()
    for entry in matched + recent:
        key = str(entry.get("entry_id") or "")
        if key and key not in seen and str(entry.get("content") or "").strip():
            seen.add(key)
            rows.append(entry_as_card(entry))

    now = _now()
    family = await _family(owner_id)
    letters = await db.sealed_letters.find({"user_id": owner_id}, {"_id": 0}).to_list(length=500)
    rows += [letter_as_card(l) for l in letters if _letter_unlocked(l, heir, now, family)]
    return rows
