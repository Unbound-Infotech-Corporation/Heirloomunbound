"""Setup / Keys Wizard — one place for users to BYO API keys.

Most providers already have per-service save endpoints elsewhere
(ElevenLabs in voice_clone.py, D-ID in avatar.py, fal.ai in avatar_studio.py).
This router only exposes:
  • GET  /api/user-keys/status   — what's configured (admin / user / none)
  • POST /api/user-keys/verify   — live-test a pasted key against the provider

The wizard frontend calls /verify, then on success POSTs to the
service-specific save endpoint so each integration keeps its own contract.
"""
from __future__ import annotations

import base64
import os

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import db, get_current_user

router = APIRouter(prefix="/user-keys", tags=["user-keys"])

ADMIN_KEYS = {
    "elevenlabs": os.environ.get("ELEVENLABS_API_KEY", "").strip(),
    "did": os.environ.get("D_ID_API_KEY", "").strip(),
    "fal": os.environ.get("FAL_KEY", "").strip(),
    "resend": os.environ.get("RESEND_API_KEY", "").strip(),
    "stripe": os.environ.get("STRIPE_PAYMENT_LINK_URL", "").strip(),
}

USER_FIELDS = {
    "elevenlabs": "elevenlabs_api_key",
    "did": "d_id_api_key",
    "fal": "fal_api_key",
    # resend is the app's transactional sender — not per-user overrideable here
}

OAUTH_SERVICES = ("spotify", "github")


@router.get("/status")
async def get_status(user: dict = Depends(get_current_user)):
    """Return per-service configuration state for the wizard UI."""
    out: dict[str, dict] = {}
    for svc, field in USER_FIELDS.items():
        has_user = bool((user.get(field) or "").strip())
        has_admin = bool(ADMIN_KEYS.get(svc))
        out[svc] = {
            "configured": has_user or has_admin,
            "source": "you" if has_user else ("admin" if has_admin else "none"),
        }
    # Resend (admin-only, app-wide transactional)
    out["resend"] = {
        "configured": bool(ADMIN_KEYS["resend"]),
        "source": "admin" if ADMIN_KEYS["resend"] else "none",
    }
    # Stripe (admin-only — payment link is product-level)
    out["stripe"] = {
        "configured": bool(ADMIN_KEYS["stripe"]),
        "source": "admin" if ADMIN_KEYS["stripe"] else "none",
    }
    # OAuth links — check user doc for stored tokens
    for svc in OAUTH_SERVICES:
        token_field = f"{svc}_oauth"
        has_oauth = bool((user.get(token_field) or {}).get("access_token"))
        out[svc] = {
            "configured": has_oauth,
            "source": "you" if has_oauth else "none",
            "oauth": True,
        }
    return out


# ---------------- Live verification ----------------
class VerifyReq(BaseModel):
    service: str
    api_key: str


@router.post("/verify")
async def verify_key(body: VerifyReq, _user: dict = Depends(get_current_user)):
    """Hit the provider's cheapest authenticated endpoint to confirm the key
    is real. Returns {ok, detail, account?} — never persists."""
    svc = (body.service or "").lower().strip()
    key = (body.api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Empty key")

    try:
        if svc == "elevenlabs":
            r = requests.get(
                "https://api.elevenlabs.io/v1/user",
                headers={"xi-api-key": key},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json() or {}
                tier = ((data.get("subscription") or {}).get("tier")) or "free"
                return {"ok": True, "detail": f"Valid — plan: {tier}"}
            return {"ok": False, "detail": f"ElevenLabs rejected the key ({r.status_code})"}

        if svc == "did":
            b64 = base64.b64encode(key.encode()).decode()
            r = requests.get(
                "https://api.d-id.com/credits",
                headers={"Authorization": f"Basic {b64}"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json() or {}
                remaining = data.get("remaining", data.get("credits", "?"))
                return {"ok": True, "detail": f"Valid — credits remaining: {remaining}"}
            return {"ok": False, "detail": f"D-ID rejected the key ({r.status_code})"}

        if svc == "fal":
            # fal keys are `key_id:key_secret`. Hit the platform usage endpoint:
            #   200 → valid with admin scope (we get balance back)
            #   403 → valid but standard scope (still works for inference, which is what we use)
            #   401 → invalid key
            r = requests.get(
                "https://api.fal.ai/v1/serverless/usage",
                headers={"Authorization": f"Key {key}"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json() or {}
                bal = data.get("credits_remaining")
                if bal is not None:
                    return {"ok": True, "detail": f"Valid — credits remaining: {bal}"}
                return {"ok": True, "detail": "Valid fal.ai admin key."}
            if r.status_code == 403:
                return {"ok": True, "detail": "Valid fal.ai key (standard scope — Beautify will work)."}
            if r.status_code == 401:
                return {"ok": False, "detail": "fal.ai rejected the key — double-check the key_id:key_secret format."}
            return {"ok": False, "detail": f"fal.ai verification failed ({r.status_code})"}

        if svc == "resend":
            r = requests.get(
                "https://api.resend.com/domains",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
            if r.status_code == 200:
                domains = (r.json() or {}).get("data") or []
                return {"ok": True, "detail": f"Valid — {len(domains)} domain(s) on this account"}
            return {"ok": False, "detail": f"Resend rejected the key ({r.status_code})"}

        raise HTTPException(status_code=400, detail=f"Unknown service '{svc}'")
    except requests.RequestException as exc:
        return {"ok": False, "detail": f"Network error contacting {svc}: {exc!s}"}
