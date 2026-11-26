"""Which approved memory cards an heir's Twin may tell. Owner decisions only.

Pure store functions (no web framework) so the rules can be tested without a server. The routes in
``routers/memory_loop.py`` are thin wrappers.

* ``owner`` / ``private``: only the owner's Twin (the default for every approved card).
* ``family`` / ``heir``: heirs, once released. ``heir_ids`` empty means every heir; a list limits it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

VISIBILITIES = ("owner", "private", "family", "heir")


async def clean_heir_ids(store: Any, user_id: str, visibility: str, heir_ids: list[str]) -> list[str]:
    if visibility not in VISIBILITIES:
        raise ValueError("Unknown visibility")
    if visibility in ("owner", "private"):
        return []  # unsharing clears any heir list
    ids = list(dict.fromkeys(str(x).strip()[:60] for x in heir_ids or [] if str(x).strip()))
    if ids:
        known = await store.heirs.count_documents({"user_id": user_id, "heir_id": {"$in": ids}})
        if known != len(ids):
            raise ValueError("Unknown heir")
    return ids


async def share_cards(store: Any, user_id: str, card_ids: list[str], visibility: str, heir_ids: list[str]) -> dict:
    """Share or unshare approved cards. Pending cards and other owners' cards are left alone."""
    ids = await clean_heir_ids(store, user_id, visibility, heir_ids)
    update = {"visibility": visibility, "heir_ids": ids, "updated_at": datetime.now(timezone.utc).isoformat()}
    changed: list[str] = []
    for card_id in dict.fromkeys(card_ids or []):
        found = await store.memory_cards.find_one({"card_id": card_id, "user_id": user_id, "status": "approved"}, {"_id": 0})
        if not found:
            continue
        await store.memory_cards.update_one({"card_id": card_id, "user_id": user_id}, {"$set": update})
        changed.append(card_id)
    return {"shared": changed, "visibility": visibility, "heir_ids": ids}


async def get_default(store: Any, user_id: str) -> bool:
    row = await store.users.find_one({"user_id": user_id}, {"_id": 0, "share_new_cards_with_heirs": 1})
    return bool((row or {}).get("share_new_cards_with_heirs"))


async def set_default(store: Any, user_id: str, on: bool) -> bool:
    await store.users.update_one({"user_id": user_id}, {"$set": {"share_new_cards_with_heirs": bool(on)}})
    return bool(on)
