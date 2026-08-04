"""Local AI Providers — per-user config for routing LLM/TTS/STT/Image work
to a self-hosted endpoint on the owner's PC instead of our cloud defaults.

The desktop companion is what actually calls the local endpoints (only it can
reach 127.0.0.1 on the user's machine). This router just stores + returns the
config so it follows the user across devices and gets picked up by whichever
Heirloom desktop install is running.

Design:
    * Four subsystems: chat / tts / stt / image. Each has the same shape.
    * We accept any "OpenAI-compatible" endpoint URL for chat/tts/stt — that
      covers Ollama, LM Studio, LocalAI, Pinokio-hosted models, KoboldCPP,
      most self-hosted TTS servers (Kokoro-FastAPI, XTTS-v2 server), and
      most Whisper-server projects.
    * `image` supports a special `provider_type = "comfyui"` because ComfyUI's
      API is workflow-based, not OpenAI-shape. We only store the config here;
      the desktop knows how to speak both dialects.
    * API keys are optional (most local runtimes don't need one) and are
      stored as-is — this endpoint is per-user, cookie-authenticated, and
      the keys point at 127.0.0.1 anyway so blast radius is nil.

Endpoints:
    GET  /api/providers        — current user's config (creates defaults if none)
    PUT  /api/providers        — replace entire config
    POST /api/providers/reset  — wipe to defaults (cloud everywhere)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from deps import db, get_current_user

router = APIRouter(prefix="/providers", tags=["providers"])


# ---------------- schema ----------------
class SubsystemConfig(BaseModel):
    enabled: bool = False
    base_url: str = ""           # e.g. http://127.0.0.1:11434/v1
    api_key: str = ""            # optional — many local runtimes don't need one
    model: str = ""              # e.g. llama3.3:70b, kokoro-en-v1
    provider_type: Literal["openai_compat", "comfyui"] = "openai_compat"
    # image-only extras (ignored for other subsystems)
    comfy_workflow: Optional[str] = None    # workflow JSON as a string
    voice: Optional[str] = None             # tts-only: voice name / speaker id


class ProviderConfig(BaseModel):
    chat: SubsystemConfig = Field(default_factory=SubsystemConfig)
    tts: SubsystemConfig = Field(default_factory=SubsystemConfig)
    stt: SubsystemConfig = Field(default_factory=SubsystemConfig)
    image: SubsystemConfig = Field(default_factory=SubsystemConfig)
    embeddings: SubsystemConfig = Field(default_factory=SubsystemConfig)


DEFAULT = ProviderConfig().model_dump()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _load(user_id: str) -> dict:
    doc = await db.user_providers.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        return dict(DEFAULT)
    # Ensure every subsystem key is present (schema evolution safety)
    merged = dict(DEFAULT)
    for k in ("chat", "tts", "stt", "image", "embeddings"):
        if isinstance(doc.get(k), dict):
            merged[k] = {**DEFAULT[k], **doc[k]}
    return merged


def _redact_for_client(cfg: dict) -> dict:
    """Never send raw local api_keys back to the client — send `has_key` only.

    Security note (SEC-HARD-2): even though these keys are per-user and usually
    point at 127.0.0.1, echoing them back over the wire is an unnecessary
    disclosure surface (browser devtools, extensions, error logs). The desktop
    companion loads keys via /providers on the same authenticated session so
    it doesn't need them re-exposed here.
    """
    out = {}
    for k, v in cfg.items():
        if isinstance(v, dict) and "api_key" in v:
            key = (v.get("api_key") or "").strip()
            out[k] = {**v, "api_key": "", "has_key": bool(key)}
        else:
            out[k] = v
    return out


async def _load_with_secrets(user_id: str) -> dict:
    """Internal accessor: returns raw config including api_keys.

    Used by services that legitimately need the key (e.g. restoration router
    embedding it into a companion command payload sent to the desktop over the
    authenticated session).
    """
    return await _load(user_id)


# ---------------- endpoints ----------------
@router.get("")
async def get_providers(user: dict = Depends(get_current_user)):
    return _redact_for_client(await _load(user["user_id"]))


@router.put("")
async def put_providers(payload: ProviderConfig, user: dict = Depends(get_current_user)):
    incoming = payload.model_dump()
    # Preserve any previously-stored api_key when the client posts an empty
    # string (mirrors /routing/config so the UI can round-trip without
    # requiring the user to re-paste local keys).
    existing = await _load(user["user_id"])
    for k in ("chat", "tts", "stt", "image", "embeddings"):
        prev_key = ((existing.get(k) or {}).get("api_key") or "").strip()
        incoming_key = (incoming.get(k, {}).get("api_key") or "").strip()
        if not incoming_key and prev_key:
            incoming[k]["api_key"] = prev_key
    doc = {**incoming, "user_id": user["user_id"], "updated_at": _now()}
    await db.user_providers.replace_one({"user_id": user["user_id"]}, doc, upsert=True)
    return _redact_for_client(await _load(user["user_id"]))


@router.post("/reset")
async def reset_providers(user: dict = Depends(get_current_user)):
    await db.user_providers.delete_one({"user_id": user["user_id"]})
    return _redact_for_client(dict(DEFAULT))
