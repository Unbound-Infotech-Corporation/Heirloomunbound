"""Object storage helper — Emergent object storage backend.

Initialised once on app startup; storage_key is cached at module level.
"""
import logging
import os
import threading

import requests

logger = logging.getLogger(__name__)

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
APP_PREFIX = os.environ.get("APP_STORAGE_PREFIX", "heirloom")

_lock = threading.Lock()
_storage_key: str | None = None


def init_storage() -> str | None:
    """Init the storage session. Returns storage_key or None if not configured."""
    global _storage_key
    if _storage_key:
        return _storage_key
    emergent_key = os.environ.get("EMERGENT_LLM_KEY")
    if not emergent_key:
        logger.warning("EMERGENT_LLM_KEY missing — object storage disabled")
        return None
    with _lock:
        if _storage_key:
            return _storage_key
        try:
            r = requests.post(
                f"{STORAGE_URL}/init",
                json={"emergent_key": emergent_key},
                timeout=30,
            )
            r.raise_for_status()
            _storage_key = r.json()["storage_key"]
            logger.info("Object storage initialised")
            return _storage_key
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Object storage init failed: {exc}")
            return None


def _refresh_on_403(resp):
    global _storage_key
    if resp.status_code == 403:
        _storage_key = None
        init_storage()


def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    if not key:
        raise RuntimeError("Object storage unavailable")
    r = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data,
        timeout=120,
    )
    _refresh_on_403(r)
    r.raise_for_status()
    return r.json()


def get_object(path: str) -> tuple[bytes, str]:
    key = init_storage()
    if not key:
        raise RuntimeError("Object storage unavailable")
    r = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key},
        timeout=60,
    )
    _refresh_on_403(r)
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "application/octet-stream")
