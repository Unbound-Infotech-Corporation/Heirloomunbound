"""Photos: upload to object storage, attach captions, optional link to entry."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel

from deps import db, get_current_user
from storage import APP_PREFIX, get_object, put_object
from utils import detect_image_mime, make_photo_signature, verify_photo_signature

router = APIRouter(prefix="/photos", tags=["photos"])

ALLOWED = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif"}
EXT_BY_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/heic": "heic",
    "image/heif": "heif",
}


class PhotoUpdate(BaseModel):
    caption: Optional[str] = None
    taken_at: Optional[str] = None
    entry_id: Optional[str] = None


@router.post("/upload")
async def upload_photo(
    file: UploadFile = File(...),
    caption: str = Form(""),
    taken_at: str = Form(""),
    entry_id: str = Form(""),
    user: dict = Depends(get_current_user),
):
    if (file.content_type or "").lower() not in ALLOWED:
        raise HTTPException(status_code=400, detail="Unsupported image type")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large (12MB max)")
    # Security: validate magic bytes — Content-Type alone is forgeable
    detected = detect_image_mime(data[:32])
    if not detected:
        raise HTTPException(status_code=400, detail="File does not look like a real image")

    ext = EXT_BY_MIME.get(file.content_type.lower(), "bin")
    photo_id = f"ph_{uuid.uuid4().hex[:12]}"
    path = f"{APP_PREFIX}/photos/{user['user_id']}/{photo_id}.{ext}"
    try:
        result = put_object(path, data, file.content_type)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc!s}") from exc

    doc = {
        "photo_id": photo_id,
        "user_id": user["user_id"],
        "storage_path": result["path"],
        "content_type": file.content_type,
        "size": result.get("size", len(data)),
        "original_filename": file.filename,
        "caption": caption,
        "taken_at": taken_at or None,
        "entry_id": entry_id or None,
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.photos.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_photos(
    entry_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    query: dict = {"user_id": user["user_id"], "is_deleted": False}
    if entry_id:
        query["entry_id"] = entry_id
    cursor = db.photos.find(query, {"_id": 0}).sort("created_at", -1).limit(500)
    return await cursor.to_list(length=500)


@router.patch("/{photo_id}")
async def update_photo(photo_id: str, payload: PhotoUpdate, user: dict = Depends(get_current_user)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.photos.update_one(
        {"photo_id": photo_id, "user_id": user["user_id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Photo not found")
    doc = await db.photos.find_one({"photo_id": photo_id}, {"_id": 0})
    return doc


@router.delete("/{photo_id}")
async def delete_photo(photo_id: str, user: dict = Depends(get_current_user)):
    res = await db.photos.update_one(
        {"photo_id": photo_id, "user_id": user["user_id"]},
        {"$set": {"is_deleted": True}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Photo not found")
    return {"ok": True}


@router.post("/{photo_id}/signed-url")
async def signed_url(photo_id: str, user: dict = Depends(get_current_user)):
    """Issue a short-lived (5 min) signed query for embedding the photo in <img src>."""
    photo = await db.photos.find_one(
        {"photo_id": photo_id, "user_id": user["user_id"], "is_deleted": False}, {"_id": 0}
    )
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    sig, exp = make_photo_signature(photo_id, user["user_id"])
    return {"sig": sig, "exp": exp, "user_id": user["user_id"]}


@router.get("/{photo_id}/file")
async def download_photo(
    photo_id: str,
    request: Request,
    sig: Optional[str] = Query(None),
    exp: Optional[int] = Query(None),
    uid: Optional[str] = Query(None),
):
    """Serve photo bytes.

    Auth options (security SEC-002 — never accept session_token in URL):
      1) Authenticated request via cookie / Bearer header (preferred — used by the React app).
      2) Short-lived signed URL via ?sig=&exp=&uid= (HMAC over photo_id+user_id+exp, 5 min TTL),
         for `<img src>` embedding where you can't send headers/cookies cleanly.
    """
    photo = await db.photos.find_one({"photo_id": photo_id, "is_deleted": False}, {"_id": 0})
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    authorized = False
    if sig and exp and uid:
        if uid == photo["user_id"] and verify_photo_signature(photo_id, uid, exp, sig):
            authorized = True
    if not authorized:
        # Try session auth (cookie or Bearer) — reuse the same middleware
        try:
            session_user = await get_current_user(request)
            if session_user["user_id"] == photo["user_id"]:
                authorized = True
        except HTTPException:
            pass

    if not authorized:
        raise HTTPException(status_code=401, detail="Not authorized for this photo")

    try:
        data, ctype = get_object(photo["storage_path"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Fetch failed: {exc!s}") from exc
    return Response(content=data, media_type=photo.get("content_type", ctype))
