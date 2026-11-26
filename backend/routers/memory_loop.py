"""Record a memory: one question, one answer, one card, then a grounded reply."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

import card_sharing as sharing
from deps import db, get_current_user
from memory_cards import (
    answer_grounded,
    approve_fields,
    choose_prompt,
    draft_card,
    entry_from_card,
    grounding_block,
    new_card_doc,
    new_prompt_doc,
    cards_reached_through_archive,
    merge_cards,
    recall_cards,
    stored_prompt_status,
    visible_cards,
    why_from,
)

router = APIRouter(prefix="/memory-loop", tags=["memory-loop"])


class AnswerReq(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=8000)
    prompt_id: str = ""
    key: str = ""
    question: str = ""


class CardEdit(BaseModel):
    title: Optional[str] = None
    era: Optional[str] = None
    people: Optional[list[str] | str] = None
    story: Optional[str] = None
    approve: bool = False


class CardShare(BaseModel):
    # owner/private: only the owner's Twin. family/heir: heirs after release. heir_ids limits it to those heirs.
    visibility: str = Field(..., pattern="^(owner|private|family|heir)$")
    heir_ids: list[str] = Field(default_factory=list, max_length=50)


class BulkShare(CardShare):
    card_ids: list[str] = Field(..., min_length=1, max_length=200)


class SharingDefault(BaseModel):
    share_new_cards: bool


class AskReq(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def _prompts(user_id: str) -> list[dict]:
    cursor = db.daily_prompts.find({"user_id": user_id}, {"_id": 0})
    return await cursor.to_list(length=200)


async def _nudges(user_id: str) -> list[dict]:
    cursor = db.nudges.find({"user_id": user_id, "status": "open"}, {"_id": 0})
    return await cursor.to_list(length=50)


async def _cards(user_id: str, *, approved_only: bool = False) -> list[dict]:
    query = {"user_id": user_id}
    if approved_only:
        # Imports can leave hundreds of pending cards; they must not push approved ones out.
        query["status"] = "approved"
    cursor = db.memory_cards.find(query, {"_id": 0, "transcript": 0})
    return await cursor.to_list(length=3000)


async def _local_complete(system: str, user: str) -> str:
    from llm_provider import complete_text, prefer_local

    if not prefer_local():
        raise RuntimeError("This box answers with the local model only")
    return await complete_text(system, user, session_id="memory-loop")


@router.get("/next")
async def next_prompt(user: dict = Depends(get_current_user), key: str = "", question: str = ""):
    user_id = user["user_id"]
    prompts = await _prompts(user_id)
    choice = choose_prompt(
        prompts,
        await _nudges(user_id),
        today=_today(),
        chosen_key=key,
        chosen_question=question,
    )
    prompt = choice.get("prompt")
    if choice.get("create") and prompt:
        doc = new_prompt_doc(user_id, prompt)
        await db.daily_prompts.insert_one(dict(doc))
        prompt = doc
        choice["waiting"] = int(choice.get("waiting") or 0) + 1
    return {
        "prompt": prompt,
        "waiting": int(choice.get("waiting") or 0),
        "cards": len([card for card in await _cards(user_id) if card.get("status") == "approved"]),
    }


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    del user
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="The recording was empty")
    try:
        from local_inference import transcribe_whisper_bytes

        text = transcribe_whisper_bytes(raw, filename=file.filename or "memory.wav")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Hearing is not installed on this box. Type the answer instead.") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="Hearing could not read that recording. Type the answer instead.") from exc
    if not (text or "").strip():
        raise HTTPException(status_code=422, detail="No words came through. Try again, or type the answer.")
    return {"transcript": text.strip()}


@router.post("/answer")
async def answer(body: AnswerReq, user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    prompts = await _prompts(user_id)
    choice = choose_prompt(
        prompts,
        await _nudges(user_id),
        today=_today(),
        chosen_key=body.key,
        chosen_question=body.question,
    )
    prompt = dict(choice.get("prompt") or {})
    if body.prompt_id:
        found = next((row for row in prompts if row.get("prompt_id") == body.prompt_id), None)
        if found:
            prompt = found
    if body.question:
        prompt["question"] = body.question
    status = stored_prompt_status(choice) if not prompt.get("prompt_id") else None
    if status and str(prompt.get("question") or "").strip():
        prompt = new_prompt_doc(user_id, prompt)
        prompt["status"] = status
        await db.daily_prompts.insert_one(dict(prompt))
    try:
        draft = await draft_card(body.transcript, str(prompt.get("question") or ""), _local_complete)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    card = new_card_doc(user_id, draft, prompt_id=str(prompt.get("prompt_id") or ""))
    await db.memory_cards.insert_one(dict(card))
    return {"card": card, "prompt": prompt}


@router.patch("/cards/{card_id}")
async def edit_card(card_id: str, body: CardEdit, user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    card = await db.memory_cards.find_one({"card_id": card_id, "user_id": user_id}, {"_id": 0})
    if not card:
        raise HTTPException(status_code=404, detail="That memory card is not on this box")
    if not body.approve and body.title is None and body.story is None and body.era is None and body.people is None:
        return {"card": card}
    if not body.approve:
        updated = dict(card)
        fields = approve_fields(card, body.model_dump(), now=datetime.now(timezone.utc))
        for key in ("title", "era", "people", "story"):
            updated[key] = fields[key]
        updated["status"] = card.get("status") or "pending"
        updated["approved_at"] = card.get("approved_at") or ""
        updated["updated_at"] = fields["updated_at"]
        await db.memory_cards.update_one({"card_id": card_id, "user_id": user_id}, {"$set": updated})
        return {"card": updated}
    from life_story import shares_new_cards

    updated = approve_fields(card, body.model_dump(), share_new=await shares_new_cards(db, user_id))
    await db.memory_cards.update_one({"card_id": card_id, "user_id": user_id}, {"$set": updated})
    if str(card.get("status") or "") != "approved":
        entry = entry_from_card({**card, **updated})
        await db.entries.insert_one(entry)
    prompt_id = str(card.get("prompt_id") or "")
    if prompt_id:
        await db.daily_prompts.update_one(
            {"prompt_id": prompt_id, "user_id": user_id},
            {"$set": {"status": "answered", "answered_at": updated["approved_at"], "card_id": card_id}},
        )
        await db.nudges.update_one(
            {"nudge_id": prompt_id, "user_id": user_id},
            {"$set": {"status": "acted"}},
        )
    return {"card": updated}


@router.post("/cards/share")
async def share_cards(body: BulkShare, user: dict = Depends(get_current_user)):
    """Share or unshare several approved cards at once. Pending cards are skipped, never shared."""
    try:
        return await sharing.share_cards(db, user["user_id"], body.card_ids, body.visibility, body.heir_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cards/{card_id}/share")
async def share_card(card_id: str, body: CardShare, user: dict = Depends(get_current_user)):
    """The owner decides which approved memories an heir's Twin may tell. Cards start owner-only."""
    card = await db.memory_cards.find_one({"card_id": card_id, "user_id": user["user_id"]}, {"_id": 0})
    if not card:
        raise HTTPException(status_code=404, detail="That memory card is not on this box")
    if str(card.get("status") or "") != "approved":
        raise HTTPException(status_code=400, detail="Approve the card before sharing it")
    try:
        done = await sharing.share_cards(db, user["user_id"], [card_id], body.visibility, body.heir_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"card": {**card, "visibility": done["visibility"], "heir_ids": done["heir_ids"]}}


