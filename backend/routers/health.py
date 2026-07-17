"""Production readiness / health probes for Emergent ops.

GET /api/health       — deep readiness (config flags, no secrets)
GET /api/health/ping  — cheap liveness for uptime monitors
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter
from motor.motor_asyncio import AsyncIOMotorClient

from deps import DB_NAME, MONGO_URL

router = APIRouter(prefix="/health", tags=["health"])

PROD_DOMAIN = "https://heirloomunbound.com"


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _present(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


@router.get("/ping")
async def ping():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


@router.get("")
@router.get("/")
async def health():
    """Operator-facing readiness report. Never returns secret values."""
    mongo_ok = False
    mongo_error = None
    try:
        client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=2500)
        await client.admin.command("ping")
        mongo_ok = True
        client.close()
    except Exception as exc:  # noqa: BLE001
        mongo_error = type(exc).__name__

    public_backend = os.environ.get("PUBLIC_BACKEND_URL", "").strip().rstrip("/")
    public_frontend = os.environ.get("PUBLIC_FRONTEND_URL", "").strip().rstrip("/")
    sender = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev").strip()
    stripe_key = os.environ.get("STRIPE_API_KEY", "").strip()

    checks = {
        "mongo": mongo_ok,
        "emergent_llm_key": _present("EMERGENT_LLM_KEY"),
        "stripe_api_key": bool(stripe_key),
        "stripe_live_mode": bool(stripe_key) and stripe_key.startswith("sk_live"),
        "stripe_webhook_secret": _present("STRIPE_WEBHOOK_SECRET"),
        "stripe_payment_link": _present("STRIPE_PAYMENT_LINK_URL"),
        "resend_api_key": _present("RESEND_API_KEY"),
        "resend_prod_sender": bool(sender) and sender != "onboarding@resend.dev",
        "public_backend_url": bool(public_backend),
        "public_frontend_url": bool(public_frontend),
        "cors_origins": _present("CORS_ORIGINS") or bool(public_backend),
    }

    sale_ready = all(
        [
            checks["mongo"],
            checks["emergent_llm_key"],
            checks["stripe_api_key"],
            checks["stripe_webhook_secret"],
            checks["stripe_payment_link"],
            checks["resend_api_key"],
            checks["resend_prod_sender"],
            checks["public_backend_url"],
            checks["public_frontend_url"],
        ]
    )

    missing = [k for k, ok in checks.items() if not ok]
    status = "ok" if mongo_ok and checks["emergent_llm_key"] else "degraded"
    if not mongo_ok:
        status = "down"

    return {
        "app": "digital-heirloom",
        "status": status,
        "sale_ready": sale_ready,
        "enforce_purchase": _truthy("ENFORCE_PURCHASE"),
        "db_name": DB_NAME,
        "public_backend_url": public_backend or None,
        "public_frontend_url": public_frontend or None,
        "recommended_prod_domain": PROD_DOMAIN,
        "checks": checks,
        "missing": missing,
        "mongo_error": mongo_error,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
