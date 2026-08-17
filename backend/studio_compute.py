"""Resolve where studio workloads run: this PC, a networked PC, or remote Ollama."""
from __future__ import annotations

import os
from typing import Any, Optional

from local_inference import ollama_ready_at
from studio_defaults import clamp_compute


def user_compute(user: dict) -> dict:
    return clamp_compute(user.get("studio_compute"))


def resolve_ollama_url(user: dict) -> Optional[str]:
    """Ollama base URL for server-side twin turns (not the companion daemon)."""
    compute = user_compute(user)
    if compute["mode"] == "server":
        url = (compute.get("remote") or {}).get("ollama_url") or ""
        cleaned = url.strip().rstrip("/")
        return cleaned or None
    env = (os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_URL") or "").strip()
    if env:
        return env.rstrip("/")
    return None


def effective_runtime_probe(user: dict, companion_probe: Optional[dict]) -> dict:
    """Merge companion GPU/Whisper/Piper with remote Ollama when mode=server."""
    base: dict[str, Any] = dict(companion_probe or {})
    compute = user_compute(user)
    if compute["mode"] == "server":
        url = resolve_ollama_url(user)
        if url:
            ready = ollama_ready_at(url)
            label = (compute.get("remote") or {}).get("label") or "Remote Ollama"
            base["ollama"] = {
                "ready": ready,
                "detail": f"{label} ({url})" if ready else f"Cannot reach {url}",
                "url": url,
            }
    return base


async def resolve_compute_device(db, user: dict) -> Optional[dict]:
    """Pick the companion device that runs Whisper/Piper/provision jobs."""
    compute = user_compute(user)
    uid = user["user_id"]
    base_filter = {"user_id": uid, "revoked": {"$ne": True}}
    if compute["mode"] == "network" and compute.get("device_id"):
        return await db.companion_devices.find_one(
            {**base_filter, "device_id": compute["device_id"]},
            {"_id": 0},
        )
    return await db.companion_devices.find_one(
        base_filter,
        {"_id": 0},
        sort=[("last_seen", -1)],
    )


def compute_target_device_id(user: dict) -> Optional[str]:
    """Device id stored for network mode (used when queueing PC-bound commands)."""
    compute = user_compute(user)
    if compute["mode"] == "network":
        return compute.get("device_id")
    return None


def command_targets_device(cmd: dict, device_id: str) -> bool:
    """True if this queued command should run on device_id."""
    payload = cmd.get("payload") or {}
    target = payload.get("target_device_id")
    if not target:
        return True
    return str(target) == str(device_id)
