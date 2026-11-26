"""Life-story interview, memory imports, and the review queue. Owner only, local model only.

Every answer and import becomes a *pending* memory card. Approving a card is what lets the
twin use it (``memory_loop.grounding_for_turn`` reads approved cards only).
"""
from __future__ import annotations

import asyncio
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

import life_story as ls
from connectors import connectors_allowed
from deps import db, get_current_user
from memory_cards import approve_fields

router = APIRouter(prefix="/life-story", tags=["life-story"])

MAX_UPLOAD = 25 * 1024 * 1024
_jobs: set[asyncio.Task] = set()


def _owner_gate(user: dict) -> None:
    if user.get("account_status") == "refunded":
        raise HTTPException(status_code=403, detail="account_inactive")
    if not connectors_allowed(audience=user.get("audience") or "owner", heir_surface=bool(user.get("heir_surface"))):
        raise HTTPException(status_code=403, detail="owner_only")


async def _complete(system: str, user: str) -> str:
    from llm_provider import complete_text, prefer_local

    if not prefer_local():
        raise RuntimeError("This box answers with the local model only")
    return await complete_text(system, user, session_id="life-story")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- interview

class StartReq(BaseModel):
    length: str = "full"
    restart: bool = False


class AnswerReq(BaseModel):
    qid: str
    transcript: str = Field(..., min_length=1, max_length=8000)
    followups: bool = True


class SkipReq(BaseModel):
    qid: str = ""
    chapter: str = ""


def _view(session: Optional[dict]) -> dict:
    if not session:
        return {"session": None}
    public = {k: v for k, v in session.items() if k not in ("_id", "queue", "done")}
    return {"session": public, "current": ls.current_item(session), "progress": ls.progress(session)}


async def _active(user_id: str) -> Optional[dict]:
    return await db.life_interviews.find_one({"user_id": user_id, "status": "active"}, {"_id": 0})


