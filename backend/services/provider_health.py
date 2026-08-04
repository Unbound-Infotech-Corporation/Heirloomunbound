"""Provider health checks — probes each enabled BYOK provider once per hour
so we can surface a red/green dot in the AI Router UI and catch rotting keys.

Strategy
--------
For every user that has a `routing_configs` doc, we walk each enabled provider
and fire a cheap GET (`/v1/models` on OpenAI-compat endpoints; `list` on the
Emergent path). We DON'T run a chat completion — that would cost real money.
The response only needs to be a 2xx to count as green; timeouts / 4xx / 5xx
mark the provider red with the truncated error stored for the UI.

Records live in a dedicated collection `provider_health` keyed on
(user_id, provider) — a single upsert per check, no growing history.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from deps import db, EMERGENT_LLM_KEY
from services.llm_router import PROVIDERS, get_config

log = logging.getLogger("provider_health")

# One provider probe cannot take longer than this.
_PROBE_TIMEOUT = 8.0
# Between full refresh sweeps.
CHECK_INTERVAL_S = 3600  # 1 hour


async def probe_provider(user_id: str, provider: str, cfg: dict | None = None) -> dict:
    """Ping a single provider for one user and upsert `provider_health`.

    Returns the fresh health doc (redacted — no api_key in it).
    """
    cfg = cfg or await get_config(user_id)
    pcfg = cfg["providers"].get(provider) or {}
    spec = PROVIDERS.get(provider)
    if not spec:
        return await _write_health(user_id, provider, "unknown", "unknown provider", None)

    if not pcfg.get("enabled"):
        return await _write_health(user_id, provider, "unknown", "disabled", None)

    if provider == "emergent":
        # Emergent key comes from env — we just check the SDK imports cleanly.
        return await _probe_emergent(user_id)

    api_key = (pcfg.get("api_key") or "").strip()
    if not api_key:
        return await _write_health(user_id, provider, "red", "no api key configured", None)

    # Anthropic's native REST API expects x-api-key + anthropic-version, not
    # Bearer, so we probe /v1/models with those headers. Every other listed
    # provider is OpenAI-compatible on /v1/models with Bearer.
    if provider == "anthropic":
        url = "https://api.anthropic.com/v1/models"
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    elif provider == "gemini":
        # Gemini's OpenAI-compat proxy accepts either ?key= or Bearer.
        url = spec["base_url"].rstrip("/") + f"/models?key={api_key}"
        headers = {"Authorization": f"Bearer {api_key}"}
    else:
        url = spec["base_url"].rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if 200 <= resp.status_code < 300:
            return await _write_health(user_id, provider, "green", None, latency_ms)
        # 401/403 = auth failure (rotting key) — the whole reason we do this.
        # 404 on /models happens on a couple of providers even for good keys —
        # treat any 4xx as red and let the owner investigate.
        snippet = (resp.text or "")[:180]
        return await _write_health(user_id, provider, "red", f"HTTP {resp.status_code}: {snippet}", latency_ms)
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.perf_counter() - started) * 1000)
        return await _write_health(user_id, provider, "red", str(exc)[:180], latency_ms)


async def _probe_emergent(user_id: str) -> dict:
    """Ensure the Universal Key is set and the SDK loads."""
    if not EMERGENT_LLM_KEY:
        return await _write_health(user_id, "emergent", "red", "EMERGENT_LLM_KEY not set", None)
    try:
        from emergentintegrations.llm.chat import LlmChat  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return await _write_health(user_id, "emergent", "red", f"sdk import failed: {exc}", None)
    return await _write_health(user_id, "emergent", "green", None, None)


async def _write_health(
    user_id: str, provider: str, status: str, error: str | None, latency_ms: int | None
) -> dict:
    """Upsert the current health row AND fire a rotation-alert email on the
    first green→red flip. Alerts auto-reset once the provider goes back to
    green, so the next flip triggers again.
    """
    now = datetime.now(timezone.utc).isoformat()
    prior = await db.provider_health.find_one(
        {"user_id": user_id, "provider": provider},
        {"_id": 0, "status": 1, "rotation_alert_sent": 1},
    ) or {}
    prior_status = prior.get("status")

    update: dict = {
        "user_id": user_id,
        "provider": provider,
        "status": status,
        "error": error,
        "latency_ms": latency_ms,
        "last_checked": now,
    }
    if status == "green":
        update["last_ok"] = now
        # Reset the alert flag so a fresh red → green → red cycle re-fires.
        update["rotation_alert_sent"] = False
    await db.provider_health.update_one(
        {"user_id": user_id, "provider": provider},
        {"$set": update, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )

    # Green → red transition: fire once. `prior_status == "green"` is the guard;
    # a first-ever probe that lands red does NOT fire (we want the user to
    # notice the change from working to broken, not to nag on setup).
    if (
        status == "red"
        and prior_status == "green"
        and not prior.get("rotation_alert_sent")
    ):
        try:
            sent = await _send_rotation_alert(user_id, provider, error)
            if sent:
                await db.provider_health.update_one(
                    {"user_id": user_id, "provider": provider},
                    {"$set": {"rotation_alert_sent": True}},
                )
        except Exception:  # noqa: BLE001 — never let alerting break the probe
            log.warning("rotation alert failed for %s/%s", user_id, provider, exc_info=True)

    return update


async def _send_rotation_alert(user_id: str, provider: str, error: str | None) -> bool:
    """Look up the owner's email and send a Resend rotation alert.

    Returns True on success (or explicit skip); False if delivery failed so the
    caller can retry on the next probe.
    """
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1, "name": 1})
    if not user or not (user.get("email") or "").strip():
        return True  # no email on file — treat as delivered so we don't retry forever
    from email_service import send_provider_rotation_email
    result = await send_provider_rotation_email(
        to=user["email"], owner_name=user.get("name", "Friend"),
        provider=provider, error=(error or "unknown error"),
    )
    return bool(result and (result.get("ok") or result.get("skipped")))


async def refresh_user(user_id: str, cfg: dict | None = None) -> list[dict]:
    """Refresh every enabled provider for one user. Runs probes in parallel."""
    cfg = cfg or await get_config(user_id)
    enabled = [pid for pid, pcfg in cfg["providers"].items() if pcfg.get("enabled")]
    if not enabled:
        return []
    results = await asyncio.gather(
        *(probe_provider(user_id, pid, cfg) for pid in enabled),
        return_exceptions=True,
    )
    # Filter any raised exceptions to keep the return shape clean.
    return [r for r in results if isinstance(r, dict)]


async def refresh_all_users() -> int:
    """Loop across every user with a routing_configs doc and probe theirs."""
    n = 0
    async for doc in db.routing_configs.find({}, {"_id": 0, "user_id": 1}):
        uid = doc.get("user_id")
        if not uid:
            continue
        try:
            await refresh_user(uid)
            n += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("provider health refresh failed for %s: %s", uid, exc)
    return n


async def get_health_for_user(user_id: str) -> list[dict]:
    cursor = db.provider_health.find({"user_id": user_id}, {"_id": 0, "user_id": 0})
    return await cursor.to_list(length=100)


async def health_loop() -> None:
    """Long-running background task registered from `server.py` startup."""
    # Small initial delay so we don't stampede on fresh boot.
    await asyncio.sleep(30)
    while True:
        try:
            count = await refresh_all_users()
            log.info("provider health sweep: %d users refreshed", count)
        except Exception as exc:  # noqa: BLE001
            log.warning("provider health sweep error: %s", exc)
        await asyncio.sleep(CHECK_INTERVAL_S)
