"""Legacy Continuity — inheritance package, death-watch, desktop heartbeat.

The end goal of Heirloom is a twin close enough to give to heirs after the
owner passes. This router exposes:

1. GET  /legacy/status          — death-watch dashboard (inactivity, devices, heirs)
2. POST /legacy/heartbeat       — device-auth heartbeat (desktop app)
3. GET  /legacy/export          — downloadable Inheritance Package (JSON zip)
4. POST /legacy/check-in        — owner check-in (same effect as /heirs/check-in)
5. PUT  /legacy/settings        — inactivity defaults / export preferences
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from deps import db, get_current_user
from routers.companion import get_device_user

router = APIRouter(prefix="/legacy", tags=["legacy"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


@router.get("/status")
async def legacy_status(user: dict = Depends(get_current_user)):
    """Death-watch + readiness summary for the Legacy Continuity page."""
    uid = user["user_id"]
    now = _now()

    devices = await db.companion_devices.find(
        {"user_id": uid, "revoked": {"$ne": True}}, {"_id": 0}
    ).to_list(length=20)

    last_device_seen: Optional[datetime] = None
    online = []
    for d in devices:
        seen = _parse_iso(d.get("last_seen"))
        if seen and (last_device_seen is None or seen > last_device_seen):
            last_device_seen = seen
        online.append({
            "device_id": d.get("device_id"),
            "name": d.get("name") or "Companion",
            "last_seen": d.get("last_seen"),
            "online": bool(seen and (now - seen) < timedelta(minutes=3)),
        })

    last_check_in = _parse_iso(user.get("legacy_last_check_in") or user.get("last_check_in"))
    # Prefer the freshest signal between explicit check-in and desktop heartbeat.
    freshest = last_check_in
    if last_device_seen and (freshest is None or last_device_seen > freshest):
        freshest = last_device_seen

    heirs = await db.heirs.find({"user_id": uid}, {"_id": 0, "release_token": 0}).to_list(length=50)
    entry_count = await db.entries.count_documents({"user_id": uid})
    fact_count = await db.memory_facts.count_documents({"user_id": uid})
    has_personality = bool(
        await db.personality_profiles.find_one({"user_id": uid}, {"_id": 1})
    )
    voice_cfg = await db.elevenlabs_settings.find_one({"user_id": uid}, {"_id": 0}) or {}
    has_voice = bool(voice_cfg.get("voice_id") or user.get("elevenlabs_voice_id"))

    default_inactivity = int(user.get("legacy_inactivity_days") or 30)
    days_since = None
    if freshest:
        days_since = round((now - freshest).total_seconds() / 86400, 1)

    readiness = {
        "archive_entries": entry_count,
        "identity_facts": fact_count,
        "personality_profile": has_personality,
        "voice_clone": has_voice,
        "heirs_designated": len(heirs),
        "desktop_connected": any(d["online"] for d in online),
        "score": 0,
    }
    # Simple 0-100 readiness heuristic for the Continuity page.
    score = 0
    score += min(40, entry_count)  # up to 40 for archive depth
    score += 15 if has_personality else 0
    score += 15 if fact_count >= 3 else (8 if fact_count else 0)
    score += 15 if has_voice else 0
    score += 10 if heirs else 0
    score += 5 if readiness["desktop_connected"] else 0
    readiness["score"] = min(100, score)

    return {
        "last_check_in": freshest.isoformat() if freshest else None,
        "days_since_presence": days_since,
        "inactivity_days_default": default_inactivity,
        "devices": online,
        "heirs": [
            {
                "heir_id": h.get("heir_id"),
                "name": h.get("name"),
                "relationship": h.get("relationship"),
                "released": bool(h.get("released")),
                "inactivity_days": h.get("inactivity_days"),
                "release_on": h.get("release_on"),
            }
            for h in heirs
        ],
        "readiness": readiness,
        "legacy_message": user.get("legacy_message") or "",
    }


class LegacySettings(BaseModel):
    inactivity_days_default: Optional[int] = Field(default=None, ge=7, le=3650)
    legacy_message: Optional[str] = None


@router.put("/settings")
async def update_legacy_settings(payload: LegacySettings, user: dict = Depends(get_current_user)):
    update: dict = {}
    if payload.inactivity_days_default is not None:
        update["legacy_inactivity_days"] = int(payload.inactivity_days_default)
    if payload.legacy_message is not None:
        update["legacy_message"] = payload.legacy_message.strip()[:4000]
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": update})
    return {"ok": True, **update}


@router.post("/check-in")
async def legacy_check_in(user: dict = Depends(get_current_user)):
    """Owner explicitly confirms they are alive — resets inactivity clocks."""
    now = _now_iso()
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"legacy_last_check_in": now, "last_check_in": now}},
    )
    # Also bump every heir's last_check_in so inactivity triggers reset.
    await db.heirs.update_many(
        {"user_id": user["user_id"], "released": {"$ne": True}},
        {"$set": {"last_check_in": now}},
    )
    return {"ok": True, "checked_in_at": now}


@router.post("/heartbeat")
async def legacy_heartbeat(ctx: dict = Depends(get_device_user)):
    """Desktop app heartbeat — strengthens death-watch beyond opportunistic poll."""
    now = _now_iso()
    device = ctx["device"]
    user = ctx["user"]
    await db.companion_devices.update_one(
        {"device_id": device["device_id"]},
        {"$set": {"last_seen": now, "heartbeat_at": now}},
    )
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"legacy_last_check_in": now}},
    )
    return {"ok": True, "at": now}


@router.get("/export")
async def export_legacy_package(user: dict = Depends(get_current_user)):
    """Build an Inheritance Package zip the owner can store offline / give to heirs.

    Contents (JSON + README) — no raw ElevenLabs audio blobs (those live with
    the provider). Includes everything needed to ground a twin offline or to
    re-seed a new Heirloom instance.
    """
    return await _build_export_response(user)


@router.get("/export-device")
async def export_legacy_package_device(ctx: dict = Depends(get_device_user)):
    """Same Inheritance Package, authenticated via companion device token.

    Used by the Windows desktop app so the owner can export without opening
    a browser session.
    """
    return await _build_export_response(ctx["user"])


async def _build_export_response(user: dict):
    uid = user["user_id"]
    now = _now()

    entries = await db.entries.find({"user_id": uid}, {"_id": 0}).to_list(length=10000)
    facts = await db.memory_facts.find({"user_id": uid}, {"_id": 0}).to_list(length=2000)
    episodes = await db.memory_episodes.find({"user_id": uid}, {"_id": 0}).to_list(length=500)
    personality = await db.personality_profiles.find_one({"user_id": uid}, {"_id": 0})
    letters = await db.sealed_letters.find({"user_id": uid}, {"_id": 0}).to_list(length=500)
    heirs = await db.heirs.find(
        {"user_id": uid},
        {"_id": 0, "release_token": 0},
    ).to_list(length=50)
    voice = await db.elevenlabs_settings.find_one(
        {"user_id": uid},
        {"_id": 0, "api_key": 0},  # never export the API key
    )
    photos_meta = await db.photos.find(
        {"user_id": uid},
        {"_id": 0, "storage_path": 0},
    ).to_list(length=2000)

    package = {
        "format": "heirloom.legacy.v1",
        "exported_at": now.isoformat(),
        "owner": {
            "user_id": uid,
            "name": user.get("name", ""),
            "preferred_name": user.get("preferred_name") or user.get("name", ""),
            "email": user.get("email", ""),
            "safe_topics": user.get("safe_topics") or [],
            "brand_name": user.get("brand_name") or "",
            "brand_tagline": user.get("brand_tagline") or "",
            "brand_signoff": user.get("brand_signoff") or "",
            "tts_language": user.get("tts_language") or "auto",
            "profile": user.get("profile") or {},
            "legacy_message": user.get("legacy_message") or "",
        },
        "counts": {
            "entries": len(entries),
            "facts": len(facts),
            "episodes": len(episodes),
            "letters": len(letters),
            "heirs": len(heirs),
            "photos": len(photos_meta),
        },
        "personality": personality,
        "identity_facts": facts,
        "episodic_memory": episodes,
        "entries": entries,
        "sealed_letters": letters,
        "heirs": heirs,
        "voice_clone": {
            "configured": bool((voice or {}).get("voice_id") or user.get("elevenlabs_voice_id")),
            "voice_id": (voice or {}).get("voice_id") or user.get("elevenlabs_voice_id"),
            "voice_name": (voice or {}).get("voice_name") or "",
            "note": "Audio samples are not included. Re-bind the ElevenLabs voice_id on a new account to restore spoken voice.",
        },
        "photos": photos_meta,
    }

    readme = f"""Heirloom Inheritance Package
=============================

Exported: {now.date().isoformat()}
Owner: {package['owner']['preferred_name'] or package['owner']['name']}
Format: heirloom.legacy.v1

This package is a portable snapshot of everything that makes the twin feel like
{package['owner']['preferred_name'] or 'the owner'}:

  • archive entries (memories, stories, values, advice, quotes, journals)
  • long-term identity facts and episodic conversation summaries
  • structured personality portrait (Big Five, voice tone, relationships)
  • sealed letters and designated heirs
  • voice-clone metadata (re-bind ElevenLabs voice_id to restore spoken voice)

How heirs should use this
-------------------------
1. Keep this zip somewhere safe (USB drive, family cloud, attorney escrow).
2. If the live Heirloom portal is still available, prefer that — it streams the
   living twin with the same fidelity this package was built from.
3. If the cloud service is gone, import `legacy.json` into a new Heirloom
   instance or any offline twin runner that understands heirloom.legacy.v1.

Counts: {package['counts']}

— Heirloom · Unbound Infotech
"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", readme)
        zf.writestr(
            "legacy.json",
            json.dumps(package, ensure_ascii=False, indent=2, default=str),
        )
    buf.seek(0)

    filename = f"heirloom-legacy-{now.strftime('%Y%m%d')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
