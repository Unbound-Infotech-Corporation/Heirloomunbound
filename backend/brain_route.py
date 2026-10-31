"""Primary Ollama on the LAN, then the Twin Box.

HEIRLOOM_BRAIN_URL (for example http://192.168.0.50:11434, model
llama3.3:70b) is tried first. The connect timeout is short and the health
result is cached. If that host is down, chat uses the box Ollama
(qwen2.5:14b, vision qwen2.5vl:7b).

When the local /api/ps (or `ollama ps`) shows a loaded model with
size_vram < size, or a processor share that is not 100% GPU, the Caretaker
restart runs and the remote brain is preferred.

Addresses must be LAN IPs. The optional token is sent as
`Authorization: Bearer` and is never written into the URL or the health
payload.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

REMOTE_MODEL = "llama3.3:70b"
LOCAL_CHAT_MODEL = "qwen2.5:14b"
LOCAL_VISION_MODEL = "qwen2.5vl:7b"
CONNECT_TIMEOUT = 0.8
PROBE_TIMEOUT = 1.5
CACHE_SECONDS = 15.0
RESTART_COOLDOWN = 90.0
FORBIDDEN_HOSTS = frozenset({"192.168.0.16", "192.168.0.19"})

ProbeRemote = Callable[[str, Mapping[str, str], float], Awaitable[bool]]
ProbePs = Callable[[str, float], Awaitable[Any]]
Restarter = Callable[[], str]

_remote_cache: dict[str, tuple[float, bool]] = {}
_gpu_cache: dict[str, tuple[float, str]] = {}
_restart_at = 0.0
_last_answer: dict[str, str] = {
    "name": "",
    "model": "",
    "host": "",
    "local_gpu": "unknown",
}
_settings_loader: Optional[Callable[[], Awaitable[Optional[dict]]]] = None


@dataclass(frozen=True)
class BrainSettings:
    remote_url: str = ""
    remote_model: str = REMOTE_MODEL
    token: str = ""
    local_url: str = "http://127.0.0.1:11434"
    local_model: str = LOCAL_CHAT_MODEL
    vision_model: str = LOCAL_VISION_MODEL


@dataclass(frozen=True)
class BrainTarget:
    name: str
    url: str
    model: str
    headers: dict[str, str] = field(default_factory=dict)
    local_gpu: str = "unknown"
    restarted: bool = False


def clear_caches() -> None:
    global _restart_at
    _remote_cache.clear()
    _gpu_cache.clear()
    _restart_at = 0.0
    _last_answer.update(name="", model="", host="", local_gpu="unknown")
    try:
        from brain_council import clear_answer_meta

        clear_answer_meta()
    except Exception:
        pass


def set_settings_loader(loader: Optional[Callable[[], Awaitable[Optional[dict]]]]) -> None:
    global _settings_loader
    _settings_loader = loader


def _private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


def normalize_lan_url(raw: str) -> str:
    """Return scheme://ip:port or raise ValueError. Hostnames are refused."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Brain URL is empty")
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("Brain URL must be http or https")
    if parts.username or parts.password:
        raise ValueError("Put the token in the header, not the URL")
    host = parts.hostname
    if not host:
        raise ValueError("Brain URL needs a host")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("Brain URL must be a LAN IP address") from exc
    if not _private_ip(ip):
        raise ValueError("Brain URL must stay on the LAN")
    rendered = str(ip)
    if rendered in FORBIDDEN_HOSTS:
        raise ValueError("That address is off limits")
    port = parts.port or 11434
    if port < 1 or port > 65535:
        raise ValueError("Brain URL port is invalid")
    shown = f"[{rendered}]" if ip.version == 6 else rendered
    return f"{parts.scheme}://{shown}:{port}"


