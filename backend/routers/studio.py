"""Studio API — audio mixer settings + automated model routing.

The dedicated PC (companion) is the runtime. This router is the control
surface the web workspace and the desktop MDI both talk to:

- GET/PUT /api/studio/audio     persisted mixer (devices, gain, gate, volume)
- GET     /api/studio/models    catalog + probe of what's actually available
- PUT     /api/studio/models    choose a backend per feature
- POST    /api/studio/models/provision
        one-click: queue `provision_models` on the companion so the 5090
        machine downloads Whisper/Piper/Ollama artifacts without a wizard.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from deps import db, get_current_user
from model_router import (
    effective_model_map,
    resolve_stt_backend,
    resolve_tts_backend,
    resolve_twin_backend,
    runtime_probe_from_user,
)
from studio_defaults import (
    FEATURE_MODELS,
    BACKEND_CREDENTIALS,
    backends_for_feature,
    clamp_audio,
    clamp_model_map,
    credential_for_backend,
    default_model_map,
)

router = APIRouter(prefix="/studio", tags=["studio"])


async def get_studio_user(request: Request) -> dict:
    """Accept a web session *or* the dedicated-PC device token so the
    mixer/models windows on the companion can persist settings."""
    try:
        return await get_current_user(request)
    except HTTPException as exc:
        if exc.status_code not in (401, 403):
            raise
    from routers.companion import get_device_user

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    ctx = await get_device_user(auth)
    return ctx["user"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_audio(user: dict) -> dict:
    return clamp_audio(user.get("studio_audio"))


def _user_models(user: dict) -> dict:
    return clamp_model_map(user.get("studio_models"))


# ---------- Audio mixer ----------
class AudioUpdate(BaseModel):
    input_device_id: Optional[str] = None
    output_device_id: Optional[str] = None
    input_gain: Optional[int] = Field(default=None, ge=0, le=200)
    output_volume: Optional[int] = Field(default=None, ge=0, le=100)
    mute_input: Optional[bool] = None
    mute_output: Optional[bool] = None
    noise_gate_db: Optional[int] = Field(default=None, ge=-80, le=0)
    noise_suppression: Optional[bool] = None
    high_pass_hz: Optional[int] = Field(default=None, ge=0, le=400)
    monitor_input: Optional[bool] = None
    sample_rate: Optional[int] = None
    live_listen: Optional[bool] = None
    vad_hangover_ms: Optional[int] = Field(default=None, ge=200, le=3000)


@router.get("/audio")
async def get_audio(user: dict = Depends(get_studio_user)):
    return {"settings": _user_audio(user), "updated_at": user.get("studio_audio_updated_at")}


@router.put("/audio")
async def put_audio(payload: AudioUpdate, user: dict = Depends(get_studio_user)):
    current = _user_audio(user)
    patch = payload.model_dump(exclude_none=True)
    merged = clamp_audio({**current, **patch})
    now = _now_iso()
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"studio_audio": merged, "studio_audio_updated_at": now}},
    )
    return {"settings": merged, "updated_at": now}


# ---------- Models ----------
def _probe_cloud(user: dict) -> dict[str, dict]:
    """What's wired without touching the dedicated PC."""
    el_user = bool((user.get("elevenlabs_api_key") or "").strip())
    el_admin = bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())
    did_user = bool((user.get("d_id_api_key") or "").strip())
    did_admin = bool(os.environ.get("D_ID_API_KEY", "").strip())
    llm = bool(os.environ.get("EMERGENT_LLM_KEY", "").strip())
    return {
        "cloud_whisper": {"available": llm, "detail": "Whisper via Emergent key" if llm else "No EMERGENT_LLM_KEY"},
        "cloud_claude": {"available": llm, "detail": "Claude via Emergent key" if llm else "No EMERGENT_LLM_KEY"},
        "openai_tts": {"available": llm, "detail": "OpenAI TTS via Emergent key" if llm else "No EMERGENT_LLM_KEY"},
        "elevenlabs": {
            "available": el_user or el_admin,
            "detail": "your key" if el_user else ("admin key" if el_admin else "not configured"),
        },
        "did": {
            "available": did_user or did_admin,
            "detail": "your key" if did_user else ("admin key" if did_admin else "not configured"),
        },
        "waveform": {"available": True, "detail": "always on"},
        "auto": {"available": True, "detail": "picks the best available backend"},
    }


