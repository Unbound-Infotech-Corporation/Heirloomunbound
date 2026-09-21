"""Owner-only Heirloom Rooms — capture, mock reconstruct, serve a placeholder scene."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from deps import db, get_current_user
from rooms import (
    ALLOWED_TYPES,
    CAPTURE_INSTRUCTIONS,
    CAPTURE_STATUSES,
    MAX_ASSETS,
    MAX_BYTES,
    asset_kind,
    mark_failed,
    mark_processing,
    mock_reconstruct,
    new_room_doc,
    public_room,
    scene_summary,
)
from storage import APP_PREFIX, put_object
from utils import detect_image_mime

router = APIRouter(prefix="/rooms", tags=["rooms"])

EXT_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/heic": "heic",
    "image/heif": "heif",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}


class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)


class ReconstructReq(BaseModel):
    backend: Optional[str] = Field("mock", max_length=32)
    vendor: Optional[str] = Field(None, max_length=80)


def _owner_gate(user: dict) -> None:
    if user.get("account_status") == "refunded":
        raise HTTPException(status_code=403, detail="account_inactive")


async def _get_owned(room_id: str, user_id: str) -> dict:
    doc = await db.rooms.find_one({"room_id": room_id, "user_id": user_id, "is_deleted": {"$ne": True}})
    if not doc:
        raise HTTPException(status_code=404, detail="Room not found")
    return doc


@router.get("")
async def list_rooms(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    cursor = db.rooms.find(
        {"user_id": user["user_id"], "is_deleted": {"$ne": True}},
        {"_id": 0},
    ).sort("created_at", -1)
    items = await cursor.to_list(length=100)
    return {
        "rooms": [public_room(r) for r in items],
        "capture_instructions": CAPTURE_INSTRUCTIONS,
        "statuses": list(CAPTURE_STATUSES),
        "scene_format": "gltf",
    }


@router.post("")
async def create_room(payload: RoomCreate, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    doc = new_room_doc(user["user_id"], payload.name)
    doc["room_id"] = f"rm_{uuid.uuid4().hex[:12]}"
    doc["is_deleted"] = False
    await db.rooms.insert_one(dict(doc))
    return public_room(doc)


@router.get("/{room_id}")
async def get_room(room_id: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    doc = await _get_owned(room_id, user["user_id"])
    out = public_room(doc)
    out["scene_summary"] = scene_summary(doc)
    out["capture_instructions"] = CAPTURE_INSTRUCTIONS
    return out


@router.patch("/{room_id}")
async def rename_room(room_id: str, payload: RoomUpdate, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    if not payload.name:
        raise HTTPException(status_code=400, detail="No fields to update")
    from rooms import now_iso

    res = await db.rooms.update_one(
        {"room_id": room_id, "user_id": user["user_id"], "is_deleted": {"$ne": True}},
        {"$set": {"name": payload.name.strip()[:80], "updated_at": now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Room not found")
    doc = await _get_owned(room_id, user["user_id"])
    return public_room(doc)


@router.delete("/{room_id}")
async def delete_room(room_id: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    from rooms import now_iso

    res = await db.rooms.update_one(
        {"room_id": room_id, "user_id": user["user_id"]},
        {"$set": {"is_deleted": True, "updated_at": now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Room not found")
    return {"ok": True}


@router.post("/{room_id}/assets")
async def upload_asset(
    room_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Accept a video or still. Stores via the same object store as photos when available."""
    _owner_gate(user)
    doc = await _get_owned(room_id, user["user_id"])
    assets = list(doc.get("assets") or [])
    if len(assets) >= MAX_ASSETS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_ASSETS} files per room")

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file type (images or mp4/webm/mov)")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (50MB max)")
    if content_type.startswith("image/"):
        detected = detect_image_mime(data[:32])
        if not detected:
            raise HTTPException(status_code=400, detail="File does not look like a real image")

    asset_id = f"ra_{uuid.uuid4().hex[:12]}"
    ext = EXT_BY_MIME.get(content_type, "bin")
    path = f"{APP_PREFIX}/rooms/{user['user_id']}/{room_id}/{asset_id}.{ext}"
    stored = False
    storage_error = None
    try:
        put_object(path, data, content_type)
        stored = True
    except Exception as exc:  # noqa: BLE001
        # Metadata still records the capture; mock reconstruct does not need bytes.
        storage_error = str(exc)[:200]
        path = ""

    from rooms import now_iso

    asset = {
        "asset_id": asset_id,
        "kind": asset_kind(content_type),
        "content_type": content_type,
        "size": len(data),
        "original_filename": (file.filename or "")[:180],
        "storage_path": path,
        "stored": stored,
        "storage_error": storage_error,
        "created_at": now_iso(),
    }
    await db.rooms.update_one(
        {"room_id": room_id, "user_id": user["user_id"]},
        {
            "$push": {"assets": asset},
            "$set": {"updated_at": now_iso()},
        },
    )
    return asset


@router.post("/{room_id}/reconstruct")
async def reconstruct_room(
    room_id: str,
    payload: ReconstructReq | None = None,
    user: dict = Depends(get_current_user),
):
    """Kick a reconstruction job. Phase 1 default is the mock backend."""
    _owner_gate(user)
    doc = await _get_owned(room_id, user["user_id"])
    body = payload or ReconstructReq()
    backend = (body.backend or "mock").strip().lower() or "mock"
    vendor = (body.vendor or "").strip() or None
    if backend != "mock":
        # Optional integration point — Phase 1 does not call paid vendors.
        mark_failed(doc, f"Vendor backend '{backend}' is not wired in Phase 1. Use backend=mock.")
        await db.rooms.replace_one({"room_id": room_id, "user_id": user["user_id"]}, doc)
        raise HTTPException(
            status_code=400,
            detail="Only the mock reconstruction backend ships in Phase 1. Pass backend=mock.",
        )
    mark_processing(doc, backend="mock", vendor=vendor)
    mock_reconstruct(doc)
    patch = {k: v for k, v in public_room(doc).items() if k not in {"room_id", "user_id"}}
    await db.rooms.update_one(
        {"room_id": room_id, "user_id": user["user_id"]},
        {"$set": patch},
    )
    fresh = await _get_owned(room_id, user["user_id"])
    return public_room(fresh)


@router.get("/{room_id}/scene")
async def get_scene(room_id: str, user: dict = Depends(get_current_user)):
    """Return the ready glTF (or 409 if not ready)."""
    _owner_gate(user)
    doc = await _get_owned(room_id, user["user_id"])
    if (doc.get("capture_status") or "") != "ready" or not (doc.get("scene") or {}).get("gltf"):
        raise HTTPException(status_code=409, detail="Room is not ready yet")
    gltf = doc["scene"]["gltf"]
    return JSONResponse(content=gltf, media_type="model/gltf+json")