def safe_remote_url(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return normalize_lan_url(text)
    except ValueError:
        logger.error("HEIRLOOM_BRAIN_URL is not a LAN address; ignoring it")
        return ""


def auth_headers(token: str) -> dict[str, str]:
    secret = (token or "").strip()
    if not secret:
        return {}
    return {"Authorization": f"Bearer {secret}"}


def _local_url() -> str:
    raw = (os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_URL") or "http://127.0.0.1:11434").strip()
    return raw.rstrip("/") or "http://127.0.0.1:11434"


def _local_model() -> str:
    from llm_provider import BOX_CHAT_MODEL, box_mode, ollama_model

    raw = (os.environ.get("OLLAMA_TWIN_MODEL") or "").strip()
    if raw:
        return ollama_model(raw)
    if box_mode():
        return BOX_CHAT_MODEL
    return ollama_model(None)


def settings_from_env() -> BrainSettings:
    from llm_provider import ollama_vision_model

    remote = safe_remote_url(os.environ.get("HEIRLOOM_BRAIN_URL") or "")
    model = (os.environ.get("HEIRLOOM_BRAIN_MODEL") or "").strip() or REMOTE_MODEL
    from llm_provider import is_cloud_choice

    if is_cloud_choice(model, ""):
        logger.error("HEIRLOOM_BRAIN_MODEL %s is a cloud model; using %s", model, REMOTE_MODEL)
        model = REMOTE_MODEL
    token = (os.environ.get("HEIRLOOM_BRAIN_TOKEN") or "").strip()
    return BrainSettings(
        remote_url=remote,
        remote_model=model,
        token=token,
        local_url=_local_url(),
        local_model=_local_model(),
        vision_model=ollama_vision_model(),
    )


def merge_settings(base: BrainSettings, saved: Optional[dict]) -> BrainSettings:
    """A saved owner document replaces the URL. An empty URL turns remote off."""
    if not isinstance(saved, dict):
        return base
    if "url" in saved:
        remote = safe_remote_url(str(saved.get("url") or ""))
    else:
        remote = base.remote_url
    model = str(saved.get("model") or "").strip() or base.remote_model or REMOTE_MODEL
    from llm_provider import is_cloud_choice

    if is_cloud_choice(model, ""):
        model = base.remote_model or REMOTE_MODEL
    if "token" in saved or saved.get("clear_token"):
        token = str(saved.get("token") or "").strip()
    else:
        token = base.token
    return BrainSettings(
        remote_url=remote,
        remote_model=model,
        token=token,
        local_url=base.local_url,
        local_model=base.local_model,
        vision_model=base.vision_model,
    )


def prepare_owner_update(body: Mapping[str, Any], current: Optional[dict]) -> dict:
    """Validate an owner save. Raises ValueError with a sentence the UI can show."""
    raw_url = body.get("url", "")
    if raw_url is None:
        raw_url = ""
    url_text = str(raw_url).strip()
    if url_text:
        url = normalize_lan_url(url_text)
    else:
        url = ""
    model = str(body.get("model") or "").strip() or REMOTE_MODEL
    from llm_provider import is_cloud_choice

    if is_cloud_choice(model, ""):
        raise ValueError("That model is a cloud model. Use a local Ollama tag.")
    if len(model) > 80:
        raise ValueError("Model name is too long")
    prior = current if isinstance(current, dict) else {}
    if body.get("clear_token"):
        token = ""
    elif str(body.get("token") or "").strip():
        token = str(body.get("token") or "").strip()
        if len(token) > 512:
            raise ValueError("Token is too long")
    else:
        token = str(prior.get("token") or "")
    return {"_id": "box", "url": url, "model": model, "token": token}


def public_settings(settings: BrainSettings, *, answered: str = "", local_gpu: str = "unknown") -> dict[str, Any]:
    host = ""
    if settings.remote_url:
        host = urlsplit(settings.remote_url).hostname or ""
    return {
        "url": settings.remote_url,
        "model": settings.remote_model,
        "token_set": bool(settings.token),
        "remote_configured": bool(settings.remote_url),
        "host": host,
        "local_url": settings.local_url,
        "local_model": settings.local_model,
        "vision_model": settings.vision_model,
        "answered": answered,
        "local_gpu": local_gpu,
    }


def loaded_models_off_gpu(payload: Any) -> bool:
    """True when /api/ps reports a model that is not fully in VRAM."""
    if not isinstance(payload, Mapping):
        return False
    models = payload.get("models") or []
    if not isinstance(models, list):
        return False
    for model in models:
        if not isinstance(model, Mapping):
            continue
        try:
            size = int(model.get("size") or 0)
            vram = int(model.get("size_vram") or 0)
        except (TypeError, ValueError):
            continue
        if size > 0 and vram < size:
            return True
    return False


def ps_text_off_gpu(text: str) -> bool:
    """True when `ollama ps` is not 100% GPU. Blank text is unknown, not lost."""
    from caretaker import CPU_ONLY, gpu_lost

    blob = text or ""
    if not blob.strip():
        return False
    if gpu_lost(blob, ""):
        return True
    if CPU_ONLY in blob:
        return True
    for line in blob.splitlines():
        lowered = line.lower().strip()
        if not lowered or lowered.startswith("name") or "processor" in lowered and "size" in lowered:
            continue
        if "100% gpu" in lowered:
            continue
        if "cpu" in lowered and "%" in lowered:
            return True
    return False


def local_gpu_state(payload: Any) -> str:
    if isinstance(payload, str):
        if not payload.strip():
            return "unknown"
        return "partial" if ps_text_off_gpu(payload) else "full"
    if isinstance(payload, Mapping):
        models = payload.get("models") or []
        if not models:
            return "unknown"
        return "partial" if loaded_models_off_gpu(payload) else "full"
    return "unknown"


def remember_answer(*, name: str, model: str, url: str, local_gpu: str = "unknown") -> None:
    host = ""
    if url:
        host = urlsplit(url).hostname or ""
    _last_answer.update(
        name=(name or "").strip(),
        model=(model or "").strip(),
        host=host,
        local_gpu=local_gpu or "unknown",
    )


def last_answer() -> dict[str, str]:
    return dict(_last_answer)


def brain_label() -> str:
    row = last_answer()
    name = row.get("name") or ""
    model = row.get("model") or ""
    if name and model:
        return f"{name} · {model}"
    return name or model


def _skip_store() -> bool:
    if _settings_loader is not None:
        return False
    if (os.environ.get("HEIRLOOM_BRAIN_DISABLE_STORE") or "").strip() == "1":
        return True
    return "PYTEST_CURRENT_TEST" in os.environ


async def load_saved_settings() -> Optional[dict]:
    if _settings_loader is not None:
        return await _settings_loader()
    if _skip_store():
        return None
    try:
        import asyncio

        from deps import db

        doc = await asyncio.wait_for(db.brain_settings.find_one({"_id": "box"}), timeout=0.4)
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


async def current_settings() -> BrainSettings:
    return merge_settings(settings_from_env(), await load_saved_settings())


def _cache_get(cache: dict[str, tuple[float, Any]], key: str, now: float) -> Any:
    hit = cache.get(key)
    if not hit:
        return None
    stamped, value = hit
    if now - stamped > CACHE_SECONDS:
        return None
    return value


async def probe_remote(url: str, headers: Mapping[str, str], timeout: float) -> bool:
    import httpx

    connect = min(CONNECT_TIMEOUT, timeout)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=connect)) as client:
            response = await client.get(f"{url.rstrip('/')}/api/tags", headers=dict(headers))
        return response.status_code == 200
    except Exception:
        return False


