"""Public health payload for the Twin Box and ``GET /api/health``.

No secrets. The product version string matches the existing 0.5.1 titlebar.
"""
from __future__ import annotations

import os

from ai_disclosure import disclosure_enabled
from lab_mode import box_mode_enabled, lab_mode_enabled
from llm_provider import resolve_llm_provider

PRODUCT_VERSION = "0.5.1"


from observer_store import status_public
from presence_store import status_public as presence_status_public


def _compute() -> dict[str, str]:
    """GPU name and twin model when the installer wrote them. Empty when unset."""
    gpu = (os.environ.get("HEIRLOOM_GPU_NAME") or "").strip()
    model = (os.environ.get("OLLAMA_TWIN_MODEL") or "").strip()
    found: dict[str, str] = {}
    if gpu:
        found["gpu"] = gpu
    if model:
        found["model"] = model
    return found


def health_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ok",
        "app": "digital-heirloom",
        "version": PRODUCT_VERSION,
        "llm_provider": resolve_llm_provider(),
        "lab_mode": lab_mode_enabled(),
        "box": box_mode_enabled(),
        "ai_disclosure": disclosure_enabled(),
        "observer": status_public(),
        "presence": presence_status_public(),
    }
    compute = _compute()
    if compute:
        payload["compute"] = compute
    try:
        from brain_route import brain_status

        payload["brain"] = brain_status()
    except Exception:
        payload["brain"] = {"answered": "local", "remote_configured": False}
    return payload
