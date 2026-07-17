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

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from emergentintegrations.payments.stripe.checkout import StripeCheckout
from fastapi import APIRouter, HTTPException, Request, Response

from deps import db
from routers.billing import _provision_after_payment
from routers.companion import build_one_click_installer_zip_bytes

router = APIRouter(tags=["fulfillment"])

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")
STRIPE_PAYMENT_LINK_ID = os.environ.get("STRIPE_PAYMENT_LINK_ID", "")


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

    # Grandmother-friendly one-click zip (installs Python if needed, pulls
    # newest script from the server, tray + auto-start). Advanced zip remains
    # available from the Companion page as "Companion .zip".
    payload = build_one_click_installer_zip_bytes(rec["device_token"], wake_word=False)

    await db.download_tokens.update_one(
        {"download_token": download_token},
        {"$inc": {"uses": 1}, "$set": {"last_used_at": _now_iso()}},
    )

    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="Install-Heirloom.zip"',
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

    # Also parse the raw payload so we can read fields the wrapper doesn't
    # surface (customer_details.email, payment_link, etc.) — needed for
    # Stripe Payment Link purchases that don't carry our app metadata.
    try:
        raw = json.loads(body.decode("utf-8"))
        raw_obj = (raw.get("data") or {}).get("object", {}) or {}
    except Exception:  # noqa: BLE001
        raw_obj = {}

    # Event-level idempotency — Stripe retries the same event id many times.
    # We dedupe at the event level (not just session level) so retries are free.
    event_id = getattr(evt, "event_id", None) or getattr(evt, "id", None)
    event_type = getattr(evt, "event_type", None) or getattr(evt, "type", "checkout.session.completed")
    if event_id:
        existing = await db.stripe_events.find_one({"event_id": event_id}, {"_id": 1})
        if existing:
            return {"received": True, "duplicate": True}
        await db.stripe_events.insert_one({
            "event_id": event_id,
            "event_type": event_type,
            "received_at": _now_iso(),
        })

    session_id = getattr(evt, "session_id", None)
    payment_status = getattr(evt, "payment_status", "")

    # --- checkout.session.completed → provision ---
    if session_id and payment_status == "paid":
        # Pull customer email + payment_link id from raw payload (Payment Link
        # purchases put the buyer's email here, not in our metadata).
        customer_details = raw_obj.get("customer_details") or {}
        customer_email = (
            customer_details.get("email")
            or raw_obj.get("customer_email")
            or ""
        )
        customer_name = customer_details.get("name") or ""
        payment_link_id = raw_obj.get("payment_link") or ""

        # Defense in depth: if this session came from a Payment Link, ensure
        # it's *our* Payment Link. (Doesn't reject — just logs — in case the
        # user later adds more links.)
        if payment_link_id and STRIPE_PAYMENT_LINK_ID and payment_link_id != STRIPE_PAYMENT_LINK_ID:
            print(f"[stripe webhook] payment_link mismatch: got {payment_link_id}, expected {STRIPE_PAYMENT_LINK_ID}")

        source = "payment_link" if payment_link_id else "checkout_session"
        # Stripe webhooks MUST NEVER raise — Stripe will retry-storm. Wrap the
        # whole retrieve+provision path and just log failures; idempotency is
        # preserved by the stripe_events insert above so retries dedupe.
        try:
            status_obj = await sc.get_checkout_status(session_id)
            await _provision_after_payment(
                session_id,
                status_obj,
                email_override=customer_email or None,
                name_override=customer_name or None,
                source=source,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[stripe webhook] provision failed for {session_id}: {exc}")

    # --- charge.refunded / dispute → revoke access ---
    if event_type in {"charge.refunded", "charge.dispute.created", "charge.dispute.funds_withdrawn"}:
        await _revoke_access_for_event(evt)

    return {"received": True}


async def _revoke_access_for_event(evt) -> None:
    """Mark the user's account as refunded/disputed and revoke companion access.

    We do NOT auto-delete the archive (the customer's data is sensitive — if
    the refund was a mistake we want to be able to restore). We just flag the
    account so the buy-success page shows a banner and the companion devices
    stop polling successfully.
    """
    # Try to find the transaction this refund references
    charge_id = getattr(evt, "charge_id", None) or getattr(evt, "id", None)
    metadata = getattr(evt, "metadata", {}) or {}
    session_id = metadata.get("checkout_session_id") or getattr(evt, "session_id", None)

    txn = None
    if session_id:
        txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not txn and charge_id:
        txn = await db.payment_transactions.find_one({"charge_id": charge_id}, {"_id": 0})
    if not txn:
        print(f"[stripe webhook] refund event with no matching txn: charge={charge_id}, session={session_id}")
        return

    uid = txn.get("user_id")
    if not uid:
        return

    await db.users.update_one(
        {"user_id": uid},
        {"$set": {
            "account_status": "refunded",
            "refunded_at": _now_iso(),
            "refund_event_type": getattr(evt, "event_type", None) or getattr(evt, "type", "refund"),
        }},
    )
    # Revoke every companion device so the local PCs stop being able to poll
    await db.companion_devices.update_many(
        {"user_id": uid},
        {"$set": {"revoked": True, "revoked_reason": "refunded", "revoked_at": _now_iso()}},
    )
    # Invalidate active sessions
    await db.user_sessions.delete_many({"user_id": uid})
    print(f"[stripe webhook] revoked access for {uid} due to refund/dispute")


# ---------------- Webhook setup info (for the dashboard config) ----------------
@router.get("/billing/webhook-info")
async def webhook_info(request: Request):
    """Show the URL + events the operator needs to register in the Stripe Dashboard.

    Use:
      Stripe Dashboard → Developers → Webhooks → Add endpoint → paste `url`
      → tick the events listed below → save → copy the signing secret into
      backend env as STRIPE_WEBHOOK_SECRET.
    """
    base = (
        os.environ.get("PUBLIC_BACKEND_URL", "").strip().rstrip("/")
        or str(request.base_url).rstrip("/")
    )
    return {
        "webhook_url": f"{base}/api/webhook/stripe",
        "events_to_listen_for": [
            "checkout.session.completed",
            "charge.refunded",
            "charge.dispute.created",
            "charge.dispute.funds_withdrawn",
        ],
        "payment_link_id": STRIPE_PAYMENT_LINK_ID,
        "payment_link_url": os.environ.get("STRIPE_PAYMENT_LINK_URL", ""),
        "test_mode": STRIPE_API_KEY.startswith("sk_test"),
        "configured": bool(STRIPE_API_KEY),
        "webhook_secret_configured": bool(os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()),
    }
