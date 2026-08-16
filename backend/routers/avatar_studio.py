"""Avatar Studio — upload + enhance + local Pinokio/ComfyUI twin.

Photos: front, left, right, three-quarter, and a full-body shot. D-ID still
uses the front image as a paid talking-head fallback. The local path queues
jobs onto the home PC (LivePortrait look-at-you, EchoMimic talk, InstantID
still) the same way Ollama downloads do.

Storage: Emergent's object store, paths under `heirloom/avatars/{user_id}/`.
D-ID compatibility: we serve via /avatar-studio/serve/{path:path} — gated by
`auth` query param so the D-ID worker can pull. Tokens are 24h-lived.
"""
from __future__ import annotations

import io
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

import fal_client
import requests
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from deps import db, get_current_user
from routers.companion import get_device_user
from routers.oauth import public_mail_status
from services.avatar_jobs import public_job, queue_job, queue_setup
from services.avatar_recipes import (
    ENGINES,
    assert_setup_payload_safe,
    is_known_angle,
    is_known_engine,
    normalize_body,
    public_catalog,
)
from twin_tools import _active_device, _device_is_awake

router = APIRouter(prefix="/avatar-studio", tags=["avatar-studio"])

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
APP_NAME = "heirloom"
FAL_KEY = os.environ.get("FAL_KEY", "").strip()
MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 12 MB — full-body shots are larger than faces

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


def _detect_image_content_type(raw: bytes, content_type: str = "") -> str:
    """Prefer magic bytes so a Windows photo picker can send the wrong MIME."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if len(raw) >= 3 and raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    ct = (content_type or "").lower().split(";", 1)[0].strip()
    if ct in ("image/jpg", "image/pjpeg"):
        return "image/jpeg"
    return ct


async def store_avatar_bytes(
    user: dict,
    angle: str,
    raw: bytes,
    content_type: str = "",
) -> dict:
    """Save a still photo for the talking twin. House page and Windows first-run card."""
    if not is_known_angle(angle):
        raise HTTPException(status_code=400, detail="angle must be front|left|right|three_quarter|full")
    angle = angle.strip().lower()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"Image too big (>{MAX_IMAGE_BYTES//1024//1024} MB)")
    ct = _detect_image_content_type(raw, content_type)
    if ct not in ("image/jpeg", "image/png", "image/webp"):
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
    if angle == "front":
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"avatar_source_url": public_url, "updated_at": _now_iso()}},
        )
    return {
        "ok": True,
        "image_id": img_id,
        "angle": angle,
        "serve_url": public_url,
        "avatar_source_url": public_url if angle == "front" else (user.get("avatar_source_url") or ""),
        "size": doc["size"],
        "active": angle == "front",
    }


@router.post("/upload")
async def upload_avatar(
    angle: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Upload one reference image. Angle ∈ front|left|right|three_quarter|full."""
    raw = await file.read()
    return await store_avatar_bytes(user, angle, raw, file.content_type or "")


def _public_url_for(doc: dict) -> str:
    base = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
    return f"{base}/api/avatar-studio/serve/{doc['storage_path']}?t={doc['serve_token']}"


