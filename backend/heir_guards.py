"""Heir-facing guards — portal session ids and release-token hygiene.

Heirs must never write into an owner Sit / Twin / Assist conversation.
Release state must only change through release-now / revoke-release so the
portal token rotates or dies with the flag.
"""
from __future__ import annotations

from typing import Any, Optional

_RELEASE_FIELDS = frozenset({"released", "released_at", "release_token"})


def portal_conversation_id(heir_id: str, requested: Optional[str] = None) -> str:
    """One conversation per heir. Ignore client ids that are not this heir's."""
    hid = str(heir_id or "").strip()
    if not hid:
        raise ValueError("heir_id is required")
    expected = f"heir_{hid}"
    raw = str(requested or "").strip()
    if raw == expected:
        return expected
    return expected


def can_reuse_conversation(
    *,
    requested_kind: str,
    existing_kind: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    """Refuse owner / Assist / portal threads when the caller asked for another rail."""
    cid = str(conversation_id or "").strip()
    want = (requested_kind or "").strip()
    if cid.startswith("heir_") and want != "heir_portal":
        return False
    existing = (existing_kind or "").strip()
    if existing and want and existing != want:
        return False
    return True


def sanitize_heir_patch(raw: dict | None) -> dict[str, Any]:
    """Drop release fields so PATCH cannot revive an old portal token."""
    return {
        k: v
        for k, v in (raw or {}).items()
        if k not in _RELEASE_FIELDS and v is not None
    }


def heir_archive_query(owner_id: str) -> dict:
    """Archive rows an heir may see. Owner-only and private entries stay out."""
    from memory_guard import mongo_query

    return mongo_query(owner_id, "heir")


def portal_turn_update(
    *,
    owner_id: str,
    heir_id: str,
    session_id: str,
    user_text: str,
    reply_text: str,
    now_iso: str,
) -> dict[str, Any]:
    """Upsert operators for one heir turn.

    A field may appear in ``$set`` or ``$setOnInsert``, never both. Mongo
    rejects that overlap (WriteError 40) and the heir never sees the reply.
    """
    return {
        "$setOnInsert": {
            "conversation_id": session_id,
            "user_id": owner_id,
            "created_at": now_iso,
        },
        "$set": {
            "updated_at": now_iso,
            "kind": "heir_portal",
            "heir_id": heir_id,
        },
        "$push": {
            "messages": {
                "$each": [
                    {"role": "user", "content": user_text, "ts": now_iso},
                    {"role": "assistant", "content": reply_text, "ts": now_iso},
                ]
            }
        },
    }
