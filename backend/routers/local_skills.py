"""Owner-only setup for the local-first skills: accounts, file folders, drafts, notes."""
from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel

import account_oauth
from connectors import connectors_allowed
from deps import db, get_current_user

router = APIRouter(prefix="/local-skills", tags=["local-skills"])


def _owner_gate(user: dict) -> None:
    if user.get("account_status") == "refunded":
        raise HTTPException(status_code=403, detail="account_inactive")
    if not connectors_allowed(audience=user.get("audience") or "owner", heir_surface=bool(user.get("heir_surface"))):
        raise HTTPException(status_code=403, detail="owner_only")


def _file_status() -> dict:
    from file_index import FileIndex

    idx = FileIndex()
    try:
        return {"roots": idx.roots(), "files": idx.count()}
    finally:
        idx.close()


@router.get("/status")
async def status(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    from web_privacy import search_backend

    linked = set(await account_oauth.connected(user["user_id"]))
    providers = {
        pid: {"label": p.label, "configured": p.configured(), "connected": pid in linked, "scopes": list(p.scopes)}
        for pid, p in account_oauth.PROVIDERS.items()
    }
    files = await asyncio.to_thread(_file_status)
    drafts = await db.calendar_drafts.count_documents({"user_id": user["user_id"], "status": "draft"})
    notes = await db.owner_notes.count_documents({"user_id": user["user_id"]})
    return {"providers": providers, "files": files, "calendar_drafts": drafts, "notes": notes, "web_search": search_backend()}


@router.post("/oauth/{provider}/start")
async def oauth_start(provider: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    try:
        url = await account_oauth.start(user["user_id"], provider)
    except ValueError:
        raise HTTPException(status_code=404, detail="unknown_provider")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"url": url}


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, state: str = Query(""), code: str = Query(""), error: str = Query("")):
    """The provider redirects the owner's browser here. ``state`` ties it to the owner who started."""
    front = os.environ.get("PUBLIC_FRONTEND_URL", "").rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{front}/abilities?skill_error=denied")
    try:
        await account_oauth.finish(provider, state=state, code=code)
    except Exception:  # noqa: BLE001 - never echo token-service text into a URL
        return RedirectResponse(f"{front}/abilities?skill_error=link_failed")
    return RedirectResponse(f"{front}/abilities?connected={provider}")


@router.delete("/oauth/{provider}")
async def oauth_disconnect(provider: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    return {"disconnected": await account_oauth.disconnect(user["user_id"], provider)}


class RootReq(BaseModel):
    path: str


@router.post("/files/roots")
async def add_root(payload: RootReq, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    from file_index import FileIndex

    def _add() -> dict:
        idx = FileIndex()
        try:
            root = idx.add_root(payload.path)
            stats = idx.reindex()
            return {"root": root, **stats}
        finally:
            idx.close()

    try:
        return await asyncio.to_thread(_add)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/files/roots/remove")
async def remove_root(payload: RootReq, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    from file_index import FileIndex

    def _remove() -> int:
        idx = FileIndex()
        try:
            return idx.remove_root(payload.path)
        finally:
            idx.close()

    return {"removed_files": await asyncio.to_thread(_remove)}


@router.post("/files/reindex")
async def reindex(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    from file_index import FileIndex

    def _run() -> dict:
        idx = FileIndex()
        try:
            return idx.reindex()
        finally:
            idx.close()

    return await asyncio.to_thread(_run)


@router.get("/calendar/drafts")
async def list_drafts(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    rows = await db.calendar_drafts.find({"user_id": user["user_id"], "status": "draft"}, {"_id": 0}).sort("start", 1).to_list(100)
    return {"drafts": rows}


@router.get("/calendar/drafts/{draft_id}.ics")
async def draft_ics(draft_id: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    from calendar_cloud import ics_for

    draft = await db.calendar_drafts.find_one({"user_id": user["user_id"], "draft_id": draft_id}, {"_id": 0})
    if not draft:
        raise HTTPException(status_code=404, detail="not_found")
    return PlainTextResponse(
        ics_for(draft),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{draft_id}.ics"'},
    )


@router.delete("/calendar/drafts/{draft_id}")
async def delete_draft(draft_id: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    result = await db.calendar_drafts.delete_one({"user_id": user["user_id"], "draft_id": draft_id})
    return {"deleted": result.deleted_count}


@router.get("/notes")
async def list_notes(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    rows = await db.owner_notes.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"notes": rows}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    result = await db.owner_notes.delete_one({"user_id": user["user_id"], "note_id": note_id})
    return {"deleted": result.deleted_count}