@router.get("/plan")
async def get_plan(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    out = {}
    for length in ("short", "full"):
        rows = ls.plan(length)
        out[length] = {"questions": len(rows), "minutes": ls.estimate_minutes(len(rows))}
    out["chapters"] = [{"key": k, "title": t} for k, t, _ in ls.CHAPTERS]
    return out


@router.post("/interview")
async def start_interview(body: StartReq, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    uid = user["user_id"]
    session = await _active(uid)
    if session and not body.restart:
        return _view(session)
    if session:
        await db.life_interviews.update_one({"interview_id": session["interview_id"]}, {"$set": {"status": "stopped", "updated_at": _now()}})
    session = ls.new_session(uid, body.length)
    await db.life_interviews.insert_one(dict(session))
    return _view(session)


@router.get("/interview")
async def current_interview(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    return _view(await _active(user["user_id"]))


async def _save(session: dict) -> None:
    await db.life_interviews.update_one(
        {"interview_id": session["interview_id"], "user_id": session["user_id"]},
        {"$set": {k: session[k] for k in ("queue", "done", "followups", "status", "updated_at")}},
    )


@router.post("/interview/answer")
async def answer(body: AnswerReq, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    uid = user["user_id"]
    session = await _active(uid)
    if not session:
        raise HTTPException(status_code=404, detail="Start the interview first")
    item = next((row for row in session["queue"] if row["qid"] == body.qid), None)
    if not item:
        raise HTTPException(status_code=404, detail="That question is not in this interview")
    words = body.transcript.strip()
    card = None
    if ls.substantial(words):
        try:
            card = await ls.draft_pending_card(uid, words, item["question"], _complete, source="interview",
                                               ref=session["interview_id"], chapter=item["chapter"])
        except RuntimeError:
            card = ls.quick_card(uid, words, item["question"], source="interview",
                                 ref=session["interview_id"], chapter=item["chapter"])
        await db.memory_cards.insert_one(dict(card))
        ls.mark(session, body.qid, "answered", card["card_id"])
    else:
        ls.mark(session, body.qid, "too_short")
    follow = None
    if card and body.followups and item.get("kind") == "core":
        question = await ls.ask_followup(words, item["question"], _complete)
        if question:
            follow = ls.add_followup(session, body.qid, question)
            if follow and session["status"] == "finished":
                session["status"] = "active"
    await _save(session)
    card_out = {k: v for k, v in (card or {}).items() if k != "_id"} or None
    return {**_view(session), "card": card_out, "followup": follow}


@router.post("/interview/skip")
async def skip(body: SkipReq, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    session = await _active(user["user_id"])
    if not session:
        raise HTTPException(status_code=404, detail="Start the interview first")
    if body.chapter:
        ls.skip_chapter(session, body.chapter)
    elif body.qid:
        ls.mark(session, body.qid, "skipped")
    await _save(session)
    return _view(session)


@router.post("/interview/finish")
async def finish(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    session = await _active(user["user_id"])
    if session:
        session["status"] = "finished"
        session["updated_at"] = _now()
        await _save(session)
    return _view(session)


# ---------------------------------------------------------------- imports

async def _read(file: UploadFile) -> bytes:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="The file was empty")
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="That file is over 25 MB. Split it or export a shorter range.")
    return raw


@router.post("/import/messages/preview")
async def preview_messages(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    _owner_gate(user)
    kind, msgs = ls.parse_messages(file.filename or "", await _read(file))
    if not msgs:
        raise HTTPException(status_code=422, detail="No messages found. Use a WhatsApp .txt export, a Messenger/Instagram .json, or a CSV with sender and text columns.")
    dates = [m.when for m in msgs if m.when]
    return {
        "kind": kind,
        "messages": len(msgs),
        "senders": ls.senders(msgs),
        "from": min(dates).date().isoformat() if dates else "",
        "to": max(dates).date().isoformat() if dates else "",
    }


async def _new_job(uid: str, kind: str, name: str, total: int) -> dict:
    job = {"import_id": f"mimp_{uuid.uuid4().hex[:12]}", "user_id": uid, "kind": kind, "name": name[:200],
           "status": "drafting", "total": total, "done": 0, "created_at": _now(), "updated_at": _now()}
    await db.memory_imports.insert_one(dict(job))
    job.pop("_id", None)
    return job


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _jobs.add(task)
    task.add_done_callback(_jobs.discard)


@router.post("/import/messages")
async def import_messages(
    file: UploadFile = File(...),
    me: str = Form(...),
    max_cards: int = Form(25),
    user: dict = Depends(get_current_user),
):
    _owner_gate(user)
    kind, msgs = ls.parse_messages(file.filename or "", await _read(file))
    if not any(m.sender.strip().lower() == me.strip().lower() for m in msgs):
        raise HTTPException(status_code=422, detail="None of those messages are from that name. Pick yourself from the list.")
    passages = ls.passages_from_messages(msgs, me, max_cards=max(1, min(60, max_cards)))
    if not passages:
        raise HTTPException(status_code=422, detail="Your messages here are too short to make memories from.")
    job = await _new_job(user["user_id"], kind, file.filename or kind, len(passages))
    _spawn(ls.run_import(job, passages, source="messages", complete=_complete, store=db))
    return {"import": job}


def _document_text(filename: str, raw: bytes) -> str:
    from file_index import extract_text

    suffix = Path(filename or "doc.txt").suffix.lower() or ".txt"
    if suffix not in {".txt", ".md", ".docx", ".pdf", ".html", ".htm"}:
        raise HTTPException(status_code=415, detail="Letters and documents can be .txt, .md, .docx, .pdf, or .html")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(raw)
        return extract_text(path)


@router.post("/import/document")
async def import_document(
    file: UploadFile = File(...),
    author: str = Form(""),
    title: str = Form(""),
    user: dict = Depends(get_current_user),
):
    """A letter or document. ``author`` empty means the owner wrote it."""
    _owner_gate(user)
    raw = await _read(file)
    text = await asyncio.to_thread(_document_text, file.filename or "", raw)
    name = title.strip() or Path(file.filename or "a document").stem
    passages = ls.passages_from_document(text, name, author=author.strip())
    if not passages:
        raise HTTPException(status_code=422, detail="No readable words in that file. A scanned letter needs typing or OCR first.")
    job = await _new_job(user["user_id"], "document", name, len(passages))
    _spawn(ls.run_import(job, passages, source="letter" if author.strip() else "document", complete=_complete, store=db))
    return {"import": job}


@router.post("/import/photo")
async def import_photo(
    file: UploadFile = File(...),
    caption: str = Form(""),
    taken_at: str = Form(""),
    place: str = Form(""),
    user: dict = Depends(get_current_user),
):
    """A photo plus the story behind it. The caption is the memory; the image is kept with Photos."""
    _owner_gate(user)
    from routers.photos import ALLOWED, EXT_BY_MIME
    from storage import APP_PREFIX, put_object
    from utils import detect_image_mime

    raw = await _read(file)
    mime = detect_image_mime(raw[:32])
    if not mime or mime not in ALLOWED:
        raise HTTPException(status_code=400, detail="That file does not look like a photo")
    found = ls.photo_details(raw)
    caption = " ".join((caption or found.get("caption") or "").split())
    taken_at = (taken_at or found.get("taken_at") or "").strip()
    if not ls.substantial(caption):
        return {"needs_caption": True, "found": found}
    uid = user["user_id"]
    photo_id = f"ph_{uuid.uuid4().hex[:12]}"
    stored = await asyncio.to_thread(put_object, f"{APP_PREFIX}/photos/{uid}/{photo_id}.{EXT_BY_MIME.get(mime, 'bin')}", raw, mime)
    await db.photos.insert_one({
        "photo_id": photo_id, "user_id": uid, "storage_path": stored["path"], "content_type": mime,
        "size": stored.get("size", len(raw)), "original_filename": file.filename, "caption": caption,
        "taken_at": taken_at or None, "entry_id": None, "is_deleted": False, "created_at": _now(),
    })
    transcript = ls.photo_transcript(caption, taken_at, place.strip())
    try:
        card = await ls.draft_pending_card(uid, transcript, "The story behind this photo", _complete,
                                           source="photo", ref=photo_id, era=taken_at[:4], media={"photo_id": photo_id})
    except RuntimeError:
        card = ls.quick_card(uid, transcript, "The story behind this photo", source="photo", ref=photo_id,
                             era=taken_at[:4], media={"photo_id": photo_id})
    await db.memory_cards.insert_one(dict(card))
    card.pop("_id", None)
    return {"card": card, "photo_id": photo_id}


@router.get("/imports")
async def list_imports(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    rows = await db.memory_imports.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(length=30)
    return {"imports": rows}


# ---------------------------------------------------------------- review queue

class ApproveReq(BaseModel):
    card_ids: list[str] = Field(..., min_length=1, max_length=200)


class EditReq(BaseModel):
    title: Optional[str] = None
    era: Optional[str] = None
    people: Optional[list[str] | str] = None
    story: Optional[str] = None


@router.get("/cards")
async def list_cards(status: str = "pending", source: str = "", user: dict = Depends(get_current_user)):
    _owner_gate(user)
    query: dict = {"user_id": user["user_id"], "status": status if status in ("pending", "approved") else "pending"}
    if source:
        query["source"] = source
    rows = await db.memory_cards.find(query, {"_id": 0, "transcript": 0}).sort("created_at", 1).to_list(length=300)
    counts = {}
    for st in ("pending", "approved"):
        counts[st] = await db.memory_cards.count_documents({"user_id": user["user_id"], "status": st})
    return {"cards": rows, "counts": counts}


@router.patch("/cards/{card_id}")
async def edit_card(card_id: str, body: EditReq, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    uid = user["user_id"]
    card = await db.memory_cards.find_one({"card_id": card_id, "user_id": uid}, {"_id": 0})
    if not card:
        raise HTTPException(status_code=404, detail="That memory card is not on this box")
    fields = approve_fields(card, body.model_dump())
    changes = {k: fields[k] for k in ("title", "era", "people", "story", "updated_at")}
    await db.memory_cards.update_one({"card_id": card_id, "user_id": uid}, {"$set": changes})
    return {"card": {**card, **changes}}


@router.post("/cards/approve")
async def approve_cards(body: ApproveReq, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    approved = []
    for card_id in body.card_ids:
        if await ls.approve_card(db, user["user_id"], card_id):
            approved.append(card_id)
    return {"approved": approved}


@router.post("/cards/discard")
async def discard_cards(body: ApproveReq, user: dict = Depends(get_current_user)):
    """Pending cards only. Approved memories are removed from the Memory page instead."""
    _owner_gate(user)
    result = await db.memory_cards.delete_many({"user_id": user["user_id"], "status": "pending", "card_id": {"$in": body.card_ids}})
    return {"discarded": result.deleted_count}
