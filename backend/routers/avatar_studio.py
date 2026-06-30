"""Avatar Studio — upload + enhance + save the user's twin face.

Three angles per user (front + left + right). Today D-ID only uses the front
image; sides are stored for a future 3D-avatar upgrade. Subtle enhancement
runs through fal.ai's identity-preserving face restorer (GFPGAN-style model)
— OFF by default, slider 0-100, side-by-side preview before commit.

Storage: Emergent's object store, paths under `heirloom/avatars/{user_id}/`.
All access goes through this router (no public URLs leaked to S3-like CDNs).

D-ID compatibility: D-ID requires the source_url to be publicly fetchable.
We serve via /avatar-studio/serve/{path:path} — gated by `auth` query param
so the D-ID worker can pull. Tokens are 24h-lived and stored alongside the
avatar metadata.
"""
from __future__ import annotations

import io
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

import fal_client
import requests
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from deps import db, get_current_user

router = APIRouter(prefix="/avatar-studio", tags=["avatar-studio"])

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
APP_NAME = "heirloom"
FAL_KEY = os.environ.get("FAL_KEY", "").strip()
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB

# Module-level storage_key (init-once per process)
_STORAGE_KEY: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _init_storage() -> str:
    global _STORAGE_KEY
    if _STORAGE_KEY:
        return _STORAGE_KEY
    if not EMERGENT_KEY:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY not configured")
    r = requests.post(
        f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30
    )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Storage init {r.status_code}: {r.text[:200]}")
    _STORAGE_KEY = r.json()["storage_key"]
    return _STORAGE_KEY


def _put_object(path: str, data: bytes, content_type: str) -> dict:
    key = _init_storage()
    r = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data,
        timeout=120,
    )
    if r.status_code == 403:
        # Storage key expired — re-init once and retry
        global _STORAGE_KEY
        _STORAGE_KEY = None
        key = _init_storage()
        r = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data,
            timeout=120,
        )
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Storage put {r.status_code}: {r.text[:200]}")
    return r.json()


def _get_object(path: str) -> tuple[bytes, str]:
    key = _init_storage()
    r = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key},
        timeout=60,
    )
    if r.status_code == 403:
        global _STORAGE_KEY
        _STORAGE_KEY = None
        key = _init_storage()
        r = requests.get(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key},
            timeout=60,
        )
    if r.status_code >= 400:
        raise HTTPException(status_code=404, detail=f"Object missing: {r.status_code}")
    return r.content, r.headers.get("Content-Type", "application/octet-stream")


# ---------------- Upload ----------------
ANGLE = Literal["front", "left", "right"]


@router.post("/upload")
async def upload_avatar(
    angle: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Upload one face image — angle ∈ {front, left, right}. Stored under the
    user's avatar folder; the DB row is the source of truth."""
    if angle not in ("front", "left", "right"):
        raise HTTPException(status_code=400, detail="angle must be front|left|right")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"Image too big (>{MAX_IMAGE_BYTES//1024//1024} MB)")
    ct = (file.content_type or "").lower()
    if not ct.startswith("image/") or ct not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status_code=400, detail="Only JPEG, PNG, WEBP accepted")
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[ct]

    img_id = uuid.uuid4().hex[:14]
    path = f"{APP_NAME}/avatars/{user['user_id']}/{angle}_{img_id}.{ext}"
    result = _put_object(path, raw, ct)

    # Mint a 24h read token so D-ID workers can fetch this via /serve
    serve_token = secrets.token_urlsafe(24)

    doc = {
        "image_id": img_id,
        "user_id": user["user_id"],
        "angle": angle,
        "storage_path": result["path"],
        "content_type": ct,
        "size": result["size"],
        "serve_token": serve_token,
        "is_enhanced": False,
        "is_deleted": False,
        "created_at": _now_iso(),
    }
    await db.avatar_images.insert_one(dict(doc))

    # Soft-deprecate any previous image at this angle (for the same user)
    await db.avatar_images.update_many(
        {
            "user_id": user["user_id"],
            "angle": angle,
            "image_id": {"$ne": img_id},
            "is_deleted": False,
        },
        {"$set": {"is_deleted": True, "deleted_at": _now_iso()}},
    )

    public_url = _public_url_for(doc)
    return {
        "image_id": img_id,
        "angle": angle,
        "serve_url": public_url,
        "size": doc["size"],
    }


def _public_url_for(doc: dict) -> str:
    base = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
    return f"{base}/api/avatar-studio/serve/{doc['storage_path']}?t={doc['serve_token']}"


# ---------------- List + Save ----------------
@router.get("/me")
async def get_my_avatars(user: dict = Depends(get_current_user)):
    """Return the user's current front/left/right plus what's selected as
    the active D-ID avatar source."""
    rows = (
        await db.avatar_images.find(
            {"user_id": user["user_id"], "is_deleted": False},
            {"_id": 0},
        )
        .sort("created_at", -1)
        .to_list(length=60)
    )
    by_angle: dict[str, dict] = {}
    for r in rows:
        if r["angle"] not in by_angle:
            by_angle[r["angle"]] = {
                "image_id": r["image_id"],
                "angle": r["angle"],
                "serve_url": _public_url_for(r),
                "is_enhanced": r.get("is_enhanced", False),
                "created_at": r["created_at"],
            }
    return {
        "active_source_url": user.get("avatar_source_url") or "",
        "front": by_angle.get("front"),
        "left": by_angle.get("left"),
        "right": by_angle.get("right"),
        "fal_configured": bool((user.get("fal_api_key") or "").strip() or FAL_KEY),
        "fal_using_user_key": bool((user.get("fal_api_key") or "").strip()),
    }