async def probe_local_ps(url: str, timeout: float) -> Any:
    import httpx

    connect = min(CONNECT_TIMEOUT, timeout)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=connect)) as client:
            response = await client.get(f"{url.rstrip('/')}/api/ps")
        if response.status_code >= 400:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def restart_local() -> str:
    """Ask the Caretaker host ops to restart the ollama container. Debounced."""
    global _restart_at
    now = time.monotonic()
    if now - _restart_at < RESTART_COOLDOWN:
        return ""
    _restart_at = now
    try:
        from caretaker import HostOps

        root = (os.environ.get("HEIRLOOM_ROOT") or "").strip()
        compose = os.path.join(root, "box") if root else ""
        return HostOps(compose_dir=compose).restart("ollama")
    except Exception as exc:  # noqa: BLE001
        logger.warning("caretaker restart was not run: %s", type(exc).__name__)
        return ""


async def pick_target(
    settings: BrainSettings,
    *,
    probe_remote_fn: Optional[ProbeRemote] = None,
    probe_ps_fn: Optional[ProbePs] = None,
    restart_fn: Optional[Restarter] = None,
    now: Optional[float] = None,
) -> BrainTarget:
    """Choose remote or local. Probes are cached. Restart runs on a partial GPU."""
    clock = time.monotonic() if now is None else now
    remote_fn = probe_remote_fn or probe_remote
    ps_fn = probe_ps_fn or probe_local_ps
    restarter = restart_fn or restart_local
    headers = auth_headers(settings.token)

    gpu = "unknown"
    if settings.local_url:
        cached_gpu = _cache_get(_gpu_cache, settings.local_url, clock)
        if isinstance(cached_gpu, str):
            gpu = cached_gpu
        else:
            payload = await ps_fn(settings.local_url, PROBE_TIMEOUT)
            gpu = local_gpu_state(payload)
            _gpu_cache[settings.local_url] = (clock, gpu)

    restarted = False
    if gpu == "partial":
        restarter()
        restarted = True

    remote_ok = False
    if settings.remote_url:
        cached = _cache_get(_remote_cache, settings.remote_url, clock)
        if isinstance(cached, bool):
            remote_ok = cached
        else:
            remote_ok = await remote_fn(settings.remote_url, headers, PROBE_TIMEOUT)
            _remote_cache[settings.remote_url] = (clock, remote_ok)

    if settings.remote_url and remote_ok:
        target = BrainTarget(
            name="remote",
            url=settings.remote_url,
            model=settings.remote_model or REMOTE_MODEL,
            headers=headers,
            local_gpu=gpu,
            restarted=restarted,
        )
    else:
        target = BrainTarget(
            name="local",
            url=settings.local_url,
            model=settings.local_model or LOCAL_CHAT_MODEL,
            headers={},
            local_gpu=gpu,
            restarted=restarted,
        )
    remember_answer(name=target.name, model=target.model, url=target.url, local_gpu=gpu)
    return target


def _probe_enabled(settings: BrainSettings) -> bool:
    if settings.remote_url:
        return True
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    from llm_provider import box_mode

    return box_mode()


async def maybe_route() -> Optional[BrainTarget]:
    """Remote target when it should serve this chat. None keeps the caller's URL.

    A partial local GPU still restarts Ollama and prefers remote. When remote
    is down, None means the caller stays on the box model.
    """
    settings = await current_settings()
    if not _probe_enabled(settings):
        return None
    target = await pick_target(settings)
    if target.name != "remote":
        return None
    return target


def brain_status() -> dict[str, Any]:
    """Cached view for /api/health. Does not open a socket."""
    settings = settings_from_env()
    row = last_answer()
    answered = row.get("name") or ("remote" if settings.remote_url else "local")
    model = row.get("model") or (settings.remote_model if settings.remote_url else settings.local_model)
    view = public_settings(settings, answered=answered, local_gpu=row.get("local_gpu") or "unknown")
    view["model_in_use"] = model
    view["answered"] = answered
    if row.get("host"):
        view["answered_host"] = row["host"]
    try:
        from brain_council import health_overlay

        view.update(health_overlay())
    except Exception:
        view.setdefault("strategy", "single")
    return view