# ---------------- List + Save ----------------
@router.get("/me")
async def get_my_avatars(user: dict = Depends(get_current_user)):
    """Return current photos, body sheet, engine, and home-PC readiness."""
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
    dev = await _active_device(user["user_id"])
    engine = (user.get("avatar_engine") or "auto").strip().lower()
    if engine not in ENGINES:
        engine = "auto"
    recent = (
        await db.avatar_jobs.find({"user_id": user["user_id"]}, {"_id": 0})
        .sort("created_at", -1)
        .to_list(length=12)
    )
    last_setup = await db.avatar_jobs.find_one(
        {"user_id": user["user_id"], "kind": "setup"},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    catalog = public_catalog()
    setup = dict(catalog.get("setup") or {})
    setup["consent_at"] = user.get("avatar_setup_consent_at") or ""
    setup["last_job"] = public_job(last_setup) if last_setup else None
    has_front = bool(by_angle.get("front"))
    seen = bool(dev and dev.get("last_seen"))
    online = _device_is_awake(dev)
    if not dev:
        home_next = "Download Heirloom for the home computer (Local PC in the sidebar), unzip it, and double-click Heirloom.bat."
    elif not seen:
        home_next = "On the home computer, double-click Heirloom.bat. This page will say ready when it is."
    elif not online:
        home_next = f"Open the Heirloom app on {dev.get('name') or 'the computer at home'}."
    elif not has_front:
        home_next = "Add a photo of your face looking at the camera."
    else:
        home_next = f"{dev.get('name') or 'Your computer'} is ready."
    return {
        "active_source_url": user.get("avatar_source_url") or "",
        "front": by_angle.get("front"),
        "left": by_angle.get("left"),
        "right": by_angle.get("right"),
        "three_quarter": by_angle.get("three_quarter"),
        "full": by_angle.get("full"),
        "by_angle": by_angle,
        "body": normalize_body(user.get("avatar_body") if isinstance(user.get("avatar_body"), dict) else {}),
        "engine": engine,
        "fal_configured": bool((user.get("fal_api_key") or "").strip() or FAL_KEY),
        "fal_using_user_key": bool((user.get("fal_api_key") or "").strip()),
        "home": {
            "connected": bool(dev),
            "online": online,
            "seen": seen,
            "name": (dev or {}).get("name") or "",
            "next": home_next,
        },
        "jobs": [public_job(j) for j in recent],
        "catalog": catalog,
        "setup": setup,
        "mail": await public_mail_status(user["user_id"]),
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
            "fal-ai/codeformer",
            arguments={"image_url": data_url, "fidelity": 0.7},
        )
        result = await handler.get()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"fal.ai failed: {exc!s}") from exc

    enhanced_url = (result or {}).get("image", {}).get("url") if isinstance(result, dict) else None
    if not enhanced_url:
        raise HTTPException(status_code=400, detail="fal.ai returned no image")

    # Pull the enhanced bytes + blend with original by `strength` to preserve identity
    er = requests.get(enhanced_url, timeout=60)
    if er.status_code >= 400:
        raise HTTPException(status_code=400, detail="Couldn't fetch fal.ai output")
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


# ---------------- Body sheet + engine + recipes ----------------
class BodySheetIn(BaseModel):
    height_cm: Optional[int] = None
    weight_kg: Optional[int] = None
    build: str = "average"
    presentation: str = "unspecified"
    notes: str = ""


@router.put("/body")
async def save_body(payload: BodySheetIn, user: dict = Depends(get_current_user)):
    body = normalize_body(payload.model_dump())
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"avatar_body": body, "updated_at": _now_iso()}},
    )
    return {"body": body}


class EngineIn(BaseModel):
    engine: str = Field(..., min_length=3, max_length=12)


@router.put("/engine")
async def save_engine(payload: EngineIn, user: dict = Depends(get_current_user)):
    engine = payload.engine.strip().lower()
    if not is_known_engine(engine):
        raise HTTPException(400, "engine must be auto|local|did")
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"avatar_engine": engine, "updated_at": _now_iso()}},
    )
    return {"engine": engine}


@router.get("/recipes")
async def list_recipes(user: dict = Depends(get_current_user)):
    _ = user  # auth-gated so we don't leak install URLs to anonymous scrapers
    return public_catalog()


