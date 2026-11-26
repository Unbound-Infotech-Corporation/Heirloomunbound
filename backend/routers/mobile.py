"""Phone companion: pair with a one-time code, then chat, talk and listen through the owner's box.

The phone never runs a model. Chat goes to /api/desktop/chat, voice to /api/companion/voice
(local Whisper on the box), and replies are spoken by the box's local Chatterbox via /mobile/speak.
"""
from __future__ import annotations

import base64
import hashlib
import os
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

import mobile_pairing as mp
from connectors import connectors_allowed
from deps import db, get_current_user
from routers.companion import get_device_user

router = APIRouter(prefix="/mobile", tags=["mobile"])
_LIMITER = mp.FailLimiter()


def _owner_gate(user: dict) -> None:
    if user.get("account_status") == "refunded":
        raise HTTPException(status_code=403, detail="account_inactive")
    if not connectors_allowed(audience=user.get("audience") or "owner", heir_surface=bool(user.get("heir_surface"))):
        raise HTTPException(status_code=403, detail="owner_only")


class MongoPairStore:
    async def open_codes(self, user_id: str, now: datetime) -> int:
        return await db.mobile_pair_codes.count_documents(
            {"user_id": user_id, "used": False, "expires_at": {"$gt": now.isoformat()}})

    async def save_code(self, doc: dict) -> None:
        await db.mobile_pair_codes.insert_one(dict(doc))

    async def take_code(self, hashed: str, now: datetime) -> Optional[dict]:
        row = await db.mobile_pair_codes.find_one_and_update(
            {"code_hash": hashed, "used": False, "expires_at": {"$gt": now.isoformat()}},
            {"$set": {"used": True, "used_at": now.isoformat()}}, projection={"_id": 0})
        return row

    async def save_device(self, doc: dict) -> None:
        await db.companion_devices.insert_one(dict(doc))


def tls_pin() -> str:
    """SPKI SHA-256 (base64) of the box certificate, so the phone can pin it from the QR code."""
    fixed = (os.environ.get("HEIRLOOM_TLS_SPKI_PIN") or "").strip()
    if fixed:
        return fixed
    path = (os.environ.get("HEIRLOOM_TLS_CERT_FILE") or "").strip()
    if not path or not os.path.isfile(path):
        return ""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        cert = x509.load_pem_x509_certificate(open(path, "rb").read())
        spki = cert.public_key().public_bytes(serialization.Encoding.DER,
                                              serialization.PublicFormat.SubjectPublicKeyInfo)
        return base64.b64encode(hashlib.sha256(spki).digest()).decode()
    except Exception:  # noqa: BLE001
        return ""


def box_url_for(request: Request, given: str = "") -> str:
    url = (given or os.environ.get("HEIRLOOM_PHONE_BOX_URL") or "").strip()
    if url:
        return url.rstrip("/")
    return str(request.base_url).rstrip("/")


class StartReq(BaseModel):
    box_url: str = Field("", max_length=200)


@router.post("/pair/start")
async def pair_start(body: StartReq, request: Request, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    try:
        return await mp.start(MongoPairStore(), user["user_id"], box_url_for(request, body.box_url), pin=tls_pin())
    except mp.PairingError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from None


class ClaimReq(BaseModel):
    code: str = Field(..., min_length=4, max_length=20)
    device_name: str = Field("", max_length=60)
    platform: str = Field(..., max_length=10)


@router.post("/pair/claim")
async def pair_claim(body: ClaimReq, request: Request):
    client = request.client.host if request.client else "unknown"
    try:
        return await mp.claim(MongoPairStore(), body.code, device_name=body.device_name, platform=body.platform,
                              client=client, limiter=_LIMITER)
    except mp.PairingError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from None


@router.get("/devices")
async def phones(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    rows = await db.companion_devices.find(
        {"user_id": user["user_id"], "kind": "phone", "revoked": False},
        {"_id": 0, "device_token": 0}).to_list(length=50)
    return {"devices": rows}


@router.delete("/devices/{device_id}")
async def unpair(device_id: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    done = await db.companion_devices.update_one(
        {"device_id": device_id, "user_id": user["user_id"], "kind": "phone"},
        {"$set": {"revoked": True, "revoked_at": datetime.now(timezone.utc).isoformat()}})
    if not done.matched_count:
        raise HTTPException(status_code=404, detail="No such phone")
    return {"ok": True}


@router.get("/me")
async def me(ctx: dict = Depends(get_device_user)):
    device, user = ctx["device"], ctx["user"]
    if device.get("kind") != "phone":
        raise HTTPException(status_code=403, detail="Not a phone token")
    from presence_speak import speak_url

    return {"device_id": device["device_id"], "name": device.get("name"), "owner": user.get("name") or "",
            "voice": bool(speak_url()), "local_only": True}


class SpeakReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=1200)


def _speak_wav_url() -> str:
    from presence_speak import speak_url

    url = speak_url().rstrip("/")
    return url if url.endswith(".wav") else url + ".wav"


@router.post("/speak")
async def speak(body: SpeakReq, ctx: dict = Depends(get_device_user)):
    """The box's local voice reads a reply aloud; the phone just plays the wav."""
    return await _speak(body.text, ctx)


@router.get("/speak.wav")
async def speak_get(text: str = Query(..., min_length=1, max_length=1200), ctx: dict = Depends(get_device_user)):
    """Same as POST /speak, as a GET so the phone's audio player can stream it with its Bearer header."""
    return await _speak(text, ctx)


async def _speak(text: str, ctx: dict) -> Response:
    if ctx["device"].get("kind") != "phone":
        raise HTTPException(status_code=403, detail="Not a phone token")
    import asyncio
    import json

    def render() -> bytes:
        req = urllib.request.Request(_speak_wav_url(), data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()

    try:
        wav = await asyncio.to_thread(render)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=503, detail="The box voice is not running") from None
    if not wav.startswith(b"RIFF"):
        raise HTTPException(status_code=503, detail="The box voice did not return audio")
    return Response(content=wav, media_type="audio/wav")
