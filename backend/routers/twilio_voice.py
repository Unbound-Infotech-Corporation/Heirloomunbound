"""Twilio Programmable Voice — the twin gets its own phone number.

Two flows:
    * Inbound: someone calls the user's Twilio number → Twilio POSTs our
      `/voice/incoming` webhook → we return TwiML with `<Gather input="speech">`
      that starts a multi-turn conversation loop. Each turn:
          Twilio speech-recog → POST /voice/turn/{call_sid} with SpeechResult
          → we ask the twin (Claude via emergentintegrations) for a reply
          → we synthesize the reply with ElevenLabs (user's cloned voice)
          → cache the mp3 in memory
          → return TwiML `<Play>` pointing at /audio/{token}.mp3 followed by
            another `<Gather>` to keep the conversation going
    * Outbound: user says "call X" → we POST to Twilio Calls API with our
      `/voice/incoming` webhook as the initial URL → same loop.

Multi-user: we look up the owning user by matching the incoming `To` number
against `db.user_twilio.phone_number`.

Security: every incoming webhook MUST pass Twilio's `X-Twilio-Signature`
check (we use Twilio's official RequestValidator). No signature = 403.

Persistence:
    db.user_twilio        — per-user {account_sid, auth_token, phone_number}
    db.twilio_calls       — call log with turns and transcript
    In-memory AUDIO_CACHE — token → mp3 bytes, TTL 10 min (fine because
                            Twilio fetches within seconds).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import Gather, VoiceResponse

from deps import db, get_current_user
from emergentintegrations.llm.chat import LlmChat, UserMessage

router = APIRouter(prefix="/twilio", tags=["twilio"])
log = logging.getLogger("twilio_voice")

# ------------- config -------------
PUBLIC_URL = (
    os.environ.get("PUBLIC_BACKEND_URL")
    or os.environ.get("BACKEND_URL")
    or ""
).rstrip("/")
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
MAX_TURNS = 12                     # end the call politely after this many exchanges
AUDIO_TTL_SEC = 600                # cached TTS lives 10 min
ELEVEN_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_ELEVEN_MODEL = "eleven_turbo_v2_5"

AUDIO_CACHE: dict[str, tuple[float, bytes]] = {}  # token → (expires_at, mp3 bytes)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cache_prune() -> None:
    """Cheap TTL sweep — called at the top of GET /audio."""
    now = time.time()
    dead = [k for k, (exp, _b) in AUDIO_CACHE.items() if exp < now]
    for k in dead:
        AUDIO_CACHE.pop(k, None)


# ------------- config CRUD (owner-facing) -------------
class TwilioConfig(BaseModel):
    account_sid: str = Field(min_length=8, max_length=64)
    auth_token: str = Field(min_length=8, max_length=128)
    phone_number: str = Field(min_length=6, max_length=20)  # E.164
    outbound_enabled: bool = False   # opt-in for twin-initiated calls
    voice_id: Optional[str] = None   # ElevenLabs voice_id override; else look up user's


class ConfigStatus(BaseModel):
    configured: bool
    phone_number: Optional[str] = None
    outbound_enabled: bool = False
    verified: bool = False
    webhook_configured: bool = False


@router.get("/config", response_model=ConfigStatus)
async def get_config(user: dict = Depends(get_current_user)):
    doc = await db.user_twilio.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        return ConfigStatus(configured=False)
    return ConfigStatus(
        configured=True,
        phone_number=doc.get("phone_number"),
        outbound_enabled=bool(doc.get("outbound_enabled", False)),
        verified=bool(doc.get("verified", False)),
        webhook_configured=bool(doc.get("webhook_configured", False)),
    )


@router.put("/config")
async def put_config(payload: TwilioConfig, user: dict = Depends(get_current_user)):
    # Verify credentials by hitting Twilio (fetch the account)
    try:
        client = TwilioClient(payload.account_sid, payload.auth_token)
        acct = await asyncio.to_thread(lambda: client.api.accounts(payload.account_sid).fetch())
        friendly = acct.friendly_name
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Twilio credentials rejected: {exc}") from exc

    # Verify the number belongs to this account
    try:
        numbers = await asyncio.to_thread(lambda: client.incoming_phone_numbers.list(
            phone_number=payload.phone_number, limit=1))
        if not numbers:
            raise HTTPException(status_code=400, detail=f"Number {payload.phone_number} not found on this Twilio account.")
        number_sid = numbers[0].sid
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Couldn't verify number: {exc}") from exc

    # Auto-configure the voice webhook on this number
    webhook_ok = False
    if PUBLIC_URL:
        webhook_url = f"{PUBLIC_URL}/api/twilio/voice/incoming"
        try:
            await asyncio.to_thread(lambda: client.incoming_phone_numbers(number_sid).update(
                voice_url=webhook_url, voice_method="POST"))
            webhook_ok = True
        except Exception as exc:  # noqa: BLE001
            log.warning("Couldn't auto-set voice webhook for user %s: %s", user["user_id"], exc)

    doc = {
        "user_id": user["user_id"],
        "account_sid": payload.account_sid,
        "auth_token": payload.auth_token,
        "phone_number": payload.phone_number,
        "outbound_enabled": payload.outbound_enabled,
        "voice_id": payload.voice_id,
        "twilio_number_sid": number_sid,
        "verified": True,
        "webhook_configured": webhook_ok,
        "friendly_name": friendly,
        "updated_at": _now_iso(),
    }
    await db.user_twilio.replace_one({"user_id": user["user_id"]}, doc, upsert=True)
    return {"ok": True, "phone_number": payload.phone_number, "webhook_configured": webhook_ok}


@router.delete("/config")
async def delete_config(user: dict = Depends(get_current_user)):
    await db.user_twilio.delete_one({"user_id": user["user_id"]})
    return {"ok": True}


# ------------- outbound call (user-triggered) -------------
class OutboundReq(BaseModel):
    to_number: str = Field(min_length=6, max_length=20)
    opening_line: str = Field(default="Hi, this is the digital twin — how are you?", max_length=400)


@router.post("/call/outbound")
async def outbound_call(payload: OutboundReq, user: dict = Depends(get_current_user)):
    cfg = await db.user_twilio.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not cfg or not cfg.get("verified"):
        raise HTTPException(status_code=400, detail="Twilio isn't configured — set it up in Connect first.")
    if not cfg.get("outbound_enabled"):
        raise HTTPException(status_code=400, detail="Outbound calling is off. Enable it in Twilio settings first.")
    if not PUBLIC_URL:
        raise HTTPException(status_code=500, detail="PUBLIC_BACKEND_URL not set — outbound flow can't route back.")

    # Seed the conversation with the opening line so the first Gather already
    # has our first sentence spoken.
    seed_id = uuid.uuid4().hex[:12]
    await db.twilio_calls.insert_one({
        "call_sid": None,             # filled when Twilio calls us back
        "seed_id": seed_id,
        "user_id": user["user_id"],
        "direction": "outbound",
        "to_number": payload.to_number,
        "from_number": cfg["phone_number"],
        "opening_line": payload.opening_line,
        "turns": [],
        "status": "dialing",
        "created_at": _now_iso(),
    })

    try:
        client = TwilioClient(cfg["account_sid"], cfg["auth_token"])
        call = await asyncio.to_thread(lambda: client.calls.create(
            to=payload.to_number,
            from_=cfg["phone_number"],
            url=f"{PUBLIC_URL}/api/twilio/voice/incoming?seed_id={seed_id}",
            method="POST",
        ))
    except Exception as exc:  # noqa: BLE001
        await db.twilio_calls.update_one(
            {"seed_id": seed_id},
            {"$set": {"status": "failed", "error": str(exc)[:400]}},
        )
        raise HTTPException(status_code=502, detail=f"Twilio couldn't place the call: {exc}") from exc

    await db.twilio_calls.update_one(
        {"seed_id": seed_id},
        {"$set": {"call_sid": call.sid, "status": "ringing"}},
    )
    return {"ok": True, "call_sid": call.sid}


@router.get("/calls")
async def list_calls(user: dict = Depends(get_current_user), limit: int = 20):
    docs = await db.twilio_calls.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(min(limit, 100)).to_list(length=min(limit, 100))
    return {"calls": docs}


# ------------- signature validation -------------
async def _validate_signature(request: Request, auth_token: str) -> bool:
    """Verify Twilio signed this request. Uses the exact public URL Twilio
    called + all POST params + Auth Token."""
    sig = request.headers.get("X-Twilio-Signature", "")
    if not sig:
        return False
    validator = RequestValidator(auth_token)
    # Build the full URL Twilio used (respect proxy headers)
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    full_url = f"{scheme}://{host}{request.url.path}"
    if request.url.query:
        full_url += f"?{request.url.query}"
    form = await request.form()
    params = {k: v for k, v in form.items()}
    return validator.validate(full_url, params, sig)


async def _lookup_user_by_number(number: str) -> Optional[dict]:
    return await db.user_twilio.find_one({"phone_number": number}, {"_id": 0})


# ------------- inbound / turn handlers -------------
def _twiml_bye(msg: str) -> Response:
    r = VoiceResponse()
    r.say(msg, voice="alice")
    r.hangup()
    return Response(content=str(r), media_type="application/xml")


def _twiml_gather(action: str, prompt_audio_url: Optional[str] = None,
                  prompt_text: Optional[str] = None, timeout: int = 6) -> str:
    r = VoiceResponse()
    g = Gather(input="speech", action=action, method="POST",
               speech_timeout="auto", timeout=timeout, language="en-US")
    if prompt_audio_url:
        g.play(prompt_audio_url)
    elif prompt_text:
        g.say(prompt_text, voice="alice")
    r.append(g)
    # If Gather times out without speech, re-prompt once then hang up
    r.say("I didn't catch that. Talk to you soon.", voice="alice")
    r.hangup()
    return str(r)


@router.post("/voice/incoming")
async def voice_incoming(request: Request):
    """First hop of any call — inbound or outbound. Twilio POSTs the call
    metadata; we return TwiML that opens the conversation."""
    form = await request.form()
    call_sid = form.get("CallSid", "")
    from_number = form.get("From", "")
    to_number = form.get("To", "")
    direction = form.get("Direction", "inbound")
    seed_id = request.query_params.get("seed_id")

    # Find owning user — for inbound, match "To"; for outbound-seed, we already
    # created the call log with the seed_id.
    if seed_id:
        seed_doc = await db.twilio_calls.find_one({"seed_id": seed_id}, {"_id": 0})
        if not seed_doc:
            return _twiml_bye("Call setup error.")
        user_number = seed_doc["from_number"]
    else:
        user_number = to_number
    cfg = await _lookup_user_by_number(user_number)
    if not cfg:
        # Fail closed: unsigned/unknown-number webhooks get 403 (no user data leak).
        raise HTTPException(status_code=403, detail="Unknown Twilio number or bad signature")

    if not await _validate_signature(request, cfg["auth_token"]):
        log.warning("Twilio signature validation failed for CallSid=%s", call_sid)
        raise HTTPException(status_code=403, detail="Bad Twilio signature")

    # Persist / update the call log
    opening_line = None
    if seed_id:
        opening_line = seed_doc.get("opening_line")
        await db.twilio_calls.update_one(
            {"seed_id": seed_id},
            {"$set": {"call_sid": call_sid, "status": "in-progress"}},
        )
    else:
        await db.twilio_calls.insert_one({
            "call_sid": call_sid,
            "user_id": cfg["user_id"],
            "direction": direction or "inbound",
            "to_number": to_number,
            "from_number": from_number,
            "opening_line": None,
            "turns": [],
            "status": "in-progress",
            "created_at": _now_iso(),
        })

    # Build the opening prompt — either seeded outbound line, or default greeting
    if opening_line:
        audio_url = await _synthesize_and_cache(cfg["user_id"], opening_line, cfg.get("voice_id"))
        twiml = _twiml_gather(f"/api/twilio/voice/turn/{call_sid}", prompt_audio_url=audio_url)
    else:
        # Very first turn: say a short greeting in the cloned voice if we have one,
        # else fall back to Twilio's built-in TTS.
        greet = f"Hey, this is a digital twin. How can I help?"
        try:
            audio_url = await _synthesize_and_cache(cfg["user_id"], greet, cfg.get("voice_id"))
            twiml = _twiml_gather(f"/api/twilio/voice/turn/{call_sid}", prompt_audio_url=audio_url)
        except Exception:  # noqa: BLE001
            twiml = _twiml_gather(f"/api/twilio/voice/turn/{call_sid}", prompt_text=greet)
    return Response(content=twiml, media_type="application/xml")


@router.post("/voice/turn/{call_sid}")
async def voice_turn(call_sid: str, request: Request):
    form = await request.form()
    speech = (form.get("SpeechResult") or "").strip()

    doc = await db.twilio_calls.find_one({"call_sid": call_sid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=403, detail="Unknown call or bad signature")
    cfg = await db.user_twilio.find_one({"user_id": doc["user_id"]}, {"_id": 0})
    if not cfg:
        raise HTTPException(status_code=403, detail="Line not configured")

    if not await _validate_signature(request, cfg["auth_token"]):
        raise HTTPException(status_code=403, detail="Bad Twilio signature")

    turns: list = doc.get("turns") or []
    if len(turns) >= MAX_TURNS:
        return _twiml_bye("I'll wrap up here for now. Bye!")

    if not speech:
        # Timed out — polite goodbye
        return _twiml_bye("I couldn't hear you. Talk soon!")

    # Ask the twin
    try:
        reply = await _twin_reply(cfg["user_id"], turns, speech)
    except Exception as exc:  # noqa: BLE001
        log.exception("twin_reply failed: %s", exc)
        reply = "Sorry, I'm having trouble thinking right now. Talk soon!"

    turns.append({"role": "caller", "text": speech, "at": _now_iso()})
    turns.append({"role": "twin", "text": reply, "at": _now_iso()})
    await db.twilio_calls.update_one(
        {"call_sid": call_sid},
        {"$set": {"turns": turns, "last_updated_at": _now_iso()}},
    )

    # Synthesize with the user's ElevenLabs voice; fall back to Twilio TTS.
    try:
        audio_url = await _synthesize_and_cache(cfg["user_id"], reply, cfg.get("voice_id"))
        twiml = _twiml_gather(f"/api/twilio/voice/turn/{call_sid}", prompt_audio_url=audio_url)
    except Exception as exc:  # noqa: BLE001
        log.warning("TTS failed, falling back to Twilio voice: %s", exc)
        twiml = _twiml_gather(f"/api/twilio/voice/turn/{call_sid}", prompt_text=reply)

    return Response(content=twiml, media_type="application/xml")


# ------------- twin brain -------------
async def _twin_reply(user_id: str, prior_turns: list, caller_said: str) -> str:
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "name": 1, "personality": 1})
    persona = (user or {}).get("personality") or ""
    name = (user or {}).get("name") or "the owner"
    system = (
        f"You are the digital twin of {name}. You are on a phone call — someone called your "
        f"owner's number and you're speaking with them AS the owner. Keep replies SHORT "
        f"(1-3 sentences), warm, natural, spoken-cadence. Never break character. Never say "
        f"you're an AI unless they explicitly ask. If they ask for something urgent that "
        f"only the real owner can decide, politely say you'll pass it along.\n\n"
        f"Owner personality notes:\n{persona[:1200]}"
    )
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"call_{user_id}_{uuid.uuid4().hex[:6]}",
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-4-6")
    # Rehydrate prior turns so the twin has short-term memory
    for t in prior_turns[-8:]:
        role = "user" if t["role"] == "caller" else "assistant"
        # LlmChat with a fresh session — we just prepend context textually
        if role == "user":
            await chat.send_message(UserMessage(text=f"[Earlier they said: {t['text']}]"))
    resp = await chat.send_message(UserMessage(text=caller_said))
    text = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
    return text.strip()[:800]


# ------------- TTS / audio cache -------------
async def _synthesize_and_cache(user_id: str, text: str, voice_id_override: Optional[str] = None) -> str:
    """Generate mp3 via ElevenLabs, stash in AUDIO_CACHE, return a public URL
    Twilio can Play. Raises on failure — caller should fall back to Twilio TTS."""
    settings = await db.voice_clone_settings.find_one({"user_id": user_id}, {"_id": 0}) or {}
    voice_id = voice_id_override or settings.get("voice_id")
    api_key = settings.get("api_key")
    if not (voice_id and api_key):
        raise RuntimeError("ElevenLabs voice not configured")
    url = ELEVEN_TTS_URL.format(voice_id=voice_id)
    headers = {"xi-api-key": api_key, "accept": "audio/mpeg", "Content-Type": "application/json"}
    payload = {"text": text, "model_id": DEFAULT_ELEVEN_MODEL,
               "voice_settings": {"stability": 0.5, "similarity_boost": 0.85}}
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        audio_bytes = r.content
    token = uuid.uuid4().hex
    AUDIO_CACHE[token] = (time.time() + AUDIO_TTL_SEC, audio_bytes)
    return f"{PUBLIC_URL}/api/twilio/audio/{token}.mp3"


@router.get("/audio/{token_with_ext}")
async def get_audio(token_with_ext: str):
    _cache_prune()
    token = token_with_ext.split(".")[0]
    entry = AUDIO_CACHE.get(token)
    if not entry:
        raise HTTPException(status_code=404, detail="audio expired")
    exp, blob = entry
    if exp < time.time():
        AUDIO_CACHE.pop(token, None)
        raise HTTPException(status_code=404, detail="audio expired")
    return Response(content=blob, media_type="audio/mpeg")
