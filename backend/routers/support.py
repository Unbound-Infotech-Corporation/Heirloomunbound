"""Heirloom Unbound support tickets from the companion Terminal."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from deps import db
from email_service import send_support_ticket_email
from routers.studio import get_studio_user
from support_ticket import (
    build_ticket_snapshot,
    mailto_href,
    new_ticket_id,
    redact_text,
    snapshot_json,
)

router = APIRouter(prefix="/support", tags=["support"])


class TicketReq(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=4000)
    email: Optional[str] = Field(default=None, max_length=200)
    probe: Optional[dict] = None
    model_map: Optional[dict] = None
    compute: Optional[dict] = None
    log_lines: Optional[list[str]] = None
    os: Optional[str] = Field(default=None, max_length=200)
    build_id: Optional[str] = Field(default=None, max_length=80)
    companion_version: Optional[str] = Field(default=None, max_length=40)


@router.post("/ticket")
async def create_support_ticket(payload: TicketReq, user: dict = Depends(get_studio_user)):
    """Store a redacted snapshot and try Resend. Offline clients use mailto + copy."""
    ticket_id = new_ticket_id()
    email = redact_text((payload.email or user.get("email") or "").strip())[:200]
    subject = redact_text(payload.subject.strip())
    message = redact_text(payload.message.strip())
    snapshot = build_ticket_snapshot(
        os_name=payload.os,
        build_id=payload.build_id,
        companion_version=payload.companion_version,
        probe=payload.probe,
        model_map=payload.model_map,
        compute=payload.compute,
        log_lines=payload.log_lines or [],
    )
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "ticket_id": ticket_id,
        "user_id": user.get("user_id"),
        "email": email,
        "subject": subject,
        "message": message,
        "snapshot": snapshot,
        "created_at": now,
        "source": "companion_terminal",
        "product": "Heirloom Unbound",
    }
    await db.support_tickets.insert_one(doc)
    mailed = await send_support_ticket_email(
        ticket_id=ticket_id,
        subject=subject,
        body=message,
        reply_to=email,
        snapshot_text=snapshot_json(snapshot),
    )
    queued = not mailed.get("skipped") and not mailed.get("error")
    return {
        "ok": True,
        "ticket_id": ticket_id,
        "queued": queued,
        "email": email,
        "mailto": mailto_href(ticket_id=ticket_id, subject=subject, email=email, snapshot=snapshot),
        "snapshot": snapshot,
        "hint": (
            f"ticket {ticket_id} queued"
            if queued
            else f"ticket {ticket_id} saved — copy the bundle or use mailto if mail is offline"
        ),
    }
