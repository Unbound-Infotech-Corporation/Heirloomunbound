"""Email-related endpoints (test send, etc)."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from deps import db, get_current_user
from email_service import send_magic_link_email

router = APIRouter(prefix="/email", tags=["email"])


class TestReq(BaseModel):
    to: EmailStr


@router.post("/test")
async def send_test(req: TestReq, user: dict = Depends(get_current_user)):
    """Owner-only: send a sample welcome email to a recipient of your choice.

    Useful for verifying the Resend integration end-to-end and confirming
    your `from` domain renders the way you want. Resend test mode only
    delivers to the email address that owns the Resend account.
    """
    backend_url = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
    # Provision a dummy magic-link + download just to fill the template.
    result = await send_magic_link_email(
        to=req.to,
        name=user.get("name", "Friend"),
        login_url="/auth/magic/ml_test_token_visual_only",
        download_url="/api/download/dl_test_token_visual_only",
        backend_url=backend_url,
    )
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    if "skipped" in result:
        raise HTTPException(status_code=503, detail=result.get("reason", "email service not configured"))
    return {"sent": True, "id": result.get("id"), "to": req.to}


@router.get("/status")
async def status(user: dict = Depends(get_current_user)):
    """Surface email config to the Settings page."""
    return {
        "configured": bool(os.environ.get("RESEND_API_KEY")),
        "sender_email": os.environ.get("SENDER_EMAIL", ""),
        "sender_name": os.environ.get("SENDER_NAME", "Heirloom"),
        "test_mode": os.environ.get("SENDER_EMAIL", "") == "onboarding@resend.dev",
    }
