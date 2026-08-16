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
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel

from deps import db, get_current_user
from services.llm_router import (
    DEFAULT_CONFIG,
    PRESETS,
    PRICING,
    PROVIDERS,
    TASKS,
    chat_once,
    chat_stream,
    daily_spend_series,
    get_config,
    month_end_projections,
    projection_history,
    resolve_provider,
    save_config,
    snapshot_projections,
    usage_summary,
)
from utils import rate_limit

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
    task_models: Optional[dict[str, str]] = None
    local_task_routes: Optional[dict[str, str]] = None


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
        "task_models": payload.task_models if payload.task_models is not None else existing.get("task_models") or {},
        "local_task_routes": payload.local_task_routes if payload.local_task_routes is not None else existing.get("local_task_routes") or {},
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
    # Protect the operator-funded Emergent key + any BYOK budget from runaway UI.
    await rate_limit(user["user_id"], "routing", max_calls=20, per_seconds=60)
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
    await rate_limit(user["user_id"], "routing", max_calls=20, per_seconds=60)

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


@router.get("/usage/daily")
async def get_usage_daily(days: int = 30, user: dict = Depends(get_current_user)):
    """Per-day cost buckets per provider — powers the sparkline chart on
    the frontend Router page.
    """
    return await daily_spend_series(user["user_id"], days=days)


@router.get("/usage/projection")
async def get_usage_projection(user: dict = Depends(get_current_user)):
    """Extrapolate this month's spend to month-end per provider.

    Returns `{provider_id: {mtd_usd, projected_month_end_usd, days_elapsed,
    days_in_month}}` — used by the Routing page to show a "projected" chip
    beside each provider's monthly budget cap.
    """
    return await month_end_projections(user["user_id"])


@router.get("/usage/projection/history")
async def get_projection_history(days: int = 14, user: dict = Depends(get_current_user)):
    """Per-day snapshots of the month-end projection over the last N days.

    Powers the "trend" chart on the Routing page so users can see whether
    their spend estimate is rising or falling week over week.
    """
    return await projection_history(user["user_id"], days=days)


# --------- Provider Templates (built-in presets + user-saved) ---------
async def _load_user_templates(user_id: str) -> list[dict]:
    cursor = db.user_templates.find(
        {"user_id": user_id}, {"_id": 0, "user_id": 0}
    ).sort("created_at", 1)
    return await cursor.to_list(length=200)


@router.get("/templates")
async def list_templates(user: dict = Depends(get_current_user)):
    """Enumerate one-click routing presets — built-ins first, then any
    templates the user has saved themselves. Returned to the client so the
    UI can render a picker without hard-coding names.
    """
    out = []
    for tid, spec in PRESETS.items():
        required = sorted({pid for pid in spec["task_routes"].values()})
        out.append({
            "id": tid, "label": spec["label"], "blurb": spec["blurb"],
            "task_routes": spec["task_routes"],
            "required_providers": required,
            "kind": "builtin",
        })
    for row in await _load_user_templates(user["user_id"]):
        out.append({
            "id": row["template_id"],
            "label": row["label"],
            "blurb": row.get("blurb") or "Saved by you",
            "task_routes": row["task_routes"],
            "required_providers": sorted({pid for pid in row["task_routes"].values()}),
            "kind": "custom",
            "created_at": row.get("created_at"),
        })
    return out


@router.get("/templates/preview")
async def preview_template(template_id: str, user: dict = Depends(get_current_user)):
    """Show what a template would change WITHOUT applying it.

    Returns a diff array + the resulting task_routes so the UI can display
    a "here's what will change" table before the user confirms.
    """
    preset = PRESETS.get(template_id)
    if not preset:
        # Custom template?
        custom = await db.user_templates.find_one(
            {"user_id": user["user_id"], "template_id": template_id},
            {"_id": 0},
        )
        if not custom:
            raise HTTPException(404, f"unknown template '{template_id}'")
        target_routes = custom["task_routes"]
        label = custom["label"]
    else:
        target_routes = preset["task_routes"]
        label = preset["label"]

    existing = await get_config(user["user_id"])
    current_routes = existing["task_routes"]
    diff: list[dict] = []
    for tid in TASKS:
        cur = current_routes.get(tid, TASKS[tid]["default"])
        new = target_routes.get(tid, cur)
        if cur != new:
            diff.append({
                "task": tid, "task_label": TASKS[tid]["label"],
                "from": cur, "to": new,
            })
    return {
        "template_id": template_id, "label": label,
        "current_routes": current_routes,
        "new_routes": {**current_routes, **target_routes},
        "diff": diff,
    }