@router.post("/setup")
async def start_easy_setup(payload: dict, user: dict = Depends(get_current_user)):
    """One permission checkbox, then the home PC downloads official Pinokio.

    We never collect Pinokio / ComfyUI / Hugging Face logins. Those programs
    run locally and do not need accounts.
    """
    if not isinstance(payload, dict):
        raise HTTPException(400, "Tick the box so we know you want this on your computer.")
    try:
        assert_setup_payload_safe(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return await queue_setup(user, consent=True)


class CreateJobIn(BaseModel):
    kind: str
    recipe_id: str = ""
    text: str = ""
    body: Optional[dict] = None


@router.post("/jobs")
async def create_job(payload: CreateJobIn, user: dict = Depends(get_current_user)):
    """Queue a still / talk / look job on the home PC."""
    return await queue_job(
        user,
        kind=payload.kind,
        recipe_id=payload.recipe_id,
        text=payload.text,
        body_override=payload.body,
    )


@router.get("/jobs")
async def list_jobs(user: dict = Depends(get_current_user), limit: int = 20):
    limit = max(1, min(int(limit or 20), 50))
    rows = (
        await db.avatar_jobs.find({"user_id": user["user_id"]}, {"_id": 0})
        .sort("created_at", -1)
        .to_list(length=limit)
    )
    return [public_job(r) for r in rows]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    doc = await db.avatar_jobs.find_one(
        {"job_id": job_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Job not found")
    return public_job(doc)


@router.get("/companion-file/{image_id}")
async def companion_avatar_file(image_id: str, auth: dict = Depends(get_device_user)):
    """Device-token download of the owner's own avatar photo."""
    user_id = auth["user"]["user_id"]
    row = await db.avatar_images.find_one(
        {"image_id": image_id, "user_id": user_id, "is_deleted": False},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "Image not found")
    data, ct = _get_object(row["storage_path"])
    return Response(content=data, media_type=row.get("content_type") or ct or "image/jpeg")


MAX_RESULT_BYTES = 48 * 1024 * 1024


def _detect_media_mime(head: bytes, filename: str) -> str:
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if len(head) >= 3 and head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if len(head) >= 8 and head[4:8] == b"ftyp":
        return "video/mp4"
    if head[:4] == b"\x1aE\xdf\xa3":
        return "video/webm"
    lower = (filename or "").lower()
    if lower.endswith(".mp4"):
        return "video/mp4"
    if lower.endswith(".webm"):
        return "video/webm"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".wav"):
        return "audio/wav"
    raise HTTPException(415, "result is not a recognised image or video")


@router.post("/jobs/{job_id}/result")
async def submit_job_result(
    job_id: str,
    file: UploadFile = File(...),
    auth: dict = Depends(get_device_user),
):
    user_id = auth["user"]["user_id"]
    job = await db.avatar_jobs.find_one({"job_id": job_id, "user_id": user_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if job.get("status") == "complete" and job.get("result_path"):
        return {"ok": True, "job_id": job_id, "already_complete": True}
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty result")
    if len(content) > MAX_RESULT_BYTES:
        raise HTTPException(413, "Result too large")
    ct = _detect_media_mime(content[:32], file.filename or "")
    ext = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "video/mp4": "mp4",
        "video/webm": "webm",
        "audio/wav": "wav",
    }.get(ct, "bin")
    path = f"{APP_NAME}/avatars/{user_id}/jobs/{job_id}.{ext}"
    meta = _put_object(path, content, ct)
    now = _now_iso()
    await db.avatar_jobs.update_one(
        {"job_id": job_id, "user_id": user_id},
        {"$set": {
            "status": "complete",
            "result_path": meta.get("path") or path,
            "result_content_type": ct,
            "updated_at": now,
        }},
    )
    return {"ok": True, "job_id": job_id, "content_type": ct}


class JobNoteIn(BaseModel):
    message: str = ""
    reason: str = ""


@router.post("/jobs/{job_id}/note")
async def job_note(job_id: str, body: JobNoteIn, auth: dict = Depends(get_device_user)):
    """Companion finished preparing the folder / opened Pinokio — no media file."""
    user_id = auth["user"]["user_id"]
    now = _now_iso()
    res = await db.avatar_jobs.update_one(
        {
            "job_id": job_id,
            "user_id": user_id,
            "status": {"$in": ["queued", "dispatched", "processing"]},
        },
        {"$set": {
            "status": "done",
            "result_text": (body.message or "")[:2000],
            "updated_at": now,
        }},
    )
    if res.matched_count == 0:
        exists = await db.avatar_jobs.find_one({"job_id": job_id, "user_id": user_id}, {"_id": 1})
        if not exists:
            raise HTTPException(404, "Job not found")
    return {"ok": True}


@router.post("/jobs/{job_id}/fail")
async def job_fail(job_id: str, body: JobNoteIn, auth: dict = Depends(get_device_user)):
    user_id = auth["user"]["user_id"]
    reason = (body.reason or body.message or "unknown error")[:500]
    now = _now_iso()
    res = await db.avatar_jobs.update_one(
        {
            "job_id": job_id,
            "user_id": user_id,
            "status": {"$in": ["queued", "dispatched", "processing"]},
        },
        {"$set": {"status": "error", "result_text": reason, "updated_at": now}},
    )
    if res.matched_count == 0:
        exists = await db.avatar_jobs.find_one({"job_id": job_id, "user_id": user_id}, {"_id": 1})
        if not exists:
            raise HTTPException(404, "Job not found")
    return {"ok": True}


@router.get("/jobs/{job_id}/file")
async def serve_job_file(job_id: str, t: str = Query("")):
    if not t:
        raise HTTPException(401, "Missing token")
    row = await db.avatar_jobs.find_one(
        {"job_id": job_id, "serve_token": t},
        {"_id": 0},
    )
    if not row or not row.get("result_path"):
        raise HTTPException(404, "Not found")
    data, ct = _get_object(row["result_path"])
    return Response(
        content=data,
        media_type=row.get("result_content_type") or ct,
        headers={"Cache-Control": "private, max-age=3600"},
    )
