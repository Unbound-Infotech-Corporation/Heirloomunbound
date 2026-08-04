"""HTTP surface for the multi-provider LLM router.

Endpoints
---------
GET  /api/routing/catalog         — providers + tasks + pricing (public shape, no keys)
GET  /api/routing/config          — the caller's saved routing config
PUT  /api/routing/config          — replace the caller's routing config
POST /api/routing/chat            — send a one-shot chat message via the router
POST /api/routing/chat/stream     — SSE version of /chat
GET  /api/routing/usage           — aggregated usage over the last N days
GET  /api/routing/usage/events    — recent per-call events (paginated)
POST /api/routing/verify          — live-check a BYOK key against its provider
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from deps import db, get_current_user
from services.llm_router import (
    DEFAULT_CONFIG,
    PRICING,
    PROVIDERS,
    TASKS,
    chat_once,
    chat_stream,
    get_config,
    resolve_provider,
    save_config,
    usage_summary,
)

router = APIRouter(prefix="/routing", tags=["routing"])


@router.get("/catalog")
async def catalog():
    """Static reference data the frontend uses to render the config screen."""
    return {
        "providers": [
            {
                "id": pid,
                "label": spec["label"],
                "byok": spec["byok"],
                "default_model": spec["default_model"],
                "models": spec["models"],
                "base_url": spec.get("base_url"),
            }
            for pid, spec in PROVIDERS.items()
        ],
        "tasks": [
            {"id": tid, "label": spec["label"], "default_provider": spec["default"]}
            for tid, spec in TASKS.items()
        ],
        "pricing": [
            {"key": k, "input_per_1m": v[0], "output_per_1m": v[1]}
            for k, v in PRICING.items()
        ],
        "default_fallback_order": DEFAULT_CONFIG["fallback_order"],
    }


# --------- Config ---------
class ProviderCfgIn(BaseModel):
    enabled: bool = False
    api_key: str = ""
    default_model: str = ""
    monthly_budget_usd: float = 0.0


class RoutingConfigIn(BaseModel):
    providers: dict[str, ProviderCfgIn]
    task_routes: dict[str, str]
    fallback_order: list[str]


def _redact_keys(cfg: dict) -> dict:
    """Never return raw API keys to the client — send `has_key` flag only."""
    out = json.loads(json.dumps(cfg))  # deep copy
    for pid, pcfg in out.get("providers", {}).items():
        pcfg["has_key"] = bool((pcfg.get("api_key") or "").strip())
        pcfg["api_key"] = ""
    return out


@router.get("/config")
async def get_routing_config(user: dict = Depends(get_current_user)):
    cfg = await get_config(user["user_id"])
    return _redact_keys(cfg)


@router.put("/config")
async def put_routing_config(payload: RoutingConfigIn, user: dict = Depends(get_current_user)):
    # Preserve any previously-saved api_keys when the client posts an empty string
    # (that's how the UI signals "no change" — since we never return keys back to it).
    existing = await get_config(user["user_id"])
    merged_providers: dict = {}
    for pid, spec in PROVIDERS.items():
        incoming = payload.providers.get(pid)
        prev = existing["providers"].get(pid) or {}
        if incoming is None:
            merged_providers[pid] = prev
            continue
        merged_providers[pid] = {
            "enabled": bool(incoming.enabled),
            "api_key": (incoming.api_key or prev.get("api_key") or "").strip(),
            "default_model": incoming.default_model or spec["default_model"],
            "monthly_budget_usd": max(0.0, float(incoming.monthly_budget_usd or 0)),
        }
    # Only keep task routes we recognise
    task_routes = {tid: payload.task_routes.get(tid, TASKS[tid]["default"]) for tid in TASKS}
    fallback = [p for p in payload.fallback_order if p in PROVIDERS] or DEFAULT_CONFIG["fallback_order"]

    saved = await save_config(user["user_id"], {
        "providers": merged_providers,
        "task_routes": task_routes,
        "fallback_order": fallback,
    })
    return _redact_keys(saved)


# --------- Chat + Stream ---------
class ChatIn(BaseModel):
    task: str = "chat"
    messages: list[dict]
    provider: Optional[str] = None
    model: Optional[str] = None


@router.post("/chat")
async def chat(payload: ChatIn, user: dict = Depends(get_current_user)):
    if payload.task not in TASKS:
        raise HTTPException(400, f"unknown task '{payload.task}'")
    if payload.provider and payload.provider not in PROVIDERS:
        raise HTTPException(400, f"unknown provider '{payload.provider}'")
    return await chat_once(
        user["user_id"], payload.task, payload.messages,
        model_override=payload.model, provider_override=payload.provider,
    )


@router.post("/chat/stream")
async def chat_stream_endpoint(payload: ChatIn, user: dict = Depends(get_current_user)):
    if payload.task not in TASKS:
        raise HTTPException(400, f"unknown task '{payload.task}'")
    if payload.provider and payload.provider not in PROVIDERS:
        raise HTTPException(400, f"unknown provider '{payload.provider}'")

    async def gen():
        async for ev in chat_stream(
            user["user_id"], payload.task, payload.messages,
            model_override=payload.model, provider_override=payload.provider,
        ):
            yield f"data: {json.dumps(ev)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# --------- Usage ---------
@router.get("/usage")
async def get_usage(days: int = 30, user: dict = Depends(get_current_user)):
    return await usage_summary(user["user_id"], days=days)


@router.get("/usage/events")
async def get_usage_events(limit: int = 100, user: dict = Depends(get_current_user)):
    limit = max(1, min(int(limit or 100), 500))
    cursor = db.usage_events.find(
        {"user_id": user["user_id"]}, {"_id": 0, "user_id": 0},
    ).sort("ts", -1).limit(limit)
    return await cursor.to_list(length=limit)


# --------- Verify a BYOK key ---------
class VerifyIn(BaseModel):
    provider: str
    api_key: str


@router.post("/verify")
async def verify(payload: VerifyIn, user: dict = Depends(get_current_user)):
    """Send a tiny 'ping' completion to confirm the pasted key actually works."""
    spec = PROVIDERS.get(payload.provider)
    if not spec:
        raise HTTPException(400, f"unknown provider '{payload.provider}'")
    if not spec["byok"]:
        return {"ok": True, "note": "no key needed for this provider"}
    if not payload.api_key.strip():
        return {"ok": False, "error": "empty api key"}

    try:
        client = AsyncOpenAI(base_url=spec["base_url"], api_key=payload.api_key.strip(), timeout=20.0)
        resp = await client.chat.completions.create(
            model=spec["default_model"],
            messages=[{"role": "user", "content": "Say 'ok'."}],
            max_tokens=5,
            temperature=0,
        )
        text = (resp.choices[0].message.content if resp.choices else "") or ""
        return {"ok": True, "model": spec["default_model"], "sample": text.strip()[:40]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


# --------- Resolve (which provider will fire for a given task right now?) ---------
@router.get("/resolve")
async def resolve(task: str = "chat", user: dict = Depends(get_current_user)):
    if task not in TASKS:
        raise HTTPException(400, f"unknown task '{task}'")
    primary, chain = await resolve_provider(user["user_id"], task)
    return {"task": task, "primary": primary, "fallback_chain": chain}


# --------- Provider health checks ---------
@router.get("/health")
async def get_health(user: dict = Depends(get_current_user)):
    """Latest red/green status for each provider the caller has enabled."""
    from services.provider_health import get_health_for_user
    return await get_health_for_user(user["user_id"])


@router.post("/health/check")
async def force_check(provider: Optional[str] = None, user: dict = Depends(get_current_user)):
    """On-demand refresh — probes every enabled provider (or one if `provider`
    is passed). Called by the UI's 'Check now' button.
    """
    from services.provider_health import probe_provider, refresh_user
    if provider:
        if provider not in PROVIDERS:
            raise HTTPException(400, f"unknown provider '{provider}'")
        result = await probe_provider(user["user_id"], provider)
        return [result]
    return await refresh_user(user["user_id"])