class ApplyTemplateIn(BaseModel):
    template_id: str


@router.post("/templates/apply")
async def apply_template(payload: ApplyTemplateIn, user: dict = Depends(get_current_user)):
    """Apply a preset OR user-saved custom template to the caller's routing
    config. Only touches `task_routes` — API keys, enabled flags and budget
    caps are preserved.

    Returns the updated (redacted) config plus a `warnings` list naming any
    providers the template routes to that aren't currently enabled / keyed.
    """
    preset = PRESETS.get(payload.template_id)
    if preset:
        target_routes = preset["task_routes"]
    else:
        custom = await db.user_templates.find_one(
            {"user_id": user["user_id"], "template_id": payload.template_id},
            {"_id": 0, "task_routes": 1},
        )
        if not custom:
            raise HTTPException(400, f"unknown template '{payload.template_id}'")
        target_routes = custom["task_routes"]

    existing = await get_config(user["user_id"])
    new_cfg = {
        "providers": existing["providers"],
        "task_routes": {**existing["task_routes"], **target_routes},
        "task_models": existing.get("task_models") or {},
        "local_task_routes": existing.get("local_task_routes") or {},
        "fallback_order": existing["fallback_order"],
    }
    saved = await save_config(user["user_id"], new_cfg)

    warnings: list[str] = []
    for pid in set(target_routes.values()):
        pcfg = saved["providers"].get(pid) or {}
        if not pcfg.get("enabled"):
            warnings.append(f"{pid} is disabled — routes will fall back to Emergent until you enable it")
        elif PROVIDERS[pid]["byok"] and not (pcfg.get("api_key") or "").strip():
            warnings.append(f"{pid} has no API key — routes will fall back until you paste one")

    return {"config": _redact_keys(saved), "template": payload.template_id, "warnings": warnings}


# ---- Custom (user-saved) templates ----
class SaveTemplateIn(BaseModel):
    label: str
    blurb: str = ""


@router.post("/templates/save")
async def save_current_as_template(
    payload: SaveTemplateIn,
    user: dict = Depends(get_current_user),
):
    """Snapshot the caller's current `task_routes` into a custom template
    that then appears alongside the built-in presets.
    """
    label = (payload.label or "").strip()
    if not label:
        raise HTTPException(400, "label is required")
    if len(label) > 60:
        raise HTTPException(400, "label too long (max 60 chars)")

    cfg = await get_config(user["user_id"])
    template_id = f"user_{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "template_id": template_id,
        "user_id": user["user_id"],
        "label": label,
        "blurb": (payload.blurb or "").strip()[:200],
        "task_routes": dict(cfg["task_routes"]),
        "created_at": now,
    }
    await db.user_templates.insert_one(doc)
    doc.pop("_id", None)
    return {**doc, "user_id": None}  # never echo user_id back


@router.delete("/templates/{template_id}")
async def delete_user_template(template_id: str, user: dict = Depends(get_current_user)):
    if not template_id.startswith("user_"):
        raise HTTPException(400, "only user-saved templates can be deleted")
    res = await db.user_templates.delete_one(
        {"user_id": user["user_id"], "template_id": template_id}
    )
    if res.deleted_count == 0:
        raise HTTPException(404, "template not found")
    return {"ok": True, "template_id": template_id}


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
    """Latest red/green status for each provider — filtered to the caller's
    currently-enabled providers. Stale rows from disabled providers are
    surfaced as status='unknown' so the UI doesn't lie.
    """
    from services.provider_health import get_health_for_user
    cfg = await get_config(user["user_id"])
    rows = await get_health_for_user(user["user_id"])
    enabled = {pid for pid, pcfg in cfg["providers"].items() if pcfg.get("enabled")}
    out = []
    for r in rows:
        if r["provider"] not in enabled:
            r = {**r, "status": "unknown", "error": "disabled"}
        out.append(r)
    return out


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
    else:
        result = await refresh_user(user["user_id"])
    # Strip user_id for response symmetry with GET /health.
    def _clean(r: dict) -> dict:
        return {k: v for k, v in r.items() if k != "user_id"}
    if isinstance(result, list):
        return [_clean(r) for r in result]
    return [_clean(result)]
