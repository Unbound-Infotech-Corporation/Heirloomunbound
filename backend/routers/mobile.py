"""Mobile companion — home-PC archive + optional integration packs.

The phone talks to the same archive the desktop does (Mongo is the shared
store; the home PC is the live hub that last-seen-polls it). Integrations
that are off on the desktop are hidden on the phone — except phone calls,
which are the one mobile-native add-on.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import abilities as ab
from deps import db, get_current_user
from services.phone_packs import phone_enabled_ids, visible_integrations
from twin_tools import _active_device, _device_is_awake

router = APIRouter(prefix="/mobile", tags=["mobile"])


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _counts(user_id: str) -> dict:
    entries = await db.entries.count_documents({"user_id": user_id})
    photos = await db.photos.count_documents({"user_id": user_id, "is_deleted": {"$ne": True}})
    conversations = await db.conversations.count_documents({"user_id": user_id})
    calls = await db.twilio_calls.count_documents({"user_id": user_id})
    return {
        "entries": int(entries),
        "photos": int(photos),
        "conversations": int(conversations),
        "calls": int(calls),
    }


async def _phone_state(user_id: str) -> dict:
    row = await db.mobile_integrations.find_one({"user_id": user_id}, {"_id": 0}) or {}
    return {
        "enabled": sorted(phone_enabled_ids(row)),
        "explicit_off": list(row.get("explicit_off") or []),
    }


@router.get("/home")
async def home(user: dict = Depends(get_current_user)):
    """Status of the home-PC hub + the shared archive the phone is reading."""
    dev = await _active_device(user["user_id"])
    online = _device_is_awake(dev)
    counts = await _counts(user["user_id"])
    twilio = await db.user_twilio.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    return {
        "source": "home-pc" if online else "cloud-relay",
        "message": (
            f"Talking to the archive on {dev.get('name') or 'your home computer'}."
            if online else
            "Home computer is offline — using the last synced archive."
            if dev else
            "Pair the Heirloom desktop app on your home computer so the phone and PC share one archive."
        ),
        "home": {
            "paired": bool(dev),
            "online": online,
            "name": (dev or {}).get("name") or "",
            "last_seen": (dev or {}).get("last_seen"),
            "local_models": list((dev or {}).get("local_models") or []),
        },
        "archive": counts,
        "calls": {
            "configured": bool(twilio.get("phone_number") and twilio.get("account_sid")),
            "phone_number": twilio.get("phone_number") or "",
            "outbound_enabled": bool(twilio.get("outbound_enabled")),
            "webrtc_configured": bool(
                twilio.get("account_sid")
                and twilio.get("api_key_sid")
                and twilio.get("api_key_secret")
                and twilio.get("twiml_app_sid")
            ),
        },
    }


@router.get("/integrations")
async def list_integrations(user: dict = Depends(get_current_user)):
    """Desktop abilities that are actually on, plus the phone-calls pack.

    Hidden: anything the owner turned off (or never enabled) on the desktop.
    The phone does not offer unused desktop integrations — they would just
    waste space. Phone calls are the exception.
    """
    states = await ab.get_states(user["user_id"])
    phone = await _phone_state(user["user_id"])
    items = visible_integrations(ab.ABILITIES, states, {
        "enabled": phone["enabled"],
        "explicit_off": phone["explicit_off"],
    })
    return {
        "integrations": items,
        "note": "Only packs you already use on the desktop show up here, plus phone calls.",
    }


class ToggleIn(BaseModel):
    enabled: bool
    ability_id: Optional[str] = None


@router.put("/integrations/{ability_id}")
async def toggle_integration(ability_id: str, payload: ToggleIn, user: dict = Depends(get_current_user)):
    ability_id = (ability_id or payload.ability_id or "").strip()
    if ability_id == "phone_calls":
        pass
    elif ability_id not in ab.ABILITY_BY_ID:
        raise HTTPException(404, "Unknown integration")
    else:
        states = await ab.get_states(user["user_id"])
        if not states.get(ability_id, {}).get("enabled"):
            raise HTTPException(
                400,
                "Turn this on at the desktop first — the phone only mirrors packs you already use.",
            )

    row = await db.mobile_integrations.find_one({"user_id": user["user_id"]}) or {
        "user_id": user["user_id"],
        "enabled": ["phone_calls"],
        "explicit_off": [],
    }
    enabled = set(row.get("enabled") or [])
    explicit_off = set(row.get("explicit_off") or [])
    if payload.enabled:
        enabled.add(ability_id)
        explicit_off.discard(ability_id)
    else:
        enabled.discard(ability_id)
        if ability_id == "phone_calls":
            explicit_off.add("phone_calls")
    await db.mobile_integrations.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "user_id": user["user_id"],
            "enabled": sorted(enabled),
            "explicit_off": sorted(explicit_off),
            "updated_at": _iso_now(),
        }},
        upsert=True,
    )
    return await list_integrations(user)
