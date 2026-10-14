"""CORS origins for the Twin Box. Cloud deploys keep the existing allowlist."""
from __future__ import annotations

import os

_CLOUD = (
    r"https://[a-zA-Z0-9-]+\.emergentagent\.com"
    r"|http://localhost(:\d+)?"
    r"|http://127\.0\.0\.1(:\d+)?"
)

# Private LAN HTTPS only. Not a wildcard, and not http on the LAN.
_LAN = (
    r"|https://(?:localhost|127\.0\.0\.1"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(?::\d+)?"
)


def box_mode() -> bool:
    return (os.environ.get("HEIRLOOM_BOX") or "").strip().lower() in {"1", "true", "yes", "on"}


def origin_regex(*, box: bool | None = None) -> str:
    """Exact pattern passed to CORSMiddleware. Cloud shape stays unchanged."""
    enabled = box_mode() if box is None else box
    body = _CLOUD + (_LAN if enabled else "")
    return f"^({body})$"
