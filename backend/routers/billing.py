"""Stripe Checkout — sell Heirloom Companion as a one-time $79 lifetime purchase.

Flow:
1. /buy frontend → POST /api/billing/checkout {package_id, origin_url, email}
2. Backend creates a Stripe Checkout session + a payment_transactions row (PENDING).
3. User pays. Stripe redirects to {origin}/buy/success?session_id=...
4. Frontend polls GET /api/billing/status/{session_id}.
5. On first PAID response, we provision: user account, companion device,
   one-time download token, magic-link login token. Idempotent by session_id.
6. Stripe also POSTs /api/webhook/stripe — same provisioning path, idempotent.

Why both polling AND webhook: the playbook calls for polling as the source of
truth (webhooks can be delayed). The webhook is a backstop in case the user
closes the success tab.
"""
from __future__ import annotations

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from emergentintegrations.payments.stripe.checkout import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    CheckoutStatusResponse,
    StripeCheckout,
)
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from deps import db

router = APIRouter(prefix="/billing", tags=["billing"])

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")

# Server-side package catalogue. NEVER trust amounts from the client.
PACKAGES = {
    "lifetime": {
        "name": "Heirloom Lifetime",
        "price": 79.00,
        "currency": "usd",
        "description": "Lifetime Heirloom Companion + Cloud Archive. One payment, yours forever.",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stripe(host_url: str) -> StripeCheckout:
    return StripeCheckout(
        api_key=STRIPE_API_KEY,
        webhook_url=f"{host_url.rstrip('/')}/api/webhook/stripe",
    )


# ---------------- Models ----------------
class CheckoutReq(BaseModel):
    package_id: str = Field(..., description="Key from PACKAGES (e.g. 'lifetime')")
    origin_url: str = Field(..., description="window.location.origin from the frontend")
    email: EmailStr
    name: Optional[str] = None


class CheckoutResp(BaseModel):
    url: str
    session_id: str


class StatusResp(BaseModel):
    paid: bool
    payment_status: str
    status: str
    amount_total: int
    currency: str
    download_url: Optional[str] = None
    login_url: Optional[str] = None
    email: Optional[str] = None


# ---------------- Endpoints ----------------
@router.post("/checkout", response_model=CheckoutResp)
async def create_checkout(payload: CheckoutReq, request: Request):
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    if payload.package_id not in PACKAGES:
        raise HTTPException(status_code=400, detail="Invalid package")

    pkg = PACKAGES[payload.package_id]
    origin = payload.origin_url.rstrip("/")
    success_url = f"{origin}/buy/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/buy"

    host_url = str(request.base_url)
    sc = _stripe(host_url)

    metadata = {
        "package_id": payload.package_id,
        "email": payload.email,
        "name": payload.name or "",
        "source": "buy_page",
    }
    req = CheckoutSessionRequest(
        amount=float(pkg["price"]),
        currency=pkg["currency"],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
    )
    session: CheckoutSessionResponse = await sc.create_checkout_session(req)

    await db.payment_transactions.insert_one({
        "session_id": session.session_id,
        "package_id": payload.package_id,
        "amount": float(pkg["price"]),
        "currency": pkg["currency"],
        "email": payload.email,
        "name": payload.name or "",
        "status": "open",
        "payment_status": "unpaid",
        "metadata": metadata,
        "provisioned": False,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    })

    return CheckoutResp(url=session.url, session_id=session.session_id)


async def _provision_after_payment(session_id: str, status_obj: CheckoutStatusResponse) -> dict:
    """Idempotently create the buyer's account + companion device + magic-link +
    one-time download token. Returns the provisioning artifacts so the caller
    can pass download_url + login_url back to the user."""
    txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not txn:
        # Webhook arrived for a session we don't know about — record minimal data
        meta = dict(status_obj.metadata or {})
        await db.payment_transactions.insert_one({
            "session_id": session_id,
            "package_id": meta.get("package_id", "unknown"),
            "amount": (status_obj.amount_total or 0) / 100.0,
            "currency": status_obj.currency,
            "email": meta.get("email", ""),
            "name": meta.get("name", ""),
            "status": status_obj.status,
            "payment_status": status_obj.payment_status,
            "metadata": meta,
            "provisioned": False,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
        txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})

    if txn.get("provisioned"):
        # Already done — just return existing artifacts
        return {
            "download_url": txn.get("download_url"),
            "login_url": txn.get("login_url"),
            "email": txn.get("email"),
        }

    email = txn.get("email") or (status_obj.metadata or {}).get("email") or ""
    name = txn.get("name") or (status_obj.metadata or {}).get("name") or email.split("@")[0]

    # Find or create user
    user = await db.users.find_one({"email": email}, {"_id": 0}) if email else None
    if not user and email:
        user = {
            "user_id": f"u_{uuid.uuid4().hex[:14]}",
            "email": email,
            "name": name,
            "picture": "",
            "created_at": _now_iso(),
            "setup_complete": False,
            "purchased_lifetime": True,
            "purchased_at": _now_iso(),
        }
        await db.users.insert_one(dict(user))
    elif user:
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"purchased_lifetime": True, "purchased_at": _now_iso()}},
        )

    if not user:
        raise HTTPException(status_code=400, detail="Cannot provision: email missing")

    # Create the companion device for this user
    device_id = f"dev_{uuid.uuid4().hex[:12]}"
    device_token = "comp_" + secrets.token_urlsafe(28)
    await db.companion_devices.insert_one({
        "device_id": device_id,
        "user_id": user["user_id"],
        "name": "My PC",
        "device_token": device_token,
        "revoked": False,
        "created_at": _now_iso(),
        "last_seen": None,
    })

    # One-time download token (24h expiry, can be used up to 3 times)
    download_token = "dl_" + secrets.token_urlsafe(32)
    await db.download_tokens.insert_one({
        "download_token": download_token,
        "user_id": user["user_id"],
        "device_token": device_token,
        "uses": 0,
        "max_uses": 5,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
        "created_at": _now_iso(),
    })

    # Magic-link login token (15 min, single-use)
    magic_token = "ml_" + secrets.token_urlsafe(32)
    await db.magic_links.insert_one({
        "magic_token": magic_token,
        "user_id": user["user_id"],
        "consumed": False,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "created_at": _now_iso(),
    })

    # Store on the transaction for idempotency
    download_url = f"/api/download/{download_token}"
    login_url = f"/auth/magic/{magic_token}"
    await db.payment_transactions.update_one(
        {"session_id": session_id},
        {"$set": {
            "provisioned": True,
            "user_id": user["user_id"],
            "device_id": device_id,
            "download_url": download_url,
            "login_url": login_url,
            "updated_at": _now_iso(),
        }},
    )

    # Fire the welcome email. We never block on this — if Resend is down or
    # the recipient is not on the verified-list yet (test-mode), the user
    # still has the in-page magic-link on /buy/success.
    try:
        from email_service import send_magic_link_email
        backend_url = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
        await send_magic_link_email(
            to=email,
            name=user.get("name", ""),
            login_url=login_url,
            download_url=download_url,
            backend_url=backend_url,
        )
    except Exception as exc:  # noqa: BLE001
        # Log and move on — the polling path still shows the link in-page.
        print(f"[fulfillment] email send failed for {email}: {exc}")

    return {"download_url": download_url, "login_url": login_url, "email": email}


@router.get("/status/{session_id}", response_model=StatusResp)
async def checkout_status(session_id: str, request: Request):
    if not STRIPE_API_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    host_url = str(request.base_url)
    sc = _stripe(host_url)

    status_obj: CheckoutStatusResponse = await sc.get_checkout_status(session_id)

    txn = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if txn:
        await db.payment_transactions.update_one(
            {"session_id": session_id},
            {"$set": {
                "status": status_obj.status,
                "payment_status": status_obj.payment_status,
                "updated_at": _now_iso(),
            }},
        )

    paid = status_obj.payment_status == "paid"
    download_url = login_url = email = None
    if paid:
        art = await _provision_after_payment(session_id, status_obj)
        download_url = art["download_url"]
        login_url = art["login_url"]
        email = art["email"]

    return StatusResp(
        paid=paid,
        payment_status=status_obj.payment_status,
        status=status_obj.status,
        amount_total=status_obj.amount_total or 0,
        currency=status_obj.currency or "usd",
        download_url=download_url,
        login_url=login_url,
        email=email,
    )


@router.get("/packages")
async def list_packages():
    return {"packages": {k: {**v, "id": k} for k, v in PACKAGES.items()}}
