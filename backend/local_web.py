"""Serve the built web app from the API process when there is no Caddy in front.

The Twin Box serves the React build from Caddy. A Windows "local box" install has
no Caddy, so the API serves ``HEIRLOOM_WEB_DIR`` itself: real files as they are,
any other non-API path gets ``index.html`` so the React router can take over.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def web_dir() -> Optional[Path]:
    raw = (os.environ.get("HEIRLOOM_WEB_DIR") or "").strip()
    if not raw:
        return None
    root = Path(raw)
    return root if (root / "index.html").is_file() else None


def resolve(root: Path, path: str) -> Path:
    """The file for ``path`` inside ``root``; ``index.html`` for app routes. Never outside root."""
    clean = (path or "").lstrip("/")
    if clean.startswith("api/") or clean == "api":
        raise FileNotFoundError(path)
    base = root.resolve()
    target = (base / clean).resolve() if clean else base / "index.html"
    try:
        target.relative_to(base)
    except ValueError:
        raise FileNotFoundError(path) from None
    if target.is_file():
        return target
    if "." in Path(clean).name:  # a missing asset, not an app route
        raise FileNotFoundError(path)
    return base / "index.html"


def attach_web(app) -> bool:
    root = web_dir()
    if root is None:
        return False

    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    @app.get("/{path:path}", include_in_schema=False)
    async def _web(path: str):
        try:
            target = resolve(root, path)
        except FileNotFoundError:
            raise HTTPException(status_code=404) from None
        headers = {"Cache-Control": "no-cache"} if target.name == "index.html" else {}
        return FileResponse(target, headers=headers)

    return True
