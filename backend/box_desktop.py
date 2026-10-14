"""Desktop API auth for a Twin Box client.

A paired companion still uses its device token. On the box, the Windows app
signs in as the owner and calls Twin, speak, and clones with that session.
Companion poll stays on the device token, so a session cannot pull PC commands.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, HTTPException, Request

from deps import db, get_current_user
from owner_pairing import is_owner_audience

BOX_CLIENT_DEVICE = "box-client"


def client_chat_mode(mode: str | None, device_id: str | None) -> str:
    """The box client never runs Assist. PC tools stay on the Windows PC."""
    resolved = (mode or "twin").strip().lower() or "twin"
    if device_id == BOX_CLIENT_DEVICE and resolved in {"assistant", "owner"}:
        return "twin"
    return resolved


async def resolve_desktop_user(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing device token")
    token = authorization.split(" ", 1)[1].strip()
    device = await db.companion_devices.find_one({"device_token": token, "revoked": False}, {"_id": 0})
    if device:
        user = await db.users.find_one({"user_id": device["user_id"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        await db.companion_devices.update_one(
            {"device_id": device["device_id"]},
            {"$set": {"last_seen": datetime.now(timezone.utc).isoformat()}},
        )
        return {"user": user, "device": device}

    from box_owner import box_mode

    if not box_mode():
        raise HTTPException(status_code=401, detail="Invalid device token")
    user = await get_current_user(request)
    if user.get("heir_surface") or not is_owner_audience(user.get("audience") or "owner"):
        raise HTTPException(status_code=401, detail="Owner sign-in required")
    return {
        "user": user,
        "device": {
            "device_id": BOX_CLIENT_DEVICE,
            "user_id": user.get("user_id"),
            "name": "Twin Box client",
            "kind": "pc",
        },
    }
