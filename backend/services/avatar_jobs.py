"""Queue local Pinokio/ComfyUI twin jobs onto the home PC."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from deps import db
from routers.providers import _load_with_secrets as load_providers
from services.avatar_recipes import (
    SIMPLE_SETUP,
    default_recipe_for,
    is_known_kind,
    recipe_for,
    still_prompt,
)
from twin_tools import _active_device, _device_is_awake, _queue_pc_command


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def current_images(user_id: str) -> list[dict]:
    rows = (
        await db.avatar_images.find(
            {"user_id": user_id, "is_deleted": False},
            {"_id": 0, "image_id": 1, "angle": 1, "created_at": 1},
        )
        .sort("created_at", -1)
        .to_list(length=60)
    )
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        ang = r.get("angle") or ""
        if ang in seen:
            continue
        seen.add(ang)
        out.append({"image_id": r["image_id"], "angle": ang})
    return out


async def queue_job(
    user: dict,
    *,
    kind: str,
    recipe_id: str = "",
    text: str = "",
    body_override: Optional[dict] = None,
) -> dict:
    """Insert an avatar_jobs row and enqueue the matching companion command."""
    kid = (kind or "").strip().lower()
    if not is_known_kind(kid):
        raise HTTPException(400, "kind must be still|talk|look")
    recipe = recipe_for(recipe_id) if recipe_id else default_recipe_for(kid)
    if recipe_id and not recipe:
        raise HTTPException(400, f"unknown recipe '{recipe_id}'")
    if not recipe:
        recipe = default_recipe_for(kid)
    if recipe["kind"] != kid:
        # Allow a look recipe only for look jobs, etc.
        raise HTTPException(400, f"recipe '{recipe['id']}' is a {recipe['kind']} tool, not {kid}")

    images = await current_images(user["user_id"])
    if not images:
        raise HTTPException(
            400,
            "Add a clear photo of your face first — looking at the camera.",
        )
    has_front = any(i.get("angle") == "front" for i in images)
    if not has_front:
        raise HTTPException(400, "Add a photo of your face looking at the camera. That is the one the twin uses.")

    dev = await _active_device(user["user_id"])
    if not dev:
        raise HTTPException(
            409,
            "Open the Heirloom app on the computer at home first. The twin lives there, not in the cloud.",
        )

    body = body_override if isinstance(body_override, dict) else (
        user.get("avatar_body") if isinstance(user.get("avatar_body"), dict) else {}
    )
    prompt = still_prompt(body)
    if text:
        prompt = f"{prompt} Speaking: {text[:400]}"

    providers = await load_providers(user["user_id"])
    image_cfg = providers.get("image") or {}
    tts_cfg = providers.get("tts") or {}

    job_id = f"avt_{uuid.uuid4().hex[:12]}"
    now = _now()
    cmd_kind = {"still": "avatar_still", "talk": "avatar_talk", "look": "avatar_look"}[kid]
    payload = {
        "job_id": job_id,
        "kind": kid,
        "recipe_id": recipe["id"],
        "pinokio_url": recipe.get("pinokio_url") or "",
        "prompt": prompt,
        "text": (text or "")[:2000],
        "images": images,
        "provider": {
            "base_url": (image_cfg.get("base_url") or "").rstrip("/"),
            "api_key": image_cfg.get("api_key") or "",
            "model": image_cfg.get("model") or "",
            "provider_type": image_cfg.get("provider_type") or "comfyui",
            "comfy_workflow": image_cfg.get("comfy_workflow") or "",
            "enabled": bool(image_cfg.get("enabled")),
        },
        "tts": {
            "enabled": bool(tts_cfg.get("enabled")),
            "base_url": (tts_cfg.get("base_url") or "").rstrip("/"),
            "api_key": tts_cfg.get("api_key") or "",
            "model": tts_cfg.get("model") or "",
            "voice": tts_cfg.get("voice") or "",
        },
    }
    cmd_id = await _queue_pc_command(user["user_id"], cmd_kind, payload)
    serve_token = secrets.token_urlsafe(24)
    doc = {
        "job_id": job_id,
        "user_id": user["user_id"],
        "kind": kid,
        "recipe_id": recipe["id"],
        "cmd_id": cmd_id,
        "status": "queued",
        "text": (text or "")[:2000],
        "prompt": prompt,
        "home_online": _device_is_awake(dev),
        "serve_token": serve_token,
        "result_path": None,
        "result_content_type": None,
        "result_text": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.avatar_jobs.insert_one(dict(doc))
    doc.pop("_id", None)
    doc.pop("serve_token", None)
    doc["poll"] = f"/api/avatar-studio/jobs/{job_id}"
    doc["howto"] = recipe.get("howto") or ""
    doc["recipe_label"] = recipe.get("label") or recipe["id"]
    if not doc["home_online"]:
        doc["hint"] = (
            f"{dev.get('name') or 'Your PC'} will start this the next time the desktop app is open."
        )
    else:
        doc["hint"] = recipe.get("howto") or ""
    return doc


async def queue_setup(user: dict, *, consent: bool) -> dict:
    """One permission, then the home PC downloads official Pinokio. No accounts."""
    if not consent:
        raise HTTPException(400, "Tick the box so we know you want this on your computer.")

    dev = await _active_device(user["user_id"])
    if not dev:
        raise HTTPException(
            409,
            "Open the Heirloom app on the computer at home first. We install the free tools there.",
        )

    images = await current_images(user["user_id"])
    job_id = f"avt_{uuid.uuid4().hex[:12]}"
    now = _now()
    current_engine = (user.get("avatar_engine") or "auto").strip().lower()
    user_patch: dict = {"avatar_setup_consent_at": now, "updated_at": now}
    if current_engine in ("", "auto"):
        user_patch["avatar_engine"] = "local"
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": user_patch})

    payload = {
        "job_id": job_id,
        "apps": list(SIMPLE_SETUP.get("apps") or []),
        "images": images,
    }
    cmd_id = await _queue_pc_command(user["user_id"], "avatar_setup", payload)
    serve_token = secrets.token_urlsafe(24)
    doc = {
        "job_id": job_id,
        "user_id": user["user_id"],
        "kind": "setup",
        "recipe_id": "easy-setup",
        "cmd_id": cmd_id,
        "status": "queued",
        "text": "",
        "prompt": "",
        "home_online": _device_is_awake(dev),
        "serve_token": serve_token,
        "result_path": None,
        "result_content_type": None,
        "result_text": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.avatar_jobs.insert_one(dict(doc))
    doc.pop("_id", None)
    doc.pop("serve_token", None)
    doc["poll"] = f"/api/avatar-studio/jobs/{job_id}"
    doc["howto"] = SIMPLE_SETUP.get("windows_note") or ""
    doc["recipe_label"] = SIMPLE_SETUP.get("title") or "Set up my twin"
    if not doc["home_online"]:
        doc["hint"] = (
            f"Open {dev.get('name') or 'the Heirloom app'} on the home computer. "
            "Then we download Pinokio for you."
        )
    else:
        doc["hint"] = (
            "Leave the Heirloom app open. If Windows shows a blue box, click More info, then Run anyway."
        )
    return doc


def job_file_url(doc: dict) -> Optional[str]:
    if not doc.get("result_path"):
        return None
    import os

    base = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
    token = doc.get("serve_token") or ""
    return f"{base}/api/avatar-studio/jobs/{doc['job_id']}/file?t={token}"


def public_job(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k not in ("_id", "serve_token")}
    out["result_url"] = job_file_url(doc) if doc.get("result_path") else None
    out["done"] = doc.get("status") in ("done", "complete", "error")
    out["ok"] = doc.get("status") in ("done", "complete")
    return out