def _companion_probe(device: dict | None) -> dict:
    if not device:
        return {
            "connected": False,
            "gpu": None,
            "ollama": None,
            "whisper": None,
            "piper": None,
            "detail": "No companion PC has checked in. Open Heirloom on the dedicated machine.",
        }
    last = device.get("last_seen") or device.get("last_heartbeat") or ""
    probe = device.get("runtime_probe") or {}
    return {
        "connected": True,
        "name": device.get("name") or "PC",
        "last_seen": last,
        "gpu": probe.get("gpu"),
        "ollama": probe.get("ollama"),
        "whisper": probe.get("whisper"),
        "piper": probe.get("piper"),
        "detail": probe.get("detail") or "Companion online.",
    }


def _user_key_configured(user: dict, service: str) -> tuple[bool, str]:
    """Return (configured, source) for a credential service id."""
    fields = {
        "elevenlabs": "elevenlabs_api_key",
        "did": "d_id_api_key",
        "fal": "fal_api_key",
    }
    field = fields.get(service)
    if not field:
        return False, "none"
    has_user = bool((user.get(field) or "").strip())
    admin = {
        "elevenlabs": os.environ.get("ELEVENLABS_API_KEY", "").strip(),
        "did": os.environ.get("D_ID_API_KEY", "").strip(),
        "fal": os.environ.get("FAL_KEY", "").strip(),
    }
    has_admin = bool(admin.get(service))
    if has_user:
        return True, "you"
    if has_admin:
        return True, "admin"
    return False, "none"


def _llm_available() -> bool:
    return bool(os.environ.get("EMERGENT_LLM_KEY", "").strip())


def _feature_readiness(
    feature_id: str,
    chosen_backend: str,
    user: dict,
    cloud: dict,
    companion: dict,
) -> dict:
    """Whether the selected backend can run right now + what it resolves to."""
    probe = companion if companion.get("connected") else runtime_probe_from_user(user)
    eff = effective_model_map(user, probe if isinstance(probe, dict) else None)

    if feature_id == "stt":
        effective = resolve_stt_backend({feature_id: chosen_backend, **eff}, probe)
        if effective == "local_whisper":
            ready = bool((companion.get("whisper") or {}).get("ready"))
            detail = (companion.get("whisper") or {}).get("detail") or "Provision Whisper on the dedicated PC"
        else:
            ready = _llm_available()
            detail = cloud.get("cloud_whisper", {}).get("detail") or "Cloud STT unavailable"
    elif feature_id == "tts":
        effective = resolve_tts_backend(
            {feature_id: chosen_backend, **eff},
            probe,
            has_voice_clone=bool((user.get("elevenlabs_voice_id") or "").strip()),
        )
        if effective == "elevenlabs":
            key_ok, src = _user_key_configured(user, "elevenlabs")
            has_voice = bool((user.get("elevenlabs_voice_id") or "").strip())
            ready = key_ok and has_voice
            if not key_ok:
                detail = "Add your ElevenLabs key below (or use OpenAI/local Piper)"
            elif not has_voice:
                detail = "ElevenLabs key OK — clone a voice in Settings → Voice"
            else:
                detail = f"Ready ({src} key, voice cloned)"
        elif effective == "local_piper":
            ready = bool((companion.get("piper") or {}).get("ready"))
            detail = (companion.get("piper") or {}).get("detail") or "Provision Piper on the dedicated PC"
        else:
            ready = _llm_available()
            detail = "OpenAI TTS via hosted key" if ready else "No hosted LLM key on server"
    elif feature_id == "twin":
        effective = resolve_twin_backend({feature_id: chosen_backend, **eff}, probe)
        if effective == "ollama":
            ready = bool((companion.get("ollama") or {}).get("ready"))
            detail = (companion.get("ollama") or {}).get("detail") or "Start Ollama on the dedicated PC"
        else:
            ready = _llm_available()
            detail = "Claude via hosted key" if ready else "No hosted LLM key — use Ollama locally"
    elif feature_id == "vision":
        effective = eff.get("vision", chosen_backend)
        if effective == "ollama":
            ready = bool((companion.get("ollama") or {}).get("ready"))
            detail = (companion.get("ollama") or {}).get("detail") or "Ollama + llava on dedicated PC"
        else:
            ready = _llm_available()
            detail = "Claude vision via hosted key" if ready else "No hosted vision key"
    elif feature_id == "avatar":
        effective = chosen_backend if chosen_backend != "auto" else ("did" if _user_key_configured(user, "did")[0] else "waveform")
        if effective == "did":
            ready, src = _user_key_configured(user, "did")
            detail = f"D-ID ready ({src})" if ready else "Add D-ID key below"
        else:
            ready = True
            detail = "Portrait + waveform (no third-party key)"
    else:
        effective = chosen_backend
        ready = True
        detail = ""

    cred = None
    cred_backend = chosen_backend if chosen_backend != "auto" else effective
    if cred_backend in BACKEND_CREDENTIALS:
        cred_meta = credential_for_backend(cred_backend)
    elif chosen_backend in BACKEND_CREDENTIALS:
        cred_meta = credential_for_backend(chosen_backend)
    else:
        cred_meta = None

    if cred_meta:
        svc = cred_meta["service"]
        configured, source = _user_key_configured(user, svc)
        credential = {
            **cred_meta,
            "configured": configured,
            "source": source,
        }
    else:
        credential = None

    return {
        "effective": effective,
        "ready": ready,
        "detail": detail,
        "credential": credential,
        "needs_companion": chosen_backend in {"local_whisper", "local_piper", "ollama", "auto"}
        and feature_id in {"stt", "tts", "twin", "vision"},
    }


