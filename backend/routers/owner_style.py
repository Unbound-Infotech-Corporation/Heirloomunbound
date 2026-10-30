"""Owner-only view, edit, and reset of the talking-style profile."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user
from owner_style import (
    STYLE_KEYS,
    _load_doc,
    _save_doc,
    apply_owner_edit,
    complete_local,
    empty_profile,
    note_owner_line,
    public_profile,
)
from presence_access import require_owner

router = APIRouter(prefix="/owner/style", tags=["owner-style"])


class StyleEdit(BaseModel):
    word_choice: Optional[str] = Field(default=None, max_length=600)
    sentence_length: Optional[str] = Field(default=None, max_length=600)
    punctuation: Optional[str] = Field(default=None, max_length=600)
    casing: Optional[str] = Field(default=None, max_length=600)
    deliberate_typos: Optional[str] = Field(default=None, max_length=600)
    humor: Optional[str] = Field(default=None, max_length=600)
    opens: Optional[str] = Field(default=None, max_length=600)
    closes: Optional[str] = Field(default=None, max_length=600)
    skips: Optional[str] = Field(default=None, max_length=600)
    topics: Optional[str] = Field(default=None, max_length=600)


def _fields(body: StyleEdit, current: dict) -> dict:
    incoming = body.model_dump()
    merged = {}
    for key in STYLE_KEYS:
        if incoming.get(key) is None:
            merged[key] = current.get(key) or ""
        else:
            merged[key] = incoming[key]
    return merged


@router.get("")
async def read_style(user: dict = Depends(get_current_user)):
    require_owner(user)
    doc = await _load_doc(user["user_id"])
    return {"profile": public_profile(doc)}


@router.put("")
async def edit_style(body: StyleEdit, user: dict = Depends(get_current_user)):
    require_owner(user)
    current = await _load_doc(user["user_id"])
    saved = apply_owner_edit(current, _fields(body, current))
    await _save_doc(user["user_id"], saved)
    return {"profile": public_profile(saved)}


@router.post("/reset")
async def reset_style(user: dict = Depends(get_current_user)):
    require_owner(user)
    blank = empty_profile()
    await _save_doc(user["user_id"], blank)
    return {"profile": public_profile(blank)}


@router.post("/refresh")
async def refresh_style(user: dict = Depends(get_current_user)):
    require_owner(user)
    try:
        saved = await note_owner_line(
            user["user_id"],
            "",
            load=_load_doc,
            save=_save_doc,
            complete=complete_local,
            force=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="Local Ollama did not update the style profile.") from exc
    return {"profile": public_profile(saved)}
