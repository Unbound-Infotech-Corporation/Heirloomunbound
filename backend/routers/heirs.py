"""Heir management — designate people who will inherit access to the Twin.

Release workflow:
- Each heir may have a release_on (ISO date) and/or inactivity_days trigger.
- The user can check-in to push the inactivity clock forward (last_check_in).
- A release sweep (auto-run on dashboard load + manual endpoint) flips
  released=true and mints a release_token when either trigger fires.
- The heir uses that token at /heir/<token> to access the public Heir Portal.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from deps import db, get_current_user

router = APIRouter(prefix="/heirs", tags=["heirs"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


class HeirCreate(BaseModel):
    name: str
    email: EmailStr
    relationship: str = ""
    note: str = ""
    release_on: Optional[str] = None         # ISO date — release after this date
    inactivity_days: Optional[int] = None    # release after N days w/o user check-in


class HeirUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    relationship: Optional[str] = None
    note: Optional[str] = None
    release_on: Optional[str] = None
    inactivity_days: Optional[int] = None
    released: Optional[bool] = None


def _scrub(heir: dict) -> dict:
    """Never expose the release_token to the owning user's heir list response."""
    heir.pop("_id", None)
    heir.pop("release_token", None)
    return heir


@router.post("")
async def add_heir(payload: HeirCreate, user: dict = Depends(get_current_user)):
    heir_id = f"hr_{uuid.uuid4().hex[:10]}"
    doc = {
        "heir_id": heir_id,
        "user_id": user["user_id"],
        "name": payload.name,
        "email": payload.email,
        "relationship": payload.relationship,
        "note": payload.note,
        "release_on": payload.release_on,
        "inactivity_days": payload.inactivity_days,
        "released": False,
        "released_at": None,
        "release_token": None,
        "last_check_in": _now_iso(),
        "created_at": _now_iso(),
    }
    await db.heirs.insert_one(doc)
    return _scrub(dict(doc))


@router.get("")
async def list_heirs(user: dict = Depends(get_current_user)):
    cursor = db.heirs.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(length=200)
    return [_scrub(h) for h in items]


@router.patch("/{heir_id}")
async def update_heir(heir_id: str, payload: HeirUpdate, user: dict = Depends(get_current_user)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.heirs.update_one(
        {"heir_id": heir_id, "user_id": user["user_id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Heir not found")
    doc = await db.heirs.find_one({"heir_id": heir_id}, {"_id": 0})
    return _scrub(doc)


@router.delete("/{heir_id}")
async def delete_heir(heir_id: str, user: dict = Depends(get_current_user)):
    res = await db.heirs.delete_one({"heir_id": heir_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Heir not found")
    return {"ok": True}


# ---------- Release workflow ----------

class CheckIn(BaseModel):
    pass


@router.post("/check-in")
async def check_in(_: CheckIn = None, user: dict = Depends(get_current_user)):
    """User pushes the inactivity clock forward for ALL their heirs."""
    now = _now_iso()
    res = await db.heirs.update_many(
        {"user_id": user["user_id"]},
        {"$set": {"last_check_in": now}},
    )
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"legacy_last_check_in": now, "last_check_in": now}},
    )
    return {"ok": True, "heirs_updated": res.modified_count, "last_check_in": now}


def _should_release(heir: dict, now: datetime, owner_presence: datetime | None = None) -> bool:
    if heir.get("released"):
        return False
    # Date trigger
    rd = heir.get("release_on")
    if rd:
        try:
            target = datetime.fromisoformat(rd)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            if now >= target:
                return True
        except Exception:
            pass
    # Inactivity trigger — use the freshest presence signal (heir check-in OR
    # owner desktop heartbeat / legacy check-in) so a Windows companion that
    # heartbeats daily keeps the twin locked for heirs.
    inactivity = heir.get("inactivity_days")
    last_in = heir.get("last_check_in")
    if inactivity:
        candidates = []
        for raw in (last_in, owner_presence.isoformat() if owner_presence else None):
            if not raw:
                continue
            try:
                dt = raw if isinstance(raw, datetime) else datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                candidates.append(dt)
            except Exception:
                pass
        if owner_presence:
            candidates.append(owner_presence)
        if candidates:
            freshest = max(candidates)
            if now - freshest > timedelta(days=int(inactivity)):
                return True
    return False


async def _owner_presence(user_id: str) -> datetime | None:
    """Freshest signal that the owner is still around (desktop heartbeat / check-in)."""
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "legacy_last_check_in": 1, "last_check_in": 1}) or {}
    best: datetime | None = None
    for key in ("legacy_last_check_in", "last_check_in"):
        raw = user.get(key)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if best is None or dt > best:
                best = dt
        except Exception:
            pass
    cursor = db.companion_devices.find(
        {"user_id": user_id, "revoked": {"$ne": True}},
        {"_id": 0, "last_seen": 1},
    )
    async for d in cursor:
        raw = d.get("last_seen")
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if best is None or dt > best:
                best = dt
        except Exception:
            pass
    return best


