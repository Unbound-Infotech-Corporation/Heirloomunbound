"""Who may see Presence. Heirs and callers are a 404, the same fence as Observer."""
from __future__ import annotations

from fastapi import HTTPException

from owner_pairing import is_owner_audience


def presence_allowed(user: dict | None) -> bool:
    if not user:
        return False
    if user.get("heir_surface"):
        return False
    return is_owner_audience(user.get("audience") or "owner")


def require_owner(user: dict | None) -> None:
    if not presence_allowed(user):
        raise HTTPException(status_code=404, detail="Not found")
