"""Contacts book for the mobile PWA.

Small per-user address book so `/m/call` can list family + friends and let the
owner one-tap a Twin-initiated outbound call in the contact's name.

Two paths for populating it:
  * Manual `POST /contacts {name, phone, note?}`
  * vCard import `POST /contacts/import-vcard` — accepts a .vcf upload and
    parses out FN + TEL entries. Multi-vcard files supported.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from deps import db, get_current_user

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_phone(raw: str) -> str:
    """Very light E.164-ish normalisation — keeps a leading + and digits only."""
    raw = (raw or "").strip()
    plus = raw.startswith("+")
    digits = re.sub(r"[^\d]", "", raw)
    return ("+" if plus else "") + digits


class Contact(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=6, max_length=20)
    note: Optional[str] = Field(default=None, max_length=200)


@router.get("")
async def list_contacts(user: dict = Depends(get_current_user)):
    docs = await db.contacts.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("name", 1).to_list(length=500)
    return {"contacts": docs}


@router.post("")
async def create_contact(payload: Contact, user: dict = Depends(get_current_user)):
    phone = _normalize_phone(payload.phone)
    if len(re.sub(r"\D", "", phone)) < 6:
        raise HTTPException(400, "Phone number looks too short")
    doc = {
        "contact_id": uuid.uuid4().hex[:12],
        "user_id": user["user_id"],
        "name": payload.name.strip(),
        "phone": phone,
        "note": (payload.note or "").strip() or None,
        "created_at": _now(),
    }
    await db.contacts.insert_one(doc)
    doc.pop("_id", None)
    return {"contact": doc}


@router.delete("/{contact_id}")
async def delete_contact(contact_id: str, user: dict = Depends(get_current_user)):
    res = await db.contacts.delete_one(
        {"user_id": user["user_id"], "contact_id": contact_id}
    )
    if res.deleted_count == 0:
        raise HTTPException(404, "Contact not found")
    return {"ok": True}


@router.post("/import-vcard")
async def import_vcard(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """Parse a vCard file (.vcf) and insert every recognised (name, phone)
    pair. Duplicates by exact phone are skipped."""
    raw = (await file.read()).decode("utf-8", errors="ignore")
    if not raw.strip():
        raise HTTPException(400, "Empty vCard file")

    cards = re.split(r"(?im)BEGIN:VCARD", raw)[1:]
    imported = []
    existing_phones = {
        c["phone"] for c in await db.contacts.find(
            {"user_id": user["user_id"]}, {"_id": 0, "phone": 1}
        ).to_list(length=1000)
    }

    for card in cards:
        # FN takes precedence; fall back to N (last;first).
        fn_match = re.search(r"(?im)^FN[^:]*:(.+)$", card)
        n_match = re.search(r"(?im)^N[^:]*:(.+)$", card)
        tel_matches = re.findall(r"(?im)^TEL[^:]*:(.+)$", card)

        if fn_match:
            name = fn_match.group(1).strip()
        elif n_match:
            parts = [p.strip() for p in n_match.group(1).split(";") if p.strip()]
            name = " ".join(reversed(parts)) if len(parts) > 1 else parts[0] if parts else "Unknown"
        else:
            name = "Unknown"

        for tel in tel_matches:
            phone = _normalize_phone(tel)
            if len(re.sub(r"\D", "", phone)) < 6:
                continue
            if phone in existing_phones:
                continue
            existing_phones.add(phone)
            doc = {
                "contact_id": uuid.uuid4().hex[:12],
                "user_id": user["user_id"],
                "name": name[:80],
                "phone": phone,
                "note": None,
                "source": "vcard",
                "created_at": _now(),
            }
            await db.contacts.insert_one(doc)
            imported.append({"name": doc["name"], "phone": doc["phone"]})

    return {"ok": True, "imported": len(imported), "contacts": imported}
