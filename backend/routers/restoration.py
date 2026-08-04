"""Photo restoration jobs — sends a photo through the user's local ComfyUI
(or any OpenAI-compat image API) for face-restore / colorize / upscale.

Architecture
------------
The user's image provider (from `/api/providers` — `image` subsystem) lives on
their PC at 127.0.0.1. The cloud can't reach it, so restoration is executed by
the desktop companion:

  1. Frontend POSTs /api/restoration/jobs { photo_id, kind } (kind: restore | colorize | upscale)
  2. Backend inserts a `restoration_jobs` doc, enqueues a companion command
     of kind `restore_photo` with the source URL + workflow hint + job_id.
  3. Desktop polls /companion/poll, runs ComfyUI, uploads the result via
     POST /api/restoration/jobs/{id}/result (multipart file).
  4. Backend stores the result as a normal photo entry (`is_restoration=True`)
     and marks the job `complete`.
  5. Frontend polls /api/restoration/jobs/{id} for status.

If the user has no image provider configured, the job stays `queued` — the UI
tells them how to fix it. We never call an external cloud image API by
default: photos are private and we honor the BYOK-strict rule.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from deps import db, get_current_user
from routers.companion import get_device_user
from routers.providers import _load as load_providers
from storage import put_object

router = APIRouter(prefix="/restoration", tags=["restoration"])

APP_PREFIX = "heirloom"

RESTORE_KINDS = ("restore", "colorize", "upscale")


class CreateJobReq(BaseModel):
    photo_id: str
    kind: Literal["restore", "colorize", "upscale"] = "restore"
    prompt_hint: Optional[str] = None


async def _has_active_companion(user_id: str) -> bool:
    doc = await db.companion_devices.find_one(
        {"user_id": user_id, "revoked": {"$ne": True}}, {"_id": 0, "device_id": 1}
    )
    return bool(doc)


@router.post("/jobs")
async def create_job(payload: CreateJobReq, user: dict = Depends(get_current_user)):
    # `kind` is validated by pydantic's Literal — no manual check needed.

    photo = await db.photos.find_one(
        {"photo_id": payload.photo_id, "user_id": user["user_id"], "is_deleted": {"$ne": True}},
        {"_id": 0},
    )
    if not photo:
        raise HTTPException(404, "Photo not found")

    providers = await load_providers(user["user_id"])
    image_cfg = providers.get("image") or {}
    if not image_cfg.get("enabled") or not (image_cfg.get("base_url") or "").strip():
        # We still create the job so the UI can render a clear "configure your
        # image provider first" message — but leave it in `blocked` state.
        state = "blocked"
        reason = "No local image provider configured. Open Settings → Local AI → Image and enable ComfyUI."
    elif not await _has_active_companion(user["user_id"]):
        state = "blocked"
        reason = "No active desktop companion. Install the Heirloom desktop app so it can reach your local ComfyUI."
    else:
        state = "queued"
        reason = None

    job_id = f"rst_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "job_id": job_id,
        "user_id": user["user_id"],
        "photo_id": payload.photo_id,
        "kind": payload.kind,
        "prompt_hint": (payload.prompt_hint or "").strip(),
        "status": state,
        "reason": reason,
        "result_photo_id": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.restoration_jobs.insert_one(doc)
    doc.pop("_id", None)

    # Enqueue a companion command so the desktop starts working immediately.
    if state == "queued":
        cmd = {
            "cmd_id": f"cmd_{uuid.uuid4().hex[:10]}",
            "user_id": user["user_id"],
            "kind": "restore_photo",
            "payload": {
                "job_id": job_id,
                "photo_id": payload.photo_id,
                "kind": payload.kind,
                "prompt_hint": doc["prompt_hint"],
                "provider": {
                    "base_url": (image_cfg.get("base_url") or "").rstrip("/"),
                    "api_key": image_cfg.get("api_key") or "",
                    "model": image_cfg.get("model") or "",
                    "provider_type": image_cfg.get("provider_type") or "comfyui",
                    "comfy_workflow": image_cfg.get("comfy_workflow") or "",
                },
            },
            "status": "queued",
            "result": None,
            "created_at": now,
            "completed_at": None,
        }
        await db.companion_commands.insert_one(cmd)

    return doc


@router.get("/jobs")
async def list_jobs(user: dict = Depends(get_current_user), limit: int = 50):
    limit = max(1, min(int(limit or 50), 200))
    cursor = db.restoration_jobs.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    doc = await db.restoration_jobs.find_one(
        {"job_id": job_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(404, "Job not found")
    return doc


@router.post("/jobs/{job_id}/result")
async def submit_result(
    job_id: str,
    file: UploadFile = File(...),
    auth: dict = Depends(get_device_user),
):
    """Desktop companion uploads the restored image. Stored as a new photo.

    Auth = device_token (only the caller's own PC can post results).
    Idempotent: if the job is already terminal, we return the existing result
    without inserting a second photo.
    """
    user_id = auth["user"]["user_id"]
    job = await db.restoration_jobs.find_one(
        {"job_id": job_id, "user_id": user_id}, {"_id": 0}
    )
    if not job:
        raise HTTPException(404, "Job not found")
    if job.get("status") == "complete" and job.get("result_photo_id"):
        # A retry after a network hiccup — return the already-stored result.
        return {"ok": True, "job_id": job_id, "result_photo_id": job["result_photo_id"], "already_complete": True}

    ext = (file.filename or "restored.png").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        ext = "png"
    result_id = f"ph_{uuid.uuid4().hex[:12]}"
    path = f"{APP_PREFIX}/photos/{user_id}/{result_id}.{ext}"
    content = await file.read()
    put_object(path, content, file.content_type or f"image/{ext}")

    now = datetime.now(timezone.utc).isoformat()
    photo_doc = {
        "photo_id": result_id,
        "user_id": user_id,
        "path": path,
        "caption": f"Restored ({job['kind']}) from {job['photo_id']}",
        "taken_at": None,
        "is_deleted": False,
        "is_restoration": True,
        "source_photo_id": job["photo_id"],
        "restoration_kind": job["kind"],
        "created_at": now,
    }
    await db.photos.insert_one(photo_doc)
    # Only transition to `complete` if still in an in-flight state — protects
    # against a second concurrent upload from mutating the terminal job.
    updated = await db.restoration_jobs.update_one(
        {
            "job_id": job_id, "user_id": user_id,
            "status": {"$in": ["queued", "dispatched", "processing"]},
        },
        {"$set": {"status": "complete", "result_photo_id": result_id, "updated_at": now}},
    )
    if updated.modified_count == 0:
        # Race lost — someone completed the job first. Roll back our insert.
        await db.photos.delete_one({"photo_id": result_id})
        # Return whatever the winner stored.
        winner = await db.restoration_jobs.find_one(
            {"job_id": job_id, "user_id": user_id}, {"_id": 0, "result_photo_id": 1}
        )
        return {"ok": True, "job_id": job_id, "result_photo_id": (winner or {}).get("result_photo_id"), "already_complete": True}
    photo_doc.pop("_id", None)
    return {"ok": True, "job_id": job_id, "result_photo_id": result_id}


@router.post("/jobs/{job_id}/fail")
async def report_failure(
    job_id: str,
    body: dict,
    auth: dict = Depends(get_device_user),
):
    """Desktop reports that the ComfyUI call failed — surface the reason."""
    user_id = auth["user"]["user_id"]
    reason = str(body.get("reason", "unknown error"))[:500]
    now = datetime.now(timezone.utc).isoformat()
    res = await db.restoration_jobs.update_one(
        {
            "job_id": job_id, "user_id": user_id,
            "status": {"$in": ["queued", "dispatched", "processing"]},
        },
        {"$set": {"status": "failed", "reason": reason, "updated_at": now}},
    )
    if res.matched_count == 0:
        # Either wrong owner / non-existent, or already terminal (idempotent no-op).
        exists = await db.restoration_jobs.find_one(
            {"job_id": job_id, "user_id": user_id}, {"_id": 0, "status": 1}
        )
        if not exists:
            raise HTTPException(404, "Job not found")
        return {"ok": True, "already_terminal": True, "status": exists.get("status")}
    return {"ok": True}
