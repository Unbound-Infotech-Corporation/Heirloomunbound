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
        ("entries", [("user_id", 1), ("created_at", -1)], {"name": "user_created"}),
        ("entries", [("user_id", 1), ("entry_type", 1)], {"name": "user_type"}),
        ("conversations", [("user_id", 1), ("started_at", -1)], {"name": "user_started"}),
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

        # Local AI provider config (per-user)
        ("user_providers", [("user_id", 1)], {"unique": True, "name": "user_uniq"}),

        # Semantic memory search — one vector per (user, entry, model)
        ("archive_embeddings", [("user_id", 1), ("entry_id", 1), ("embedding_model", 1)],
            {"unique": True, "name": "user_entry_model_uniq"}),
        ("archive_embeddings", [("user_id", 1), ("embedding_model", 1)],
            {"name": "user_model"}),

        # Twilio Voice — routes inbound calls by "To" number
        ("user_twilio", [("user_id", 1)], {"unique": True, "name": "user_uniq"}),
        ("user_twilio", [("phone_number", 1)], {"unique": True, "sparse": True, "name": "number_uniq"}),
        ("twilio_calls", [("user_id", 1), ("created_at", -1)], {"name": "user_recent"}),
        ("twilio_calls", [("call_sid", 1)], {"unique": True, "sparse": True, "name": "sid_uniq"}),
        ("twilio_calls", [("seed_id", 1)], {"unique": True, "sparse": True, "name": "seed_uniq"}),

        # Multi-provider router usage tracking + budget alerts
        ("usage_events", [("user_id", 1), ("ts", -1)], {"name": "user_ts"}),
        ("usage_events", [("user_id", 1), ("provider", 1), ("ts", -1)], {"name": "user_provider_ts"}),
        # Budget alert idempotency — one row per (user, provider, month, tier).
        ("budget_alerts", [("user_id", 1), ("provider", 1), ("month", 1), ("tier", 1)],
            {"unique": True, "name": "user_provider_month_tier_uniq"}),

        # Provider health — one current-state row per (user, provider)
        ("provider_health", [("user_id", 1), ("provider", 1)],
            {"unique": True, "name": "user_provider_uniq"}),

        # Photo restoration
        ("restoration_jobs", [("user_id", 1), ("created_at", -1)], {"name": "user_created"}),
        ("restoration_jobs", [("job_id", 1)], {"unique": True, "name": "job_id_uniq"}),

        # Multi-provider router config (Phase 35+ — separate from user_providers)
        ("routing_configs", [("user_id", 1)], {"unique": True, "name": "user_uniq"}),

        # Custom (user-saved) routing templates
        ("user_templates", [("user_id", 1), ("created_at", 1)], {"name": "user_created"}),
        ("user_templates", [("template_id", 1)], {"unique": True, "name": "template_id_uniq"}),

        # Projection history snapshots — one row per (user, provider, day).
        ("projection_history", [("user_id", 1), ("provider", 1), ("day", 1)],
            {"unique": True, "name": "user_provider_day_uniq"}),
        ("projection_history", [("user_id", 1), ("day", -1)], {"name": "user_day"}),

        # companion_commands hot path (poller reads by user_id + status)
        ("companion_commands", [("user_id", 1), ("status", 1), ("created_at", 1)],
            {"name": "user_status_created"}),

        # Web Push subscriptions — one row per (user, endpoint)
        ("push_subscriptions", [("user_id", 1), ("endpoint", 1)],
            {"unique": True, "name": "user_endpoint_uniq"}),

        # Mobile contacts book
        ("contacts", [("user_id", 1), ("name", 1)], {"name": "user_name"}),
        ("contacts", [("contact_id", 1)], {"unique": True, "name": "contact_id_uniq"}),
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