class FalKeyReq(BaseModel):
    api_key: str


@router.put("/api-key")
async def set_fal_key(payload: FalKeyReq, user: dict = Depends(get_current_user)):
    """Save the user's personal fal.ai key (overrides admin key for this user)."""
    key = (payload.api_key or "").strip()
    if not key:
        await db.users.update_one(
            {"user_id": user["user_id"]}, {"$unset": {"fal_api_key": ""}}
        )
        return {"has_user_key": False}
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"fal_api_key": key, "updated_at": _now_iso()}},
    )
    return {"has_user_key": True}


@router.delete("/api-key")
async def clear_fal_key(user: dict = Depends(get_current_user)):
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$unset": {"fal_api_key": ""}}
    )
    return {"has_user_key": False}


class SaveActiveReq(BaseModel):
    image_id: str


@router.post("/use")
async def use_avatar(body: SaveActiveReq, user: dict = Depends(get_current_user)):
    """Set this image as the active D-ID source for the user."""
    row = await db.avatar_images.find_one(
        {"image_id": body.image_id, "user_id": user["user_id"], "is_deleted": False},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")
    url = _public_url_for(row)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"avatar_source_url": url, "updated_at": _now_iso()}},
    )
    return {"avatar_source_url": url}


# ---------------- Enhance (fal.ai) ----------------
class EnhanceReq(BaseModel):
    image_id: str
    strength: float = 0.5  # 0..1, frontend's 0..100 slider scaled down


@router.post("/enhance")
async def enhance_avatar(body: EnhanceReq, user: dict = Depends(get_current_user)):
    """Run the front image through fal.ai's identity-preserving restorer and
    save the result as a NEW image (the original stays untouched)."""
    user_fal = (user.get("fal_api_key") or "").strip()
    effective_key = user_fal or FAL_KEY
    if not effective_key:
        raise HTTPException(
            status_code=400,
            detail="Beautify is unavailable — add your fal.ai key in Settings → Keys & Integrations.",
        )
    os.environ["FAL_KEY"] = effective_key  # fal_client reads from env at request time

    row = await db.avatar_images.find_one(
        {"image_id": body.image_id, "user_id": user["user_id"], "is_deleted": False},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Image not found")

    # Strength clamped 0..1 — anything beyond ~0.6 starts to look airbrushed
    strength = max(0.0, min(0.85, float(body.strength)))

    original, ct = _get_object(row["storage_path"])

    # Upload to fal as a data URL (faster than presigned for <8MB)
    data_url = fal_client.encode(original, ct)

    try:
        handler = await fal_client.submit_async(
            "fal-ai/gfpgan",
            arguments={"image_url": data_url},
        )
        result = await handler.get()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"fal.ai failed: {exc!s}") from exc

    enhanced_url = (result or {}).get("image", {}).get("url") if isinstance(result, dict) else None
    if not enhanced_url:
        raise HTTPException(status_code=502, detail="fal.ai returned no image")

    # Pull the enhanced bytes + blend with original by `strength` to preserve identity
    er = requests.get(enhanced_url, timeout=60)
    if er.status_code >= 400:
        raise HTTPException(status_code=502, detail="Couldn't fetch fal.ai output")
    enhanced_bytes = er.content

    if strength < 0.99:
        try:
            blended = _blend_images(original, enhanced_bytes, alpha=strength)
            if blended:
                enhanced_bytes = blended
        except Exception:  # noqa: BLE001
            pass  # Fall back to full-strength output if PIL fails

    new_id = uuid.uuid4().hex[:14]
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(ct, "jpg")
    path = f"{APP_NAME}/avatars/{user['user_id']}/{row['angle']}_enh_{new_id}.{ext}"
    result_meta = _put_object(path, enhanced_bytes, ct)

    doc = {
        "image_id": new_id,
        "user_id": user["user_id"],
        "angle": row["angle"],
        "storage_path": result_meta["path"],
        "content_type": ct,
        "size": result_meta["size"],
        "serve_token": secrets.token_urlsafe(24),
        "is_enhanced": True,
        "parent_image_id": row["image_id"],
        "strength": strength,
        "is_deleted": False,
        "created_at": _now_iso(),
    }
    await db.avatar_images.insert_one(dict(doc))
    return {
        "image_id": new_id,
        "angle": row["angle"],
        "serve_url": _public_url_for(doc),
        "strength": strength,
        "is_enhanced": True,
    }


def _blend_images(orig: bytes, enhanced: bytes, *, alpha: float) -> Optional[bytes]:
    """Pixel-blend the two images at `alpha` so the user can dial in how much
    enhancement they want. alpha=0 → original, alpha=1 → fully enhanced."""
    try:
        from PIL import Image
    except ImportError:
        return None
    o = Image.open(io.BytesIO(orig)).convert("RGB")
    e = Image.open(io.BytesIO(enhanced)).convert("RGB").resize(o.size)
    out = Image.blend(o, e, max(0.0, min(1.0, alpha)))
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ---------------- Public serve (token-gated) ----------------
@router.get("/serve/{storage_path:path}")
async def serve_avatar(storage_path: str, t: str = Query("")):
    """Public endpoint — gated by the `t` token so D-ID's worker can fetch
    without a session cookie, but random scrapers can't."""
    if not t:
        raise HTTPException(status_code=401, detail="Missing token")
    row = await db.avatar_images.find_one(
        {"storage_path": storage_path, "serve_token": t, "is_deleted": False},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    data, ct = _get_object(storage_path)
    return Response(
        content=data,
        media_type=row.get("content_type", ct),
        headers={"Cache-Control": "public, max-age=86400"},
    )
