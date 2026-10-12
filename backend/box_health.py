"""Public health payload for the Twin Box and ``GET /api/health``.

No secrets. The product version string matches the existing 0.5.1 titlebar.
"""
from __future__ import annotations

from ai_disclosure import disclosure_enabled
from lab_mode import box_mode_enabled, lab_mode_enabled
from llm_provider import resolve_llm_provider

PRODUCT_VERSION = "0.5.1"


from observer_store import status_public
from presence_store import status_public as presence_status_public


def health_payload() -> dict[str, object]:
    return {
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
