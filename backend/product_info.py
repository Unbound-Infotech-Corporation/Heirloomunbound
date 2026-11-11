"""Product version and the commit this process was built from.

``PRODUCT_VERSION`` is the single version string. ``/api/build`` reads it
instead of a second hard-coded copy. The commit comes from the environment
the deploy injected, then from git, then from ``unknown``.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

PRODUCT_VERSION = "0.5.1"

_SHA_ENV = ("HEIRLOOM_GIT_SHA", "GIT_COMMIT", "SOURCE_VERSION", "GITHUB_SHA")
_HEX = frozenset("0123456789abcdef")


def product_version() -> str:
    override = (os.environ.get("HEIRLOOM_VERSION") or "").strip()
    return override or PRODUCT_VERSION


def _short_sha(raw: str) -> str | None:
    text = (raw or "").strip().lower()
    if not text or text in {"dev", "unknown", "none", "null"}:
        return None
    token = text.split()[0]
    if len(token) < 7 or any(char not in _HEX for char in token):
        return None
    return token[:12]


def git_sha() -> str:
    for key in _SHA_ENV:
        found = _short_sha(os.environ.get(key) or "")
        if found:
            return found
    root = Path(__file__).resolve().parents[1]
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    found = _short_sha(proc.stdout or "")
    if proc.returncode == 0 and found:
        return found
    return "unknown"
