"""Object storage helper.

The default backend writes under the Heirloom data root (``HEIRLOOM_DATA_ROOT``
/ ``objects``). The Emergent object store is optional and used only when
``HEIRLOOM_STORAGE`` is ``emergent`` (or ``cloud`` / ``objstore``) on a web
deployment. A Twin Box always stays on the local filesystem.

Public interface: ``init_storage``, ``put_object``, ``get_object``,
``STORAGE_URL``, ``APP_PREFIX``.
"""
import logging
import os
import threading
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
APP_PREFIX = os.environ.get("APP_STORAGE_PREFIX", "heirloom")
_EMERGENT_NAMES = frozenset({"emergent", "cloud", "objstore"})

_lock = threading.Lock()
_storage_key: str | None = None
_logged_box_override = False


def _box_mode() -> bool:
    return (os.environ.get("HEIRLOOM_BOX") or "").strip().lower() in {"1", "true", "yes", "on"}


def storage_backend() -> str:
    """``local`` unless the web deployment explicitly selects Emergent."""
    raw = (os.environ.get("HEIRLOOM_STORAGE") or "").strip().lower()
    explicit = raw in _EMERGENT_NAMES
    if _box_mode():
        global _logged_box_override
        if explicit and not _logged_box_override:
            logger.error("HEIRLOOM_BOX refused Emergent object storage; using the local filesystem")
            _logged_box_override = True
        return "local"
    return "emergent" if explicit else "local"


def _local_root() -> Path:
    from box_pause import data_root

    root = data_root() / "objects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _object_file(path: str) -> tuple[Path, str]:
    rel = (path or "").replace("\\", "/").strip().lstrip("/")
    parts = [part for part in rel.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("invalid object path")
    root = _local_root().resolve()
    dest = root.joinpath(*parts).resolve()
    if dest != root and root not in dest.parents:
        raise ValueError("invalid object path")
    return dest, "/".join(parts)


def _put_local(path: str, data: bytes, content_type: str) -> dict:
    dest, logical = _object_file(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    dest.with_name(dest.name + ".content-type").write_text(content_type or "application/octet-stream", encoding="utf-8")
    return {"path": logical, "size": len(data), "content_type": content_type}


def _get_local(path: str) -> tuple[bytes, str]:
    dest, _logical = _object_file(path)
    if not dest.is_file():
        raise RuntimeError("object not found")
    ctype_path = dest.with_name(dest.name + ".content-type")
    try:
        ctype = ctype_path.read_text(encoding="utf-8").strip() or "application/octet-stream"
    except OSError:
        ctype = "application/octet-stream"
    return dest.read_bytes(), ctype


def init_storage() -> str | None:
    """Init the storage session. Returns a key, ``local``, or None if Emergent is not configured."""
    global _storage_key
    if storage_backend() == "local":
        _local_root()
        return "local"
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
    if storage_backend() == "local":
        return _put_local(path, data, content_type)
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
    if storage_backend() == "local":
        return _get_local(path)
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
