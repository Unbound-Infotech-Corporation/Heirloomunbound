"""Optional Twilio number: family can call or text the Twin. Off unless TWILIO_MODE is mock or live.

Twilio routes only. Each call turn is a <Record>ing that the box downloads, transcribes with local
Whisper, answers with the local model and memory, and speaks back with <Play> of a wav rendered by the
box's local Chatterbox. No <Say>, no <Gather input="speech">: Twilio's cloud speech is never used.
See twilio_bridge.py for modes and config.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

import phone_inbound as inbound
import phone_policy as policy
import twilio_bridge as tb
from deps import db, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/twilio", tags=["twilio"])
_SILENCE: dict[str, int] = {}


def _cfg() -> tb.TwilioConfig:
    return tb.config()


def _cache() -> tb.AudioCache:
    from box_pause import data_root

    return tb.AudioCache(Path(os.environ.get("HEIRLOOM_TWILIO_AUDIO_DIR") or (data_root() / "twilio-audio")))


def _xml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


async def _checked(request: Request, path: str) -> dict:
    cfg = _cfg()
    if cfg.mode == "off":
        raise HTTPException(status_code=404, detail="Not found")
    form = {k: str(v) for k, v in (await request.form()).items()}
    ok = tb.request_allowed(cfg, url=tb.webhook_url(cfg, path), params=form,
                            signature=request.headers.get("X-Twilio-Signature", ""),
                            client_host=request.client.host if request.client else "",
                            mock_header=request.headers.get("X-Heirloom-Mock", ""))
    if not ok:
        raise HTTPException(status_code=403, detail="Bad signature")
    return form


async def _owner_and_settings() -> tuple[Optional[dict], dict]:
    user = await db.users.find_one({"audience": "owner"}, {"_id": 0})
    if not user:
        return None, policy.clamp_settings(None)
    row = await db.twin_phone_settings.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return user, policy.clamp_settings(row)


async def _reply(user: dict, text: str, decision: policy.PolicyDecision, thread: str) -> str:
    from twin_runtime import ensure_conversation, run_twin_turn

    conv = await ensure_conversation(user["user_id"], kind="twin_phone", conversation_id=thread)
    try:
        result = await run_twin_turn(user, text, conversation=conv, source="twilio", persist=True, summarise=False,
                                     role="twin", grounded=True, persona_hint="family", audience=decision.audience,
                                     caller_is_owner=decision.caller_is_owner,
                                     phone_caller_name=inbound.caller_name(decision), local_only=True)
        return result.reply
    except Exception as exc:  # noqa: BLE001
        logger.warning("Twilio twin turn failed: %s", exc)
        return "I lost that for a moment. Say it once more?"


def _thread(prefix: str, number: str) -> str:
    return f"{prefix}_" + hashlib.sha256(policy.normalize_e164(number).encode()).hexdigest()[:16]


def _disclosure(user: dict, decision: policy.PolicyDecision) -> str:
    line = policy.disclosure_line(user.get("name") or "")
    if decision.disclose or (os.environ.get("HEIRLOOM_AI_DISCLOSURE") or "1").strip() != "0":
        line += " I'm an AI that remembers what they shared."
    return line


def _render(text: str) -> bytes:
    req = urllib.request.Request(tb.voice_wav_url(), data=json.dumps({"text": text[:1200]}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        wav = resp.read()
    if not wav.startswith(b"RIFF"):
        raise RuntimeError("voice returned no audio")
    return wav


async def _play(text: str) -> str:
    """<Play> of the box's own voice. If the voice is down, nothing is spoken (never Twilio TTS)."""
    try:
        wav = await asyncio.to_thread(_render, text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Twilio: local voice unavailable: %s", exc)
        return ""
    clip = _cache().put(wav)
    return tb.play(f"{_cfg().public_url or 'http://127.0.0.1'}/api/twilio/audio/{clip}.wav")


def _fetch_recording(cfg: tb.TwilioConfig, form: dict) -> bytes:
    url = form.get("RecordingUrl", "")
    if cfg.mode == "mock" and url.startswith("file://"):
        local = Path(url[len("file://"):])
        if local.suffix.lower() != ".wav":
            raise ValueError("mock recordings must be .wav files")
        return local.read_bytes()
    if not tb.recording_host_ok(url):
        raise ValueError("recording is not on Twilio")
    req = urllib.request.Request(tb.recording_wav_url(url), headers={"Authorization": tb.basic_auth(cfg)})
    with urllib.request.urlopen(req, timeout=60) as resp:
        wav = resp.read()
    sid = form.get("RecordingSid", "")
    if cfg.mode == "live" and sid.startswith("RE"):
        delete = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Recordings/{sid}.json",
            method="DELETE", headers={"Authorization": tb.basic_auth(cfg)})
        try:
            urllib.request.urlopen(delete, timeout=30).close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Twilio: could not delete recording %s: %s", sid, exc)
    return wav


