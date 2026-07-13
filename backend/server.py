"""FastAPI entrypoint for the Digital Heirloom / AI Twin app."""
import asyncio
import logging
import os
import re

# Sentry must initialise BEFORE FastAPI/app imports so it instruments correctly.
# Quiet no-op if SENTRY_DSN isn't set — keeps dev/test environments clean.
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "preview"),
        # Low sample rate keeps Heirloom comfortably inside the free tier.
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_RATE", "0.05")),
        profiles_sample_rate=float(os.environ.get("SENTRY_PROFILES_RATE", "0.0")),
        send_default_pii=True,  # includes user_id we set via set_user
        # Drop noise — health checks pollute the dashboard otherwise.
        before_send=lambda event, _hint: (
            None
            if (event.get("request", {}) or {}).get("url", "").endswith(("/api/health", "/api/health/ping"))
            else event
        ),
        attach_stacktrace=True,
    )

from fastapi import APIRouter, FastAPI, Request
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from deps import db  # noqa: F401  -- ensures Mongo client is initialised early
from db_indexes import ensure_indexes
from routers import (
    archive,
    abilities,
    auth,
    photo_story,
    avatar,
    avatar_studio,
    billing,
    capture,
    companion,
    dashboard,
    dashboard_extra,
    desktop,
    email as email_router,
    fulfillment,
    heir_portal,
    heirs,
    interviewer,
    letters,
    live,
    memory,
    music,
    nudges,
    oauth,
    onboarding,
    personality,
    personas,
    photos,
    reminders,
    skills,
    social_import,
    sources,
    twin,
    user_keys,
    vault,
    voice,
    voice_clone,
)
from storage import init_storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Digital Heirloom — AI Twin", version="0.3.0")


@app.on_event("startup")
async def _startup():
    init_storage()
    await ensure_indexes()

    async def _letter_delivery_loop():
        # Deliver date-triggered sealed letters shortly after their day arrives.
        from routers.letters import deliver_due_letters
        while True:
            try:
                await deliver_due_letters()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger("server").warning("letter delivery loop error: %s", exc)
            await asyncio.sleep(900)  # every 15 minutes

    app.state.letter_task = asyncio.create_task(_letter_delivery_loop())


api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"app": "digital-heirloom", "status": "ok"}


api_router.include_router(auth.router)
api_router.include_router(archive.router)
api_router.include_router(abilities.router)
api_router.include_router(photo_story.router)
api_router.include_router(interviewer.router)
api_router.include_router(voice.router)
api_router.include_router(voice_clone.router)
api_router.include_router(twin.router)
api_router.include_router(social_import.router)
api_router.include_router(skills.router)
api_router.include_router(heirs.router)
api_router.include_router(dashboard.router)
api_router.include_router(dashboard_extra.router)
api_router.include_router(photos.router)
api_router.include_router(companion.router)
api_router.include_router(capture.router)
api_router.include_router(reminders.router)
api_router.include_router(onboarding.router)
api_router.include_router(sources.router)
api_router.include_router(letters.router)
api_router.include_router(heir_portal.router)
api_router.include_router(personality.router)
api_router.include_router(personas.router)
api_router.include_router(nudges.router)
api_router.include_router(memory.router)
api_router.include_router(music.router)
api_router.include_router(billing.router)
api_router.include_router(fulfillment.router)
api_router.include_router(avatar.router)
api_router.include_router(email_router.router)
api_router.include_router(oauth.router)
api_router.include_router(desktop.router)
api_router.include_router(vault.router)
api_router.include_router(live.router)
api_router.include_router(avatar_studio.router)
api_router.include_router(user_keys.router)

app.include_router(api_router)


# -------- Sentry debug endpoint --------
@app.get("/api/_sentry/debug")
async def _sentry_debug(secret: str = ""):
    """Triggers a deliberate ZeroDivisionError so we can confirm Sentry capture
    is wired correctly. Requires the secret env var to prevent random hits."""
    expected = os.environ.get("SENTRY_DEBUG_SECRET", "").strip()
    if not expected or secret != expected:
        return {"ok": False, "hint": "set SENTRY_DEBUG_SECRET and pass ?secret="}
    1 / 0  # noqa: B018 — this is the point


# -------- CORS: explicit allowlist + regex (security: SEC-001) --------
def _cors_allowed_origins() -> list[str]:
    """Build a strict origin allowlist from env. Never returns '*' when credentials are enabled."""
    raw = os.environ.get("CORS_ORIGINS", "")
    items = [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]
    # Always derive from PUBLIC_BACKEND_URL (since the app is single-origin: frontend = backend host)
    public = os.environ.get("PUBLIC_BACKEND_URL", "").strip().rstrip("/")
    if public and public not in items:
        items.append(public)
    return items


def _cors_origin_regex() -> str | None:
    """Allow Emergent preview/sub-domain origins via regex without baking exact URLs."""
    # Permit https://<anything>.emergentagent.com and http(s)://localhost:* for dev
    return r"^(https://[a-zA-Z0-9-]+\.emergentagent\.com|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?)$"


_allowed = _cors_allowed_origins()
if _allowed:
    logger.info(f"CORS allowed origins (exact): {_allowed}")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_allowed,
    allow_origin_regex=_cors_origin_regex(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    task = getattr(app.state, "letter_task", None)
    if task:
        task.cancel()
    from deps import client
    client.close()
