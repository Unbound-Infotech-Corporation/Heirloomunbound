"""Maestro-style Models API — connect a cloud key or download a home-PC model.

Endpoints
---------
GET  /api/models/studio          — catalog + current assignments + home PC status
POST /api/models/connect         — paste a key, verify, enable, done
POST /api/models/disconnect      — turn a BYOK provider off
POST /api/models/assign          — set the model for one function (instant)
POST /api/models/pull            — queue `ollama pull` on the home PC
GET  /api/models/pulls/{cmd_id}  — poll a download
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from deps import db, get_current_user
from routers.providers import DEFAULT as PROVIDER_DEFAULT
from routers.providers import _load as load_local_providers
from services.llm_router import PROVIDERS, get_config, save_config
from services.model_catalog import (
    CLOUD_SERVICES,
    FUNCTIONS,
    LOCAL_MODELS,
    LOCAL_BY_ID,
    FUNCTION_BY_ID,
    assignment_for,
    is_known_cloud_provider,
    is_known_local_model,
    parse_option_id,
    ready_options,
)
from twin_tools import (
    _active_device,
    _device_is_awake,
    _queue_pc_command,
    _wait_for_command_result,
)

router = APIRouter(prefix="/models", tags=["models"])

_OLLAMA_BASE = "http://127.0.0.1:11434/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_cfg(cfg: dict) -> dict:
    out = {
        "providers": {},
        "task_routes": dict(cfg.get("task_routes") or {}),
        "task_models": dict(cfg.get("task_models") or {}),
        "local_task_routes": dict(cfg.get("local_task_routes") or {}),
        "fallback_order": list(cfg.get("fallback_order") or []),
    }
    for pid, pcfg in (cfg.get("providers") or {}).items():
        out["providers"][pid] = {
            "enabled": bool(pcfg.get("enabled")),
            "has_key": bool((pcfg.get("api_key") or "").strip()),
            "default_model": pcfg.get("default_model") or "",
            "monthly_budget_usd": float(pcfg.get("monthly_budget_usd") or 0),
        }
    return out


async def _home_pc(user_id: str) -> dict:
    dev = await _active_device(user_id)
    online = _device_is_awake(dev)
    models = list((dev or {}).get("local_models") or [])
    return {
        "connected": bool(dev),
        "online": online,
        "name": (dev or {}).get("name") or "",
        "last_seen": (dev or {}).get("last_seen"),
        "ollama": bool((dev or {}).get("ollama")),
        "local_models": models,
        "lan_url": (dev or {}).get("lan_url") or "",
    }


def _ready_options(cfg: dict, home: dict) -> list[dict]:
    return ready_options(cfg, home.get("local_models") or [])


def _assignment_for(fn: dict, cfg: dict) -> dict:
    return assignment_for(fn, cfg)


@router.get("/studio")
async def studio(user: dict = Depends(get_current_user)):
    cfg = await get_config(user["user_id"])
    home = await _home_pc(user["user_id"])
    assignments = {fn["id"]: _assignment_for(fn, cfg) for fn in FUNCTIONS}
    return {
        "services": CLOUD_SERVICES,
        "local_models": LOCAL_MODELS,
        "functions": FUNCTIONS,
        "config": _redact_cfg(cfg),
        "home": home,
        "options": _ready_options(cfg, home),
        "assignments": assignments,
    }


class ConnectIn(BaseModel):
    provider: str
    api_key: str = ""
    default_model: str = ""


@router.post("/connect")
async def connect(payload: ConnectIn, user: dict = Depends(get_current_user)):
    """One-click connect: verify the key (when BYOK), enable the provider, save."""
    pid = (payload.provider or "").strip()
    if not is_known_cloud_provider(pid) or pid not in PROVIDERS:
        raise HTTPException(400, f"unknown provider '{pid}'")
    spec = PROVIDERS[pid]
    cfg = await get_config(user["user_id"])
    pcfg = dict(cfg["providers"].get(pid) or {})
    key = (payload.api_key or "").strip() or (pcfg.get("api_key") or "").strip()

    if spec["byok"]:
        if not key:
            raise HTTPException(400, "Paste an API key to connect this service.")
        try:
            client = AsyncOpenAI(base_url=spec["base_url"], api_key=key, timeout=20.0)
            await client.chat.completions.create(
                model=spec["default_model"],
                messages=[{"role": "user", "content": "Say ok."}],
                max_tokens=4,
                temperature=0,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"That key didn't work: {str(exc)[:180]}") from exc

    pcfg["enabled"] = True
    if key:
        pcfg["api_key"] = key
    if payload.default_model.strip():
        pcfg["default_model"] = payload.default_model.strip()
    elif not pcfg.get("default_model"):
        pcfg["default_model"] = spec["default_model"]
    cfg["providers"][pid] = pcfg
    saved = await save_config(user["user_id"], cfg)
    return {"ok": True, "provider": pid, "config": _redact_cfg(saved)}


class DisconnectIn(BaseModel):
    provider: str


@router.post("/disconnect")
async def disconnect(payload: DisconnectIn, user: dict = Depends(get_current_user)):
    pid = (payload.provider or "").strip()
    if pid == "emergent":
        raise HTTPException(400, "The Heirloom key stays on so the twin never bricks.")
    if pid not in PROVIDERS:
        raise HTTPException(400, f"unknown provider '{pid}'")
    cfg = await get_config(user["user_id"])
    pcfg = dict(cfg["providers"].get(pid) or {})
    pcfg["enabled"] = False
    cfg["providers"][pid] = pcfg
    # Any function pointing at this provider falls back to Emergent.
    for task, routed in list((cfg.get("task_routes") or {}).items()):
        if routed == pid:
            cfg["task_routes"][task] = "emergent"
    saved = await save_config(user["user_id"], cfg)
    return {"ok": True, "provider": pid, "config": _redact_cfg(saved)}


class AssignIn(BaseModel):
    function: str
    option_id: str = ""
    provider: str = ""
    model: str = ""


@router.post("/assign")
async def assign(payload: AssignIn, user: dict = Depends(get_current_user)):
    """Instant per-function model pick. Click → saved. No extra setup."""
    fn = FUNCTION_BY_ID.get((payload.function or "").strip())
    if not fn:
        raise HTTPException(400, f"unknown function '{payload.function}'")
    task = fn["task"]
    if payload.option_id.strip():
        try:
            provider, model = parse_option_id(payload.option_id.strip())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        provider = (payload.provider or "").strip()
        model = (payload.model or "").strip()
    if not provider or not model:
        raise HTTPException(400, "Pick a model first.")

    cfg = await get_config(user["user_id"])
    local_routes = dict(cfg.get("local_task_routes") or {})
    task_models = dict(cfg.get("task_models") or {})
    task_routes = dict(cfg.get("task_routes") or {})

    if provider == "local":
        local_routes[task] = model
        await _ensure_local_subsystem(user["user_id"], model)
    else:
        if provider not in PROVIDERS:
            raise HTTPException(400, f"unknown provider '{provider}'")
        local_routes.pop(task, None)
        task_routes[task] = provider
        task_models[task] = model
        # Flip the provider on if the owner already connected a key (or it's Emergent).
        pcfg = dict(cfg["providers"].get(provider) or {})
        if (not PROVIDERS[provider]["byok"]) or (pcfg.get("api_key") or "").strip():
            pcfg["enabled"] = True
        pcfg["default_model"] = model
        cfg["providers"][provider] = pcfg

    cfg["local_task_routes"] = local_routes
    cfg["task_models"] = task_models
    cfg["task_routes"] = task_routes
    saved = await save_config(user["user_id"], cfg)
    return {
        "ok": True,
        "function": fn["id"],
        "assignment": _assignment_for(fn, saved),
        "config": _redact_cfg(saved),
    }


async def _ensure_local_subsystem(user_id: str, model: str) -> None:
    """When a local model is assigned, point the matching subsystem at Ollama
    so the desktop app picks it up without a second settings screen.
    """
    spec = LOCAL_BY_ID.get(model) or {}
    kind = spec.get("kind") or "chat"
    subsystem = {
        "vision": "image",
        "embeddings": "embeddings",
        "chat": "chat",
    }.get(kind, "chat")
    cfg = await load_local_providers(user_id)
    slot = dict(cfg.get(subsystem) or dict(PROVIDER_DEFAULT[subsystem]))
    slot["enabled"] = True
    slot["base_url"] = slot.get("base_url") or _OLLAMA_BASE
    slot["model"] = model
    slot["provider_type"] = "openai_compat"
    cfg[subsystem] = slot
    cfg["user_id"] = user_id
    cfg["updated_at"] = _now()
    await db.user_providers.replace_one({"user_id": user_id}, cfg, upsert=True)


class PullIn(BaseModel):
    model: str = Field(..., min_length=1, max_length=80)


@router.post("/pull")
async def pull(payload: PullIn, user: dict = Depends(get_current_user)):
    """Queue an Ollama download on the home PC. The UI polls /pulls/{cmd_id}."""
    model = payload.model.strip()
    if not (is_known_local_model(model) or ":" in model or model.replace(".", "").replace("-", "").isalnum()):
        raise HTTPException(400, f"unknown local model '{model}'")
    home = await _home_pc(user["user_id"])
    if not home["connected"]:
        raise HTTPException(
            409,
            "Open the Heirloom desktop app on your home computer first — downloads run there, not in the cloud.",
        )
    cmd_id = await _queue_pc_command(user["user_id"], "pull_model", {"model": model})
    await db.model_pulls.update_one(
        {"cmd_id": cmd_id},
        {"$set": {
            "cmd_id": cmd_id,
            "user_id": user["user_id"],
            "model": model,
            "status": "queued",
            "created_at": _now(),
        }},
        upsert=True,
    )
    return {
        "ok": True,
        "cmd_id": cmd_id,
        "model": model,
        "status": "queued",
        "home_online": home["online"],
        "hint": None if home["online"] else "Your PC will start the download the next time the desktop app is open.",
    }


@router.get("/pulls/{cmd_id}")
async def pull_status(cmd_id: str, user: dict = Depends(get_current_user)):
    doc = await db.companion_commands.find_one(
        {"cmd_id": cmd_id, "user_id": user["user_id"]},
        {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "download not found")
    status = doc.get("status") or "queued"
    result = doc.get("result") or ""
    done = status in ("done", "error")
    if done:
        await db.model_pulls.update_one(
            {"cmd_id": cmd_id, "user_id": user["user_id"]},
            {"$set": {"status": status, "result": result[:500], "completed_at": _now()}},
        )
        if status == "done":
            await _ensure_local_subsystem(user["user_id"], (doc.get("payload") or {}).get("model") or "")
    return {
        "cmd_id": cmd_id,
        "status": status,
        "done": done,
        "ok": status == "done",
        "output": result[:400],
        "model": (doc.get("payload") or {}).get("model"),
    }


class RefreshIn(BaseModel):
    dummy: Optional[str] = None


@router.post("/local/refresh")
async def refresh_local(user: dict = Depends(get_current_user)):
    """Ask the home PC to re-list installed Ollama models."""
    home = await _home_pc(user["user_id"])
    if not home["connected"]:
        raise HTTPException(409, "No home PC is paired yet.")
    cmd_id = await _queue_pc_command(user["user_id"], "list_models", {})
    # Short wait — `ollama list` is instant when the app is awake.
    if home["online"]:
        await _wait_for_command_result(cmd_id, user["user_id"], timeout=12.0)
    return {"ok": True, "cmd_id": cmd_id, "home": await _home_pc(user["user_id"])}
