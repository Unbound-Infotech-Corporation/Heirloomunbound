"""Google and Microsoft account linking for calendar and email (opt-in).

Read and draft only. The scopes below are the whole grant; there is no send
scope for Microsoft and the calendar grants are read-only on both. Gmail has no
drafts-only scope, so ``gmail.compose`` is requested and Heirloom never calls
send with it (the provider's send method refuses, and the tests hold that).

Flow: Authorization Code with PKCE. The server keeps the verifier for ten
minutes; tokens are sealed with ``CONNECTOR_SECRET_KEY`` (Fernet) before they
reach Mongo, and the browser never sees them.

What a buyer configures (docs/LOCAL-SKILLS.md):
  Google:    GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
  Microsoft: MS_OAUTH_CLIENT_ID (public client; secret optional MS_OAUTH_CLIENT_SECRET)
  Both:      HEIRLOOM_OAUTH_REDIRECT_BASE, e.g. https://heirloom.local  (or http://127.0.0.1:8001 on a PC)
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

PENDING_TTL_SECONDS = 600


@dataclass(frozen=True)
class OAuthProvider:
    id: str
    label: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    client_id_env: str
    client_secret_env: str
    secret_required: bool
    extra: tuple[tuple[str, str], ...] = ()

    def client_id(self, env: Optional[dict] = None) -> str:
        return (env if env is not None else os.environ).get(self.client_id_env, "").strip()

    def client_secret(self, env: Optional[dict] = None) -> str:
        return (env if env is not None else os.environ).get(self.client_secret_env, "").strip()

    def configured(self, env: Optional[dict] = None) -> bool:
        return bool(self.client_id(env)) and (not self.secret_required or bool(self.client_secret(env)))


PROVIDERS: dict[str, OAuthProvider] = {
    "google": OAuthProvider(
        id="google",
        label="Google (Gmail and Calendar)",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=(
            "openid",
            "email",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/calendar.readonly",
        ),
        client_id_env="GOOGLE_OAUTH_CLIENT_ID",
        client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
        secret_required=True,
        extra=(("access_type", "offline"), ("prompt", "consent"), ("include_granted_scopes", "false")),
    ),
    "microsoft": OAuthProvider(
        id="microsoft",
        label="Microsoft (Outlook mail and calendar)",
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        scopes=("offline_access", "openid", "email", "User.Read", "Mail.Read", "Mail.ReadWrite", "Calendars.Read"),
        client_id_env="MS_OAUTH_CLIENT_ID",
        client_secret_env="MS_OAUTH_CLIENT_SECRET",
        secret_required=False,
        extra=(("prompt", "select_account"),),
    ),
}

# Grants Heirloom must never ask for: sending as the owner, or writing their calendar.
FORBIDDEN_SCOPES = (
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "Mail.Send",
    "Calendars.ReadWrite",
)


def redirect_uri(provider: str, env: Optional[dict] = None) -> str:
    base = (env if env is not None else os.environ).get("HEIRLOOM_OAUTH_REDIRECT_BASE", "").strip().rstrip("/")
    if not base:
        base = "http://127.0.0.1:8001"
    return f"{base}/api/local-skills/oauth/{provider}/callback"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    return verifier, challenge


def authorize_url(provider: OAuthProvider, *, state: str, challenge: str, env: Optional[dict] = None) -> str:
    params = {
        "client_id": provider.client_id(env),
        "response_type": "code",
        "redirect_uri": redirect_uri(provider.id, env),
        "scope": " ".join(provider.scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    params.update(dict(provider.extra))
    return provider.authorize_url + "?" + urlencode(params)


def token_form(provider: OAuthProvider, *, code: str = "", verifier: str = "", refresh_token: str = "", env: Optional[dict] = None) -> dict:
    form = {"client_id": provider.client_id(env)}
    secret = provider.client_secret(env)
    if secret:
        form["client_secret"] = secret
    if refresh_token:
        form.update({"grant_type": "refresh_token", "refresh_token": refresh_token})
        if provider.id == "microsoft":
            form["scope"] = " ".join(provider.scopes)
    else:
        form.update({
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri(provider.id, env),
        })
    return form


def granted_scopes_ok(scope_text: str) -> bool:
    granted = set((scope_text or "").split())
    return not any(s in granted for s in FORBIDDEN_SCOPES)


def _now() -> float:
    return time.time()


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fernet():
    from connector_secrets import fernet_from_env

    return fernet_from_env()


def _db():
    from deps import db

    return db


def _post_form(url: str, form: dict) -> dict:
    import requests

    response = requests.post(url, data=form, timeout=20, headers={"Accept": "application/json"})
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        reason = (data or {}).get("error_description") or (data or {}).get("error") or f"HTTP {response.status_code}"
        raise RuntimeError(f"Token exchange failed: {str(reason)[:160]}")
    return data


async def start(user_id: str, provider_id: str, *, store: Any = None) -> str:
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError("unknown_provider")
    if not provider.configured():
        raise RuntimeError(f"{provider.label} is not set up on this box ({provider.client_id_env} is empty).")
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    db = store or _db()
    await db.oauth_pending.insert_one({
        "state": state,
        "user_id": user_id,
        "provider": provider_id,
        "verifier": verifier,
        "created": _now(),
    })
    return authorize_url(provider, state=state, challenge=challenge)


async def finish(provider_id: str, *, state: str, code: str, store: Any = None, post=None) -> dict:
    import asyncio

    from connector_secrets import seal_secret

    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError("unknown_provider")
    db = store or _db()
    pending = await db.oauth_pending.find_one_and_delete({"state": state, "provider": provider_id})
    if not pending or _now() - float(pending.get("created") or 0) > PENDING_TTL_SECONDS:
        raise ValueError("expired_or_unknown_state")
    form = token_form(provider, code=code, verifier=pending["verifier"])
    tokens = await asyncio.to_thread(post or _post_form, provider.token_url, form)
    scope_text = str(tokens.get("scope") or " ".join(provider.scopes))
    if not granted_scopes_ok(scope_text):
        raise RuntimeError("The account granted more than read and draft. Heirloom refused the token.")
    fernet = _fernet()
    doc = {
        "user_id": pending["user_id"],
        "provider": provider_id,
        "scopes": scope_text.split(),
        "sealed_refresh": seal_secret(str(tokens.get("refresh_token") or ""), fernet),
        "sealed_access": seal_secret(str(tokens.get("access_token") or ""), fernet),
        "expires_at": _now() + int(tokens.get("expires_in") or 3000) - 60,
        "connected_at": _iso(),
        "status": "connected",
    }
    await db.skill_accounts.update_one(
        {"user_id": doc["user_id"], "provider": provider_id}, {"$set": doc}, upsert=True
    )
    return {"provider": provider_id, "user_id": doc["user_id"], "scopes": doc["scopes"]}


async def access_token(user_id: str, provider_id: str, *, store: Any = None, post=None) -> str:
    """A live access token, refreshed when needed. Empty when not connected."""
    import asyncio

    from connector_secrets import open_secret, seal_secret

    db = store or _db()
    doc = await db.skill_accounts.find_one({"user_id": user_id, "provider": provider_id, "status": "connected"})
    if not doc:
        return ""
    fernet = _fernet()
    if float(doc.get("expires_at") or 0) > _now():
        return open_secret(doc["sealed_access"], fernet)
    refresh = open_secret(doc.get("sealed_refresh") or "", fernet)
    if not refresh:
        return ""
    provider = PROVIDERS[provider_id]
    tokens = await asyncio.to_thread(post or _post_form, provider.token_url, token_form(provider, refresh_token=refresh))
    update = {
        "sealed_access": seal_secret(str(tokens.get("access_token") or ""), fernet),
        "expires_at": _now() + int(tokens.get("expires_in") or 3000) - 60,
    }
    if tokens.get("refresh_token"):
        update["sealed_refresh"] = seal_secret(str(tokens["refresh_token"]), fernet)
    await db.skill_accounts.update_one({"user_id": user_id, "provider": provider_id}, {"$set": update})
    return open_secret(update["sealed_access"], fernet)


async def connected(user_id: str, *, store: Any = None) -> list[str]:
    db = store or _db()
    rows = await db.skill_accounts.find({"user_id": user_id, "status": "connected"}, {"_id": 0, "provider": 1}).to_list(10)
    return [r["provider"] for r in rows]


async def disconnect(user_id: str, provider_id: str, *, store: Any = None) -> bool:
    db = store or _db()
    result = await db.skill_accounts.delete_one({"user_id": user_id, "provider": provider_id})
    return bool(getattr(result, "deleted_count", 0))
