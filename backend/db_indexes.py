"""Idempotent MongoDB index creation. Called once at app startup.

Indexes are the single biggest production-readiness win on this app:
- `user_sessions.session_token` is hit on every authenticated request.
- `users.user_id` is hit on every authenticated request (after session lookup).
- `entries.user_id` / `companion_devices.device_token` / `heirs.release_token` are hit
  on every archive query, every companion poll, and every public-heir-portal
  view respectively.

Mongo's `create_index` is idempotent — if an index with the same spec already
exists, this is a no-op. Safe to run on every cold start.
"""
from __future__ import annotations

import logging

from deps import db

logger = logging.getLogger(__name__)


async def ensure_indexes() -> None:
    """Create production indexes on hot-path collections. Idempotent."""
    plans: list[tuple[str, list, dict]] = [
        # Auth — hit on every request
        ("user_sessions", [("session_token", 1)], {"unique": True, "name": "session_token_uniq"}),
        ("user_sessions", [("user_id", 1)], {"name": "user_id"}),
        ("users", [("user_id", 1)], {"unique": True, "name": "user_id_uniq"}),
        ("users", [("email", 1)], {"name": "email"}),

        # Archive — hit on Library, Twin, Dashboard, Interviewer
        # Field is `type` (not entry_type).
        ("entries", [("user_id", 1), ("created_at", -1)], {"name": "user_created"}),
        # Real field is `type` — older builds wrongly indexed `entry_type` under this name.
        ("entries", [("user_id", 1), ("type", 1)], {"name": "user_type_v2"}),
        ("entries", [("user_id", 1), ("tags", 1)], {"name": "user_tags"}),

        # Conversations sort/filter by updated_at + kind (not started_at).
        ("conversations", [("user_id", 1), ("updated_at", -1)], {"name": "user_updated"}),
        ("conversations", [("user_id", 1), ("kind", 1), ("updated_at", -1)], {"name": "user_kind_updated"}),
        ("conversations", [("conversation_id", 1)], {"unique": True, "name": "conv_id_uniq"}),

        # Companion — hit on every poll cycle from local PC
        # Field is `device_token` (not token).
        ("companion_devices", [("device_token", 1)], {"unique": True, "sparse": True, "name": "device_token_uniq"}),
        ("companion_devices", [("user_id", 1), ("revoked", 1)], {"name": "user_revoked"}),
        ("companion_commands", [("user_id", 1), ("status", 1), ("created_at", 1)], {"name": "user_status_created"}),

        # Heirs + public portal — release_token lookup on every portal page hit
        ("heirs", [("user_id", 1)], {"name": "user_id"}),
        ("heirs", [("release_token", 1)], {"sparse": True, "name": "release_token"}),

        # Letters (collection is sealed_letters)
        ("sealed_letters", [("user_id", 1), ("created_at", -1)], {"name": "user_created"}),

        # Long-term memory (twin system prompt builds this every turn)
        ("memory_facts", [("user_id", 1)], {"name": "user_id"}),
        ("memory_episodes", [("user_id", 1), ("created_at", -1)], {"name": "user_created"}),
        ("memory_state", [("user_id", 1)], {"unique": True, "name": "user_id_uniq"}),
        ("personality_profiles", [("user_id", 1)], {"unique": True, "name": "user_id_uniq"}),

        # Skills + reminders
        ("skills", [("user_id", 1)], {"name": "user_id"}),
        ("reminders", [("user_id", 1), ("status", 1), ("due_at", 1)], {"name": "user_status_due"}),

        # Personas + nudges + dashboard
        ("personas", [("user_id", 1)], {"name": "user_id"}),
        ("nudges", [("user_id", 1), ("date", -1)], {"name": "user_date"}),

        # Photos
        ("photos", [("user_id", 1), ("created_at", -1)], {"name": "user_created"}),

        # Avatar talks (D-ID)
        ("avatar_talks", [("user_id", 1)], {"name": "user_id"}),
        ("avatar_talks", [("talk_id", 1)], {"unique": True, "name": "talk_id_uniq"}),

        # Imports + sources
        ("imports", [("user_id", 1), ("created_at", -1)], {"name": "user_created"}),
        ("sources", [("user_id", 1)], {"name": "user_id"}),

        # Billing / fulfillment
        ("checkout_sessions", [("session_id", 1)], {"unique": True, "name": "session_uniq"}),
        ("magic_links", [("token", 1)], {"unique": True, "sparse": True, "name": "token_uniq"}),

        # Stripe webhook event-level idempotency
        ("stripe_events", [("event_id", 1)], {"unique": True, "name": "event_id_uniq"}),

        # OAuth account-linking
        ("oauth_connections", [("user_id", 1), ("provider", 1)], {"unique": True, "name": "user_provider_uniq"}),
        ("oauth_states", [("state", 1)], {"unique": True, "name": "state_uniq"}),

        # Abilities
        ("user_abilities", [("user_id", 1), ("ability_id", 1)], {"unique": True, "name": "user_ability_uniq"}),
    ]

    created = 0
    skipped = 0

    # Drop known-wrong indexes left by earlier builds (wrong field names).
    for coll_name, bad_name in (
        ("entries", "user_type"),  # was {user_id, entry_type} — field doesn't exist
        ("companion_devices", "token_uniq"),  # was {token} — field is device_token
        ("conversations", "user_started"),  # was {user_id, started_at} — field is updated_at
    ):
        try:
            await db[coll_name].drop_index(bad_name)
            logger.info(f"Dropped stale index {coll_name}.{bad_name}")
        except Exception:
            pass

    for coll_name, keys, opts in plans:
        try:
            await db[coll_name].create_index(keys, **opts)
            created += 1
        except Exception as exc:  # noqa: BLE001
            # Most common cause: an existing index with the same name but
            # different options. Log and continue — the app still works,
            # just not optimally on this collection.
            logger.warning(f"Skipped index on {coll_name} ({opts.get('name')}): {exc}")
            skipped += 1

    logger.info(f"DB indexes ensured: {created} created/verified, {skipped} skipped")
