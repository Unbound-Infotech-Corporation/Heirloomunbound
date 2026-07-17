"""Shared dependencies: Mongo client, auth middleware."""
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException, Request, status
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# When true (production sale mode), authenticated users must have purchased
# the lifetime license (or be marked tester/admin). Preview stays open by default.
ENFORCE_PURCHASE = os.environ.get("ENFORCE_PURCHASE", "").strip().lower() in {
    "1", "true", "yes", "on",
}

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


def _extract_token(request: Request) -> str | None:
    token = request.cookies.get("session_token")
    if token:
        return token
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


async def get_current_user(request: Request) -> dict:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    expires_at = session.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if user.get("account_status") == "refunded":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account refunded — access revoked. Contact support@heirloom.app",
        )

    # Bind to Sentry so any error during this request carries the user_id.
    # No-op if Sentry isn't initialised.
    try:
        import sentry_sdk  # local import — keeps deps.py import-time cheap
        sentry_sdk.set_user({"id": user["user_id"], "email": user.get("email", "")})
    except Exception:  # noqa: BLE001
        pass
    return user


def user_has_paid_access(user: dict) -> bool:
    """Lifetime buyers, platform testers, and admins get full product access."""
    if user.get("purchased_lifetime"):
        return True
    if user.get("is_tester") or user.get("is_admin"):
        return True
    return False


async def require_paid_user(request: Request) -> dict:
    """Like get_current_user, but optionally enforces the $79 lifetime purchase.

    Set ENFORCE_PURCHASE=true on Emergent production when you are ready to sell.
    Leave unset on preview so Google login stays open for demos and testing.
    """
    user = await get_current_user(request)
    if not ENFORCE_PURCHASE:
        return user
    if user_has_paid_access(user):
        return user
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail="Lifetime license required. Purchase at /buy",
    )
