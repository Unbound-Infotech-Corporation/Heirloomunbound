"""Web Push notifications (VAPID).

Lets the mobile PWA wake up when the twin's Twilio number rings so the owner
can jump into the WebRTC leg. Also supports arbitrary in-app notifications.

Flow
----
1. Frontend fetches `GET /api/push/vapid-public-key` and registers the SW.
2. `PushManager.subscribe({applicationServerKey})` yields a subscription.
3. Frontend `POST /api/push/subscribe {endpoint, keys:{p256dh, auth}}`.
4. Server stores it in `push_subscriptions`.
5. Anywhere in the codebase can `await notify_user(user_id, {title, body, url})`
   to fan out a push to every device the user has enrolled.

Dead subscriptions (410 Gone) are auto-pruned.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pywebpush import WebPushException, webpush

from deps import db, get_current_user

router = APIRouter(prefix="/push", tags=["push"])
log = logging.getLogger("push")

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
VAPID_CONTACT = os.environ.get("VAPID_CONTACT_EMAIL", "mailto:support@heirloom.app").strip()


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=8, max_length=256)
    auth: str = Field(min_length=8, max_length=64)


class PushSubscription(BaseModel):
    endpoint: str = Field(min_length=16, max_length=512)
    keys: PushKeys
    user_agent: str | None = Field(default=None, max_length=256)


@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """Public — the frontend needs this before it can subscribe."""
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(500, "Push notifications not configured on server")
    return {"public_key": VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def subscribe(sub: PushSubscription, user: dict = Depends(get_current_user)):
    doc = {
        "user_id": user["user_id"],
        "endpoint": sub.endpoint,
        "p256dh": sub.keys.p256dh,
        "auth": sub.keys.auth,
        "user_agent": sub.user_agent,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Idempotent by (user_id, endpoint) — a repeat subscribe just refreshes.
    await db.push_subscriptions.update_one(
        {"user_id": user["user_id"], "endpoint": sub.endpoint},
        {"$set": doc},
        upsert=True,
    )
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(sub: dict, user: dict = Depends(get_current_user)):
    endpoint = (sub or {}).get("endpoint", "")
    if not endpoint:
        raise HTTPException(400, "endpoint required")
    await db.push_subscriptions.delete_one(
        {"user_id": user["user_id"], "endpoint": endpoint}
    )
    return {"ok": True}


@router.post("/test")
async def send_test_push(user: dict = Depends(get_current_user)):
    """Sends a hello notification to every device this user has enrolled. Handy
    for verifying the PWA install path end-to-end without waiting for a real
    call to come in."""
    sent = await notify_user(
        user["user_id"],
        {
            "title": "Heirloom",
            "body": "Push notifications are working.",
            "url": "/m",
            "tag": "test",
        },
    )
    return {"ok": True, "delivered": sent}


# ---------- shared helper (imported by twilio_voice etc.) ----------
async def notify_user(user_id: str, payload: dict[str, Any]) -> int:
    """Fan-out a Web Push to every registered device for `user_id`.

    Returns the number of successful deliveries. Silently prunes gone endpoints.
    Never raises — a missing VAPID config just no-ops (with a log warning).
    """
    if not (VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY):
        log.warning("Skipping push — VAPID not configured")
        return 0

    subs = await db.push_subscriptions.find(
        {"user_id": user_id}, {"_id": 0}
    ).to_list(length=100)
    if not subs:
        return 0

    delivered = 0
    dead: list[str] = []
    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s["endpoint"],
                    "keys": {"p256dh": s["p256dh"], "auth": s["auth"]},
                },
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_CONTACT},
                ttl=60,
            )
            delivered += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", 0) if e.response is not None else 0
            if status in (404, 410):
                dead.append(s["endpoint"])
            else:
                log.warning("Push failed for %s: %s", s["endpoint"][:40], e)
        except Exception as e:  # noqa: BLE001
            log.warning("Push exception for %s: %s", s["endpoint"][:40], e)

    if dead:
        await db.push_subscriptions.delete_many({"endpoint": {"$in": dead}})
    return delivered
