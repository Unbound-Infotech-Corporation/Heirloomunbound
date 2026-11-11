"""Whether Ollama is actually answering, including on this machine.

The Models Studio test used to look only at the companion PC. A box or
desktop whose own Ollama is serving twin turns then said "Start Ollama".
"""
from __future__ import annotations

from typing import Callable, Optional


def _block(source: object) -> dict | None:
    if not isinstance(source, dict):
        return None
    row = source.get("ollama")
    return row if isinstance(row, dict) else None


def describe_ollama(
    probe: Optional[dict],
    companion: Optional[dict],
    *,
    live_ready: Optional[Callable[[], bool]] = None,
    live_url: str = "",
) -> dict:
    """Prefer a ready probe. Otherwise ask the Ollama this process uses."""
    for source in (probe, companion):
        row = _block(source)
        if row and row.get("ready"):
            detail = str(row.get("detail") or "").strip()
            if not detail or "start ollama" in detail.lower():
                detail = "Ollama is answering"
            return {"ready": True, "detail": detail, "url": row.get("url") or live_url}
    if live_ready is not None:
        try:
            answering = bool(live_ready())
        except Exception:  # noqa: BLE001
            answering = False
        if answering:
            where = live_url or "this machine"
            return {
                "ready": True,
                "detail": f"Ollama is answering ({where})",
                "url": live_url,
            }
    return {
        "ready": False,
        "detail": "Start Ollama on the dedicated PC",
        "url": live_url,
    }