@router.get("/models")
async def get_models(user: dict = Depends(get_studio_user)):
    chosen = _user_models(user)
    cloud = _probe_cloud(user)
    device = await db.companion_devices.find_one(
        {"user_id": user["user_id"], "revoked": {"$ne": True}},
        {"_id": 0},
        sort=[("last_seen", -1)],
    )
    companion = _companion_probe(device)
    features = []
    for spec in FEATURE_MODELS:
        backends = []
        for b in spec["backends"]:
            avail = True
            detail = ""
            if b["id"] in cloud:
                avail = bool(cloud[b["id"]]["available"])
                detail = cloud[b["id"]]["detail"]
            elif b["id"] == "local_whisper":
                avail = bool((companion.get("whisper") or {}).get("ready"))
                detail = (companion.get("whisper") or {}).get("detail") or "needs provision on the PC"
            elif b["id"] == "local_piper":
                avail = bool((companion.get("piper") or {}).get("ready"))
                detail = (companion.get("piper") or {}).get("detail") or "needs provision on the PC"
            elif b["id"] == "ollama":
                avail = bool((companion.get("ollama") or {}).get("ready"))
                detail = (companion.get("ollama") or {}).get("detail") or "Ollama not detected"
            cred_meta = credential_for_backend(b["id"])
            backends.append(
                {
                    **b,
                    "available": avail,
                    "detail": detail,
                    "needs_key": bool(cred_meta),
                    "credential_service": cred_meta["service"] if cred_meta else None,
                }
            )
        status = _feature_readiness(spec["id"], chosen[spec["id"]], user, cloud, companion)
        features.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "purpose": spec["purpose"],
                "selected": chosen[spec["id"]],
                "local_artifact": spec["local_artifact"],
                "backends": backends,
                "status": status,
            }
        )
    return {
        "features": features,
        "map": chosen,
        "effective": effective_model_map(user, companion if companion.get("connected") else runtime_probe_from_user(user)),
        "companion": companion,
        "hosted_llm": _llm_available(),
        "updated_at": user.get("studio_models_updated_at"),
    }


class ModelMapUpdate(BaseModel):
    map: dict[str, str]


