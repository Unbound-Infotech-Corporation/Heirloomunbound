"""Twin phone line — Retell PSTN in front of the Heirloom brain.

Owner REST lives here. Retell opens a custom-LLM WebSocket per call and posts
signed webhooks for recordings and transcripts. WinUI talks to the REST
surface with a session or device token (same as studio).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

import abilities as ab
import phone_inbound as inbound
import phone_policy as policy
import phone_retell as retell
from deps import db
from routers.studio import get_studio_user
from twin_runtime import ensure_conversation, run_twin_turn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/phone", tags=["phone"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _settings_doc(user_id: str) -> dict:
    row = await db.twin_phone_settings.find_one({"user_id": user_id}, {"_id": 0})
    return policy.clamp_settings(row)


async def _save_settings(user_id: str, settings: dict) -> dict:
    clamped = policy.clamp_settings(settings)
    clamped["user_id"] = user_id
    clamped["updated_at"] = _now_iso()
    await db.twin_phone_settings.update_one(
        {"user_id": user_id},
        {"$set": clamped},
        upsert=True,
    )
    return clamped


async def _line_doc(user_id: str) -> Optional[dict]:
    return await db.twin_phone_lines.find_one({"user_id": user_id}, {"_id": 0})


async def _line_by_e164(e164: str) -> Optional[dict]:
    number = policy.normalize_e164(e164)
    if not number:
        return None
    return await db.twin_phone_lines.find_one({"e164": number}, {"_id": 0})


def _status_payload(settings: dict, line: Optional[dict], user: dict) -> dict:
    cloned = bool((user.get("elevenlabs_voice_id") or "").strip())
    voice_kind = (line or {}).get("voice_kind") or ("cloned" if cloned else "stock")
    return {
        "configured": retell.configured(),
        "settings": settings,
        "line": {
            "e164": (line or {}).get("e164") or "",
            "status": (line or {}).get("status") or "none",
            "voice_kind": voice_kind if line else ("cloned" if cloned else "stock"),
            "voice_name": (line or {}).get("voice_name")
            or user.get("elevenlabs_voice_name")
            or "",
        },
        "cloned_voice_ready": cloned,
        "public_url_ready": bool(retell.public_http_base()),
    }


@router.get("/settings")
async def get_settings(user: dict = Depends(get_studio_user)):
    settings = await _settings_doc(user["user_id"])
    line = await _line_doc(user["user_id"])
    return _status_payload(settings, line, user)


class SettingsReq(BaseModel):
    answering: Optional[bool] = None
    who_can_call: Optional[str] = None
    allowlist: Optional[list[dict]] = None
    unknown_policy: Optional[str] = None
    owner_e164: Optional[str] = None
    hours_enabled: Optional[bool] = None
    timezone: Optional[str] = None
    hours_windows: Optional[list[dict]] = None
    handoff_enabled: Optional[bool] = None
    handoff_e164: Optional[str] = None
    disclosure: Optional[str] = None
    record: Optional[bool] = None


@router.put("/settings")
async def put_settings(payload: SettingsReq, user: dict = Depends(get_studio_user)):
    current = await _settings_doc(user["user_id"])
    patch = payload.model_dump(exclude_unset=True)
    settings = await _save_settings(user["user_id"], {**current, **patch})
    line = await _line_doc(user["user_id"])
    return _status_payload(settings, line, user)


@router.post("/number")
async def provision_number(user: dict = Depends(get_studio_user)):
    if not retell.configured():
        raise HTTPException(
            status_code=503,
            detail="Retell is not configured. Add RETELL_API_KEY on the API.",
        )
    llm_ws = retell.llm_websocket_url()
    hook = retell.webhook_url()
    if not llm_ws or not hook:
        raise HTTPException(
            status_code=503,
            detail="PUBLIC_BACKEND_URL is not set, so Retell cannot reach this Twin.",
        )

    existing = await _line_doc(user["user_id"])
    if existing and existing.get("e164") and existing.get("status") == "active":
        settings = await _settings_doc(user["user_id"])
        return _status_payload(settings, existing, user)

    name = (user.get("name") or "Heirloom Twin").strip() or "Heirloom Twin"
    eleven_id = (user.get("elevenlabs_voice_id") or "").strip()
    eleven_key = (user.get("elevenlabs_api_key") or "").strip()
    voice_id = retell.DEFAULT_STOCK_VOICE
    voice_kind = "stock"
    if eleven_id:
        imported = await retell.import_elevenlabs_voice(
            voice_id=eleven_id,
            name=name,
            api_key=eleven_key,
        )
        if imported:
            voice_id = imported
            voice_kind = "cloned"

    try:
        agent = await retell.create_agent(
            name=f"{name} Twin",
            voice_id=voice_id,
            webhook=hook,
            llm_ws=llm_ws,
        )
        agent_id = str(agent.get("agent_id") or "")
        if not agent_id:
            raise retell.RetellError(502, "Retell did not return an agent_id")
        number = await retell.create_phone_number(
            inbound_agent_id=agent_id,
            outbound_agent_id=agent_id,
        )
    except retell.RetellError as exc:
        raise HTTPException(status_code=502, detail=f"Retell: {exc.detail}") from exc

    e164 = policy.normalize_e164(
        number.get("phone_number") or number.get("e164") or number.get("number")
    )
    if not e164:
        raise HTTPException(status_code=502, detail="Retell did not return a phone number.")

    line = {
        "user_id": user["user_id"],
        "e164": e164,
        "retell_phone_number": e164,
        "retell_agent_id": agent_id,
        "retell_llm_id": llm_ws,
        "retell_voice_id": voice_id,
        "voice_kind": voice_kind,
        "voice_name": user.get("elevenlabs_voice_name") or "",
        "status": "active",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.twin_phone_lines.update_one(
        {"user_id": user["user_id"]},
        {"$set": line},
        upsert=True,
    )
    settings = await _settings_doc(user["user_id"])
    settings["answering"] = True
    settings = await _save_settings(user["user_id"], settings)
    await ab.set_state(user["user_id"], "phone", True, ["phone_line"])
    return _status_payload(settings, line, user)


@router.delete("/number")
async def release_number(user: dict = Depends(get_studio_user)):
    line = await _line_doc(user["user_id"])
    if not line:
        settings = await _settings_doc(user["user_id"])
        return _status_payload(settings, None, user)
    try:
        await retell.delete_phone_number(line.get("e164") or "")
        await retell.delete_agent(line.get("retell_agent_id") or "")
    except retell.RetellError as exc:
        logger.warning("Retell release failed: %s", exc.detail)
    await db.twin_phone_lines.delete_one({"user_id": user["user_id"]})
    settings = await _settings_doc(user["user_id"])
    settings["answering"] = False
    settings = await _save_settings(user["user_id"], settings)
    await ab.set_state(user["user_id"], "phone", False, [])
    return _status_payload(settings, None, user)


class OutboundReq(BaseModel):
    to_e164: str = Field(..., min_length=8, max_length=24)
    contact_name: Optional[str] = Field(None, max_length=80)


@router.post("/outbound")
async def place_outbound(payload: OutboundReq, user: dict = Depends(get_studio_user)):
    line = await _line_doc(user["user_id"])
    if not line or not line.get("e164"):
        raise HTTPException(status_code=400, detail="Get a phone line first.")
    settings = await _settings_doc(user["user_id"])
    dest = policy.normalize_e164(payload.to_e164)
    if not dest:
        raise HTTPException(status_code=400, detail="That number is not a valid phone number.")
    if not policy.outbound_allowed(dest, settings):
        raise HTTPException(
            status_code=403,
            detail="Outbound calls go to people on Who may call. Add them first.",
        )
    if not retell.configured():
        raise HTTPException(status_code=503, detail="Retell is not configured.")
    try:
        call = await retell.create_phone_call(
            from_number=line["e164"],
            to_number=dest,
            metadata={
                "user_id": user["user_id"],
                "contact_name": (payload.contact_name or "").strip(),
            },
        )
    except retell.RetellError as exc:
        raise HTTPException(status_code=502, detail=f"Retell: {exc.detail}") from exc

    call_id = str(call.get("call_id") or "")
    await _upsert_call({
        "call_id": call_id,
        "user_id": user["user_id"],
        "direction": "outbound",
        "from_e164": line["e164"],
        "to_e164": dest,
        "contact_name": (payload.contact_name or "").strip(),
        "status": call.get("call_status") or "registered",
        "started_at": _now_iso(),
        "policy": "owner_outbound",
        "call_state": "talking",
    })
    return {"ok": True, "call_id": call_id, "to_e164": dest}


@router.get("/calls")
async def list_calls(user: dict = Depends(get_studio_user)):
    rows = await db.twin_phone_calls.find(
        {"user_id": user["user_id"]},
        {"_id": 0, "transcript_object": 0},
    ).sort("started_at", -1).to_list(length=40)
    return {"calls": rows}


@router.get("/calls/{call_id}")
async def get_phone_call(call_id: str, user: dict = Depends(get_studio_user)):
    row = await db.twin_phone_calls.find_one(
        {"call_id": call_id, "user_id": user["user_id"]},
        {"_id": 0},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Call not found")
    return row


async def _upsert_call(fields: dict[str, Any]) -> None:
    call_id = str(fields.get("call_id") or "").strip()
    if not call_id:
        return
    payload = {k: v for k, v in fields.items() if v is not None}
    payload["updated_at"] = _now_iso()
    await db.twin_phone_calls.update_one(
        {"call_id": call_id},
        {"$set": payload, "$setOnInsert": {"created_at": _now_iso()}},
        upsert=True,
    )


async def _mark_webhook(event: str, call_id: str) -> bool:
    """Return True if this lifecycle event is new (should be processed)."""
    key = retell.event_key(event, call_id)
    if not call_id or event in {"transcript_updated"}:
        return True
    result = await db.twin_phone_webhook_events.update_one(
        {"event_key": key},
        {"$setOnInsert": {"event_key": key, "at": _now_iso()}},
        upsert=True,
    )
    return result.upserted_id is not None


@router.post("/retell/webhook")
async def retell_webhook(request: Request):
    raw = await request.body()
    signature = (
        request.headers.get("x-retell-signature")
        or request.headers.get("X-Retell-Signature")
        or ""
    )
    if not retell.verify_webhook_signature(raw, signature):
        raise HTTPException(status_code=401, detail="Invalid Retell signature")
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    event = str(body.get("event") or "")
    call = body.get("call") if isinstance(body.get("call"), dict) else body
    call_id = str(call.get("call_id") or "")
    if not call_id:
        return {"ok": True}
    fresh = await _mark_webhook(event, call_id)
    to_number = policy.normalize_e164(call.get("to_number"))
    from_number = policy.normalize_e164(call.get("from_number"))
    direction = str(call.get("direction") or "inbound")
    line = None
    if direction == "outbound":
        line = await _line_by_e164(from_number)
    if line is None:
        line = await _line_by_e164(to_number)
    user_id = (line or {}).get("user_id") or ""
    patch: dict[str, Any] = {
        "call_id": call_id,
        "user_id": user_id,
        "direction": direction,
        "from_e164": from_number,
        "to_e164": to_number,
        "status": call.get("call_status") or event,
        "disconnection_reason": call.get("disconnection_reason") or "",
    }
    rec = call.get("recording_url") or call.get("recording") or ""
    if rec:
        patch["recording_url"] = rec
    raw_transcript = call.get("transcript")
    if isinstance(raw_transcript, list):
        formatted = retell.format_transcript(raw_transcript)
        if formatted:
            patch["transcript"] = formatted
    elif isinstance(raw_transcript, str) and raw_transcript.strip():
        patch["transcript"] = raw_transcript.strip()
    if event == "call_started":
        patch["started_at"] = _now_iso()
    if event in {"call_ended", "call_analyzed"}:
        patch["ended_at"] = _now_iso()
        analysis = call.get("call_analysis")
        if isinstance(analysis, dict):
            patch["analysis"] = analysis
    if not fresh and event != "transcript_updated":
        await _upsert_call({
            k: v for k, v in patch.items()
            if k in {"call_id", "transcript", "recording_url", "analysis", "status"}
        })
        return {"ok": True, "duplicate": True}
    await _upsert_call(patch)
    if fresh and event == "call_ended" and user_id:
        await _notify_call_ended(user_id, call_id)
    return {"ok": True}


async def _queue_notify(user_id: str, title: str, message: str) -> None:
    if not user_id or not message:
        return
    await db.companion_commands.insert_one({
        "cmd_id": f"cmd_{uuid.uuid4().hex[:10]}",
        "user_id": user_id,
        "kind": "notify",
        "payload": {"title": title, "message": message},
        "status": "queued",
        "result": None,
        "created_at": _now_iso(),
        "completed_at": None,
    })


async def _notify_call_ended(user_id: str, call_id: str) -> None:
    row = await db.twin_phone_calls.find_one({"call_id": call_id, "user_id": user_id}, {"_id": 0}) or {}
    if row.get("notified_at"):
        return
    settings = await _settings_doc(user_id)
    party = row.get("from_e164") if str(row.get("direction") or "") != "outbound" else row.get("to_e164")
    who = inbound.caller_display(
        str(party or ""),
        settings,
        contact_name=str(row.get("contact_name") or ""),
    )
    title, body = inbound.notify_copy(
        direction=str(row.get("direction") or "inbound"),
        who=who,
        message_left=str(row.get("message_left") or ""),
        status=str(row.get("policy") or row.get("status") or ""),
    )
    await _upsert_call({"call_id": call_id, "notified_at": _now_iso()})
    await _queue_notify(user_id, title, body)


def _party_e164(call: dict, line_e164: str) -> str:
    direction = str(call.get("direction") or "inbound")
    if direction == "outbound":
        return policy.normalize_e164(call.get("to_number"))
    from_n = policy.normalize_e164(call.get("from_number"))
    to_n = policy.normalize_e164(call.get("to_number"))
    if from_n and from_n != line_e164:
        return from_n
    return to_n


async def _resolve_call_context(
    call_id: str, call: dict
) -> tuple[Optional[dict], dict, policy.PolicyDecision, dict]:
    to_number = policy.normalize_e164(call.get("to_number"))
    from_number = policy.normalize_e164(call.get("from_number"))
    direction = str(call.get("direction") or "inbound")
    line = None
    if direction == "outbound":
        line = await _line_by_e164(from_number)
    if line is None:
        line = await _line_by_e164(to_number)
    if line is None:
        empty = policy.decide_inbound("", {"answering": False})
        return None, {}, empty, {}
    user = await db.users.find_one({"user_id": line["user_id"]}, {"_id": 0}) or {}
    settings = await _settings_doc(line["user_id"])
    other = _party_e164(call, line.get("e164") or "")
    if direction == "outbound":
        decision = policy.PolicyDecision(
            action="answer",
            audience="caller",
            caller_is_owner=True,
            known_family=True,
            disclose=False,
            allowlist_entry=policy.match_allowlist(other, settings),
            spoken="",
        )
    else:
        decision = policy.decide_inbound(other, settings)
    await _upsert_call({
        "call_id": call_id,
        "user_id": line["user_id"],
        "direction": direction,
        "from_e164": from_number,
        "to_e164": to_number,
        "contact_name": inbound.caller_name(decision) if inbound.caller_name(decision) != "you" else (user.get("name") or "You"),
        "status": call.get("call_status") or "ongoing",
        "policy": decision.action,
        "audience": decision.audience,
        "started_at": _now_iso(),
    })
    return line, user, decision, settings


def _contact_name(user: dict, decision: policy.PolicyDecision) -> str:
    who = inbound.caller_name(decision)
    if who == "you":
        return (user.get("name") or "You").strip() or "You"
    return who


async def _twin_spoken(
    *,
    user: dict,
    text: str,
    call_id: str,
    decision: policy.PolicyDecision,
) -> str:
    if not user.get("user_id"):
        return policy.DECLINE_SPOKEN
    conv = await ensure_conversation(
        user["user_id"],
        kind="twin_phone",
        conversation_id=f"phone_{call_id}",
    )
    try:
        result = await run_twin_turn(
            user,
            text,
            conversation=conv,
            source="phone",
            persist=True,
            summarise=False,
            twin_backend="cloud_claude",
            role="twin",
            grounded=True,
            persona_hint="family",
            audience=decision.audience,
            caller_is_owner=decision.caller_is_owner,
            phone_caller_name=inbound.caller_name(decision),
        )
        spoken = retell.for_speech(result.reply)
        if result.tool_trace:
            await _upsert_call({
                "call_id": call_id,
                "tool_trace": result.tool_trace[-12:],
            })
        return spoken or "I don't remember that yet, and I will not invent it."
    except Exception as exc:  # noqa: BLE001
        logger.warning("Phone twin turn failed: %s", exc)
        return "I lost that for a moment. Say it once more?"


@router.websocket("/retell/llm/{call_id}")
async def retell_llm(websocket: WebSocket, call_id: str):
    await websocket.accept()
    call: dict[str, Any] = {"call_id": call_id}
    user: dict = {}
    settings: dict = {}
    decision: Optional[policy.PolicyDecision] = None
    session = inbound.InboundSession()
    try:
        await websocket.send_json(retell.config_hello())
        while True:
            incoming = await websocket.receive_json()
            kind = str(incoming.get("interaction_type") or "")
            if kind == "ping_pong":
                await websocket.send_json(retell.ping_pong(incoming.get("timestamp")))
                continue
            if kind == "call_details":
                raw_call = incoming.get("call")
                if isinstance(raw_call, dict):
                    call = raw_call
                    call.setdefault("call_id", call_id)
                    _line, user, decision, settings = await _resolve_call_context(call_id, call)
                    inbound.apply_policy_phase(session, decision)
                continue
            if kind == "update_only":
                continue
            if kind not in {"response_required", "reminder_required"}:
                continue
            response_id = int(incoming.get("response_id") or 0)
            transcript = incoming.get("transcript") or []
            if decision is None:
                try:
                    fetched = await retell.get_call(call_id)
                    call = fetched if fetched else call
                except retell.RetellError:
                    pass
                _line, user, decision, settings = await _resolve_call_context(call_id, call)
                inbound.apply_policy_phase(session, decision)

            user_text = retell.latest_user_text(transcript)
            plan = inbound.plan_turn(
                interaction=kind,
                user_text=user_text,
                session=session,
                decision=decision,
                settings=settings,
                user_name=(user.get("name") or "").strip(),
            )
            if plan.save_message:
                await _upsert_call({
                    "call_id": call_id,
                    "message_left": plan.save_message,
                    "status": "message",
                    "contact_name": _contact_name(user, decision),
                })
            spoken = plan.speak
            if plan.need_twin:
                spoken = await _twin_spoken(
                    user=user,
                    text=user_text,
                    call_id=call_id,
                    decision=decision,
                )
            await websocket.send_json(retell.spoken_reply(
                spoken,
                response_id=response_id,
                end_call=plan.end_call,
                transfer_number=plan.transfer_number,
            ))
            live = retell.format_transcript(
                transcript,
                caller_name=_contact_name(user, decision),
            )
            patch: dict[str, Any] = {
                "call_id": call_id,
                "contact_name": _contact_name(user, decision),
                "call_state": session.phase,
            }
            if live:
                patch["transcript"] = live
            await _upsert_call(patch)
    except WebSocketDisconnect:
        logger.info("Retell LLM socket closed for %s", call_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Retell LLM socket error for %s: %s", call_id, exc)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
