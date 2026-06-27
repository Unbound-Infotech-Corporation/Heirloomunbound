"""Post-purchase fulfillment — public endpoints that complete the buyer journey.

These routes are reachable WITHOUT authentication; they authorise via
single-purpose tokens minted by the billing flow:

  GET  /api/download/{download_token}      → serves the personalized .zip
  POST /api/auth/magic/{magic_token}       → consumes a magic-link, returns session token
  POST /api/webhook/stripe                  → Stripe webhook (signature-verified)

Idempotency: download tokens have max_uses + expires_at; magic_links are
single-shot (consumed=true after one use).
"""
from __future__ import annotations

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from emergentintegrations.payments.stripe.checkout import StripeCheckout
from fastapi import APIRouter, HTTPException, Request, Response

from deps import db
from routers.billing import _provision_after_payment
from routers.companion import build_windows_zip_bytes

router = APIRouter(tags=["fulfillment"])

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ---------------- Personalized download ----------------
@router.get("/download/{download_token}")
async def download(download_token: str):
    if not download_token or not download_token.startswith("dl_"):
        raise HTTPException(status_code=404, detail="Invalid download token")
    rec = await db.download_tokens.find_one({"download_token": download_token}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Download not found")

    # Expiry
    try:
        exp = datetime.fromisoformat(rec.get("expires_at", ""))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        exp = _now()
    if _now() > exp:
        raise HTTPException(status_code=410, detail="Download link has expired")

    uses = int(rec.get("uses", 0))
    max_uses = int(rec.get("max_uses", 1))
    if uses >= max_uses:
        raise HTTPException(status_code=410, detail="Download link exhausted")

    payload = build_windows_zip_bytes(rec["device_token"], wake_word=False)

    await db.download_tokens.update_one(
        {"download_token": download_token},
        {"$inc": {"uses": 1}, "$set": {"last_used_at": _now_iso()}},
    )

    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="HeirloomCompanion-Windows.zip"',
            "Cache-Control": "no-store",
        },
    )


# ---------------- Magic-link login ----------------
@router.post("/auth/magic/{magic_token}")
async def consume_magic_link(magic_token: str, response: Response):
    if not magic_token or not magic_token.startswith("ml_"):
        raise HTTPException(status_code=400, detail="Invalid magic-link")
    rec = await db.magic_links.find_one({"magic_token": magic_token}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Magic-link not found")
    if rec.get("consumed"):
        raise HTTPException(status_code=410, detail="Magic-link already used")
    try:
        exp = datetime.fromisoformat(rec.get("expires_at", ""))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        exp = _now()
    if _now() > exp:
        raise HTTPException(status_code=410, detail="Magic-link has expired")

    user = await db.users.find_one({"user_id": rec["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User no longer exists")

    # Mint a real session token (same shape as Emergent Google auth path)
    session_token = f"sess_{uuid.uuid4().hex}{secrets.token_urlsafe(16)}"
    await db.user_sessions.insert_one({
        "user_id": user["user_id"],
        "session_token": session_token,
        "expires_at": (_now() + timedelta(days=7)).isoformat(),
        "issued_via": "magic_link",
        "created_at": _now_iso(),
    })

    # Burn the magic-link so it can't be reused
    await db.magic_links.update_one(
        {"magic_token": magic_token},
        {"$set": {"consumed": True, "consumed_at": _now_iso()}},
    )

    # Cookie for the SPA's auth state (same as auth.py)
    response.set_cookie(
        key="session_token",
        value=session_token,
        max_age=7 * 24 * 3600,
        httponly=True,
        samesite="none",
        secure=True,
    )

    return {
        "session_token": session_token,
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "name": user.get("name", ""),
            "picture": user.get("picture", ""),
        },
    }


# ---------------- Stripe webhook ----------------
@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    body = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    host_url = str(request.base_url)

    sc = StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=f"{host_url.rstrip('/')}/api/webhook/stripe")
    try:
        evt = await sc.handle_webhook(body, sig)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Webhook verification failed: {exc!s}") from exc

    session_id = getattr(evt, "session_id", None)
    payment_status = getattr(evt, "payment_status", "")

    if session_id and payment_status == "paid":
        # Re-pull the canonical status so we can pass amounts/metadata
        status_obj = await sc.get_checkout_status(session_id)
        await _provision_after_payment(session_id, status_obj)

    return {"received": True}