@router.put("/models")
async def put_models(payload: ModelMapUpdate, user: dict = Depends(get_studio_user)):
    current = _user_models(user)
    merged = clamp_model_map({**current, **payload.map})
    now = _now_iso()
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"studio_models": merged, "studio_models_updated_at": now}},
    )
    return {"map": merged, "updated_at": now}


class FeatureBackendUpdate(BaseModel):
    backend: str


@router.patch("/models/{feature_id}")
async def patch_feature_backend(
    feature_id: str,
    payload: FeatureBackendUpdate,
    user: dict = Depends(get_studio_user),
):
    """Change one feature backend without touching the others."""
    allowed = backends_for_feature(feature_id)
    if not allowed:
        raise HTTPException(status_code=404, detail="Unknown feature")
    backend = (payload.backend or "").strip()
    if backend not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid backend for {feature_id}")
    current = _user_models(user)
    current[feature_id] = backend
    merged = clamp_model_map(current)
    now = _now_iso()
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"studio_models": merged, "studio_models_updated_at": now}},
    )
    return {"feature_id": feature_id, "backend": merged[feature_id], "map": merged, "updated_at": now}


@router.post("/models/{feature_id}/test")
async def test_feature_backend(feature_id: str, user: dict = Depends(get_studio_user)):
    """Live check: can this feature run with the current backend selection?"""
    allowed = backends_for_feature(feature_id)
    if not allowed:
        raise HTTPException(status_code=404, detail="Unknown feature")
    chosen = _user_models(user)
    cloud = _probe_cloud(user)
    device = await db.companion_devices.find_one(
        {"user_id": user["user_id"], "revoked": {"$ne": True}},
        {"_id": 0},
        sort=[("last_seen", -1)],
    )
    companion = _companion_probe(device)
    status = _feature_readiness(feature_id, chosen[feature_id], user, cloud, companion)
    return {
        "feature_id": feature_id,
        "selected": chosen[feature_id],
        "ok": bool(status["ready"]),
        "effective": status["effective"],
        "detail": status["detail"],
        "credential": status.get("credential"),
    }


async def _queue_provision(user: dict, features: list[str]) -> dict:
    device = await db.companion_devices.find_one(
        {"user_id": user["user_id"], "revoked": {"$ne": True}},
        {"_id": 0},
        sort=[("last_seen", -1)],
    )
    if not device:
        raise HTTPException(
            status_code=409,
            detail="No companion PC is registered. Open Heirloom on the dedicated machine first.",
        )
    chosen = _user_models(user)
    import uuid

    cmd_id = f"cmd_prov_{uuid.uuid4().hex[:10]}"
    now = _now_iso()
    doc = {
        "cmd_id": cmd_id,
        "user_id": user["user_id"],
        "kind": "provision_models",
        "payload": {"features": features, "map": chosen},
        "status": "queued",
        "result": None,
        "created_at": now,
        "completed_at": None,
    }
    await db.companion_commands.insert_one(doc)
    return {
        "queued": True,
        "cmd_id": cmd_id,
        "features": features,
        "hint": "The dedicated PC will download models on the next poll (~3s).",
    }


@router.post("/models/{feature_id}/provision")
async def provision_feature(feature_id: str, user: dict = Depends(get_studio_user)):
    """Provision local artifacts for a single feature (stt/twin/vision → Whisper+Ollama, etc.)."""
    known = {f["id"] for f in FEATURE_MODELS}
    if feature_id not in known:
        raise HTTPException(status_code=404, detail="Unknown feature")
    return await _queue_provision(user, [feature_id])


class ProvisionReq(BaseModel):
    features: Optional[list[str]] = None  # default: all that are set to auto/local


@router.post("/models/provision")
async def provision_models(payload: ProvisionReq, user: dict = Depends(get_studio_user)):
    """Queue a provision_models command on the companion. The desktop app
    downloads Whisper / talks to Ollama / writes the runtime probe. No
    interactive key-paste required for local backends."""
    chosen = _user_models(user)
    wanted = payload.features or [
        fid for fid, backend in chosen.items() if backend in {"auto", "local_whisper", "local_piper", "ollama"}
    ]
    return await _queue_provision(user, wanted)
