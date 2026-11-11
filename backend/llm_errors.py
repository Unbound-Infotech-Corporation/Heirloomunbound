"""Friendly failures when a local model times out or cannot finish.

Callers turn the pair into an HTTP error. The exception text stays in the
log the caller already has; it is not repeated to the owner.
"""
from __future__ import annotations


def _is_timeout(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if "timeout" in type(current).__name__.lower():
            return True
        text = str(current).lower()
        if "timed out" in text or "timeout" in text:
            return True
        current = current.__cause__ or current.__context__
    return False


def llm_error(exc: BaseException, *, what: str) -> tuple[int, str]:
    """``(status, detail)``. Timeouts ask the owner to try again."""
    if _is_timeout(exc):
        return 503, f"{what} took too long. Try again in a moment."
    return 502, f"{what} didn't finish. Try again."