async def _do_release(heir: dict) -> str:
    """Mint a token and mark the heir released. Returns the new token."""
    token = "hr_tok_" + secrets.token_urlsafe(28)
    await db.heirs.update_one(
        {"heir_id": heir["heir_id"]},
        {"$set": {
            "released": True,
            "released_at": _now_iso(),
            "release_token": token,
        }},
    )
    # Fire-and-forget the heir release email
    if heir.get("email"):
        try:
            from email_service import send_heir_release_email
            owner = await db.users.find_one({"user_id": heir["user_id"]}, {"name": 1, "_id": 0}) or {}
            frontend = os.environ.get("PUBLIC_FRONTEND_URL", "").rstrip("/")
            portal_url = f"{frontend}/heir/{token}" if frontend else f"/heir/{token}"
            await send_heir_release_email(
                to=heir["email"],
                heir_name=heir.get("name", ""),
                owner_name=owner.get("name", ""),
                portal_url=portal_url,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[heir release] email send failed for {heir.get('email')}: {exc}")
    return token


@router.post("/check-releases")
async def check_releases(user: dict = Depends(get_current_user)):
    """Sweep this user's heirs and release any whose triggers have fired."""
    now = _now()
    presence = await _owner_presence(user["user_id"])
    cursor = db.heirs.find({"user_id": user["user_id"], "released": False}, {"_id": 0})
    candidates = await cursor.to_list(length=200)
    released = []
    for h in candidates:
        if _should_release(h, now, owner_presence=presence):
            token = await _do_release(h)
            released.append({
                "heir_id": h["heir_id"],
                "name": h.get("name"),
                "email": h.get("email"),
                "release_token": token,
                "portal_path": f"/heir/{token}",
            })
    return {"released": released, "checked": len(candidates), "owner_presence": presence.isoformat() if presence else None}


@router.post("/{heir_id}/release-now")
async def release_now(heir_id: str, user: dict = Depends(get_current_user)):
    """Manual override — release this heir immediately and return their portal token."""
    heir = await db.heirs.find_one(
        {"heir_id": heir_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found")
    if heir.get("released") and heir.get("release_token"):
        return {
            "heir_id": heir_id,
            "release_token": heir["release_token"],
            "portal_path": f"/heir/{heir['release_token']}",
            "released_at": heir.get("released_at"),
            "already_released": True,
        }
    token = await _do_release(heir)
    return {
        "heir_id": heir_id,
        "release_token": token,
        "portal_path": f"/heir/{token}",
        "released_at": _now_iso(),
        "already_released": False,
    }


@router.post("/{heir_id}/revoke-release")
async def revoke_release(heir_id: str, user: dict = Depends(get_current_user)):
    """Owner can revoke a previously-released heir (invalidates the token)."""
    res = await db.heirs.update_one(
        {"heir_id": heir_id, "user_id": user["user_id"]},
        {"$set": {"released": False, "released_at": None, "release_token": None}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Heir not found")
    return {"ok": True}


@router.get("/{heir_id}/release-link")
async def get_release_link(heir_id: str, user: dict = Depends(get_current_user)):
    """Return the heir's portal token only after release (for sharing with the heir)."""
    heir = await db.heirs.find_one(
        {"heir_id": heir_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found")
    if not heir.get("released") or not heir.get("release_token"):
        raise HTTPException(status_code=400, detail="Heir has not been released yet")
    return {
        "heir_id": heir_id,
        "release_token": heir["release_token"],
        "portal_path": f"/heir/{heir['release_token']}",
    }