@router.post("/sms")
async def sms(request: Request):
    form = await _checked(request, "/api/twilio/sms")
    user, settings = await _owner_and_settings()
    sender = form.get("From", "")
    decision = policy.decide_inbound(policy.normalize_e164(sender), settings)
    if not user or not decision.allow:
        return _xml(tb.twiml(tb.message(decision.spoken or policy.DECLINE_SPOKEN)))
    body = (form.get("Body") or "").strip()[:1000]
    if not body:
        return _xml(tb.twiml())
    reply = await _reply(user, body, decision, _thread("sms", sender))
    return _xml(tb.twiml(tb.message(tb.sms_text(reply))))


@router.post("/voice")
async def voice(request: Request):
    form = await _checked(request, "/api/twilio/voice")
    user, settings = await _owner_and_settings()
    decision = policy.decide_inbound(policy.normalize_e164(form.get("From", "")), settings)
    if not user or not decision.allow:
        return _xml(tb.twiml(await _play(decision.spoken or policy.DECLINE_SPOKEN), tb.hangup()))
    _SILENCE[form.get("CallSid", "")] = 0
    hello = _disclosure(user, decision) + " What's on your mind?"
    turn = tb.webhook_url(_cfg(), "/api/twilio/voice/turn") if _cfg().mode == "live" else "/api/twilio/voice/turn"
    return _xml(tb.twiml(await _play(hello), tb.record(turn)))


@router.post("/voice/turn")
async def voice_turn(request: Request):
    cfg = _cfg()
    form = await _checked(request, "/api/twilio/voice/turn")
    user, settings = await _owner_and_settings()
    caller = form.get("From", "")
    decision = policy.decide_inbound(policy.normalize_e164(caller), settings)
    if not user or not decision.allow:
        return _xml(tb.twiml(tb.hangup()))
    call = form.get("CallSid", "")
    turn = tb.webhook_url(cfg, "/api/twilio/voice/turn") if cfg.mode == "live" else "/api/twilio/voice/turn"
    heard = ""
    if form.get("RecordingUrl"):
        try:
            wav = await asyncio.to_thread(_fetch_recording, cfg, form)
            from local_inference import transcribe_whisper_bytes

            heard = (await asyncio.to_thread(transcribe_whisper_bytes, wav, filename="turn.wav") or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Twilio turn could not be heard: %s", exc)
    if not heard:
        _SILENCE[call] = _SILENCE.get(call, 0) + 1
        if _SILENCE[call] >= 2:
            _SILENCE.pop(call, None)
            return _xml(tb.twiml(await _play(inbound.SILENCE_BYE), tb.hangup()))
        return _xml(tb.twiml(await _play(inbound.SILENCE_REPEAT), tb.record(turn)))
    _SILENCE[call] = 0
    reply = await _reply(user, heard, decision, _thread("call", caller))
    return _xml(tb.twiml(await _play(reply), tb.record(turn)))


@router.get("/audio/{clip}.wav")
async def audio(clip: str):
    if _cfg().mode == "off":
        raise HTTPException(status_code=404, detail="Not found")
    wav = _cache().get(clip)
    if wav is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(content=wav, media_type="audio/wav")


@router.get("/status")
async def status(user: dict = Depends(get_current_user)):
    """For the owner's settings page: mode and which placeholders are filled in. Never the token."""
    from connectors import connectors_allowed

    if not connectors_allowed(audience=user.get("audience") or "owner", heir_surface=bool(user.get("heir_surface"))):
        raise HTTPException(status_code=403, detail="owner_only")
    cfg = _cfg()
    return {**cfg.public(), "webhooks": {"sms": "/api/twilio/sms", "voice": "/api/twilio/voice"},
            "local_only": True}