@router.get("/sharing")
async def get_sharing(user: dict = Depends(get_current_user)):
    return {"share_new_cards": await sharing.get_default(db, user["user_id"])}


@router.put("/sharing")
async def set_sharing(body: SharingDefault, user: dict = Depends(get_current_user)):
    """Default for cards approved from now on. Cards already approved keep their sharing."""
    return {"share_new_cards": await sharing.set_default(db, user["user_id"], body.share_new_cards)}


@router.get("/cards/{card_id}")
async def get_card(card_id: str, user: dict = Depends(get_current_user)):
    card = await db.memory_cards.find_one(
        {"card_id": card_id, "user_id": user["user_id"]},
        {"_id": 0},
    )
    if not card:
        raise HTTPException(status_code=404, detail="That memory card is not on this box")
    return {"card": card}


@router.post("/ask")
async def ask(body: AskReq, user: dict = Depends(get_current_user)):
    cards = await _cards(user["user_id"], approved_only=True)
    from grounding import verify_reply

    result = await answer_grounded(body.question, cards, _local_complete, verify=verify_reply)
    return result


async def grounding_for_turn(
    user_id: str,
    question: str,
    *,
    audience: str = "owner",
    heir_surface: bool = False,
    archive_text: str = "",
) -> tuple[str, list[dict]]:
    """Approved cards for the twin prompt. Pending and owner-private cards stay out."""
    try:
        cards = await _cards(user_id, approved_only=True)
    except Exception:
        return "", []
    allowed = visible_cards(cards, audience=audience, heir_surface=heir_surface)
    try:
        used = await recall_cards(question, allowed)
    except Exception:
        used = []
    used = merge_cards(used, cards_reached_through_archive(archive_text, allowed, question))
    return grounding_block(used), why_from(used)
