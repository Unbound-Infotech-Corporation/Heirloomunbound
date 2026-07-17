"""Idempotent MongoDB index creation. Called once at app startup.

Indexes are the single biggest production-readiness win on this app:
- `user_sessions.session_token` is hit on every authenticated request.
- `users.user_id` is hit on every authenticated request (after session lookup).
- `entries.user_id` / `companion_devices.token` / `heirs.release_token` are hit
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
        # Field is `type` (not entry_type) on every write path.
        ("entries", [("user_id", 1), ("created_at", -1)], {"name": "user_created"}),
        ("entries", [("user_id", 1), ("type", 1)], {"name": "user_type"}),
        ("entries", [("user_id", 1), ("tags", 1)], {"name": "user_tags"}),
        ("conversations", [("user_id", 1), ("kind", 1), ("updated_at", -1)], {"name": "user_kind_updated"}),
        ("conversations", [("conversation_id", 1)], {"unique": True, "name": "conv_id_uniq"}),

        # Companion — hit on every poll cycle (2s) from local PC
        ("companion_devices", [("token", 1)], {"unique": True, "sparse": True, "name": "token_uniq"}),
        ("companion_devices", [("user_id", 1)], {"name": "user_id"}),

        # Heirs + public portal — release_token lookup on every portal page hit
        ("heirs", [("user_id", 1)], {"name": "user_id"}),
        ("heirs", [("release_token", 1)], {"sparse": True, "name": "release_token"}),

        # Letters
        ("letters", [("user_id", 1), ("created_at", -1)], {"name": "user_created"}),

        # Long-term memory (twin system prompt builds this every turn)
        ("memories", [("user_id", 1), ("kind", 1)], {"name": "user_kind"}),
        ("identity_facts", [("user_id", 1)], {"name": "user_id"}),
        ("memory_facts", [("user_id", 1)], {"name": "user_id"}),
        ("memory_facts", [("user_id", 1), ("fact_id", 1)], {"name": "user_fact_id"}),
        ("memory_episodes", [("user_id", 1), ("created_at", -1)], {"name": "user_created"}),
        ("memory_state", [("user_id", 1)], {"unique": True, "name": "user_id_uniq"}),
        ("user_abilities", [("user_id", 1), ("ability_id", 1)], {"unique": True, "name": "user_ability_uniq"}),

        # Skills + reminders
        ("skills", [("user_id", 1)], {"name": "user_id"}),
        ("reminders", [("user_id", 1), ("due_at", 1)], {"name": "user_due"}),

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
    ]

    created = 0
    skipped = 0
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
