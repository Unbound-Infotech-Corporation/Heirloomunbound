"""Standing Twin routines for the owner — Slice 3 of OWNER_RAIL.md.

Opt-in, consent-first. Morning briefs, a weekly biographer prompt, and an
optional sealed-letter nudge fire through the existing nudges collection.
Empty mornings stay quiet. Heirs never receive these productivity routines.
Twin voice only: grounded in archive / reminders / letters, never invented.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

ROUTINE_KINDS = ("morning_brief", "weekly_biographer", "sealed_letter_nudge")

ROUTINE_CATALOG: tuple[tuple[str, str, str], ...] = (
    (
        "morning_brief",
        "Morning brief",
        "A quiet note in your voice when something is on the plate — due reminders, "
        "what you filed yesterday, a letter coming due. Empty mornings stay silent.",
    ),
    (
        "weekly_biographer",
        "Weekly biographer",
        "Once a week, one grounded question about a part of your life that is still thin "
        "in the archive. If there is not enough to ask from, it stays quiet.",
    ),
    (
        "sealed_letter_nudge",
        "Sealed letter nudge",
        "A light tap when a draft is still unsealed, or an heir still has no letter. "
        "No nag when nothing is waiting.",
    ),
)

# Archive gaps the weekly prompt may sit with. Labels must match filed titles/tags
# — we never invent a life to fill them.
GAP_PROMPTS: tuple[dict[str, str], ...] = (
    {
        "key": "childhood",
        "label": "Childhood home",
        "question": "Describe the home you grew up in — the rooms, the people, the routines.",
    },
    {
        "key": "first_love",
        "label": "First love",
        "question": "Tell the story of the first person you loved.",
    },
    {
        "key": "fatherhood",
        "label": "Fatherhood / parenting",
        "question": "What did becoming a parent teach you that nothing else could?",
    },
    {
        "key": "work",
        "label": "Your work / craft",
        "question": "Describe your work — what you do, why you do it, what it cost you.",
    },
    {
        "key": "faith",
        "label": "Faith / meaning",
        "question": "What do you believe about why we're here?",
    },
    {
        "key": "friendship",
        "label": "A friendship",
        "question": "Tell the story of a friendship that shaped you.",
    },
    {
        "key": "loss",
        "label": "A loss",
        "question": "Tell us about someone you lost and what they gave you.",
    },
)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def routines_allowed(*, audience: str | None = "owner", heir_surface: bool = False) -> bool:
    """Heirs / callers / the portal never get owner standing routines."""
    if heir_surface:
        return False
    return (audience or "owner").strip().lower() == "owner"


def period_key(kind: str, now: datetime) -> str:
    utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if kind == "morning_brief":
        return utc.strftime("%Y-%m-%d")
    iso = utc.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def default_routine_state() -> dict[str, dict[str, Any]]:
    return {kind: {"enabled": False, "last_run": None} for kind in ROUTINE_KINDS}


def normalize_routines(raw: Any = None) -> dict[str, dict[str, Any]]:
    """Enabled flags default off (consent). last_run is a period key or None."""
    src = raw if isinstance(raw, dict) else {}
    out = default_routine_state()
    for kind in ROUTINE_KINDS:
        item = src.get(kind)
        if isinstance(item, bool):
            out[kind]["enabled"] = item
            continue
        if not isinstance(item, dict):
            continue
        out[kind]["enabled"] = _as_bool(item.get("enabled"), False)
        last = item.get("last_run")
        out[kind]["last_run"] = str(last).strip() if last else None
    return out


def routines_from_user(user: dict | None) -> dict[str, dict[str, Any]]:
    src = (user or {}).get("standing_routines")
    return normalize_routines(src)


def routines_public(user: dict | None = None) -> dict[str, Any]:
    state = routines_from_user(user)
    catalog = {kind: {"label": label, "description": desc} for kind, label, desc in ROUTINE_CATALOG}
    routines = {}
    for kind in ROUTINE_KINDS:
        routines[kind] = {
            **state[kind],
            **catalog[kind],
        }
    return {"standing_routines": routines, "routines_owner_only": True}


def apply_enabled_updates(current: dict[str, dict[str, Any]], updates: dict[str, Any]) -> dict[str, dict[str, Any]]:
    next_state = normalize_routines(current)
    for kind in ROUTINE_KINDS:
        if kind in updates and updates[kind] is not None:
            next_state[kind]["enabled"] = _as_bool(updates[kind], False)
    return next_state


def due_kinds(state: dict[str, dict[str, Any]], now: datetime) -> list[str]:
    normalized = normalize_routines(state)
    due: list[str] = []
    for kind in ROUTINE_KINDS:
        if not normalized[kind]["enabled"]:
            continue
        if normalized[kind]["last_run"] == period_key(kind, now):
            continue
        due.append(kind)
    return due


def morning_has_signal(snapshot: dict | None) -> bool:
    snap = snapshot or {}
    return bool(
        snap.get("overdue")
        or snap.get("due_today")
        or snap.get("recent_titles")
        or snap.get("on_this_day")
        or snap.get("approaching_letters")
    )


def _titles(items: list[Any], key: str = "text") -> list[str]:
    out: list[str] = []
    for item in items or []:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        for field in (key, "title", "text", "name"):
            val = item.get(field)
            if isinstance(val, str) and val.strip():
                out.append(val.strip())
                break
    return out


def _join(parts: list[str], *, limit: int = 4) -> str:
    clipped = [p for p in parts if p][:limit]
    if not clipped:
        return ""
    if len(clipped) == 1:
        return clipped[0]
    if len(clipped) == 2:
        return f"{clipped[0]}; {clipped[1]}"
    return "; ".join(clipped[:-1]) + f"; {clipped[-1]}"


def compose_morning_brief(snapshot: dict | None, *, name: str = "") -> dict[str, Any] | None:
    """Twin-voiced morning note. Returns None when there is nothing to report."""
    snap = snapshot or {}
    if not morning_has_signal(snap):
        return None

    overdue = _titles(list(snap.get("overdue") or []))
    due_today = _titles(list(snap.get("due_today") or []))
    recent = _titles(list(snap.get("recent_titles") or []), key="title")
    on_this_day = _titles(list(snap.get("on_this_day") or []), key="title")
    letters = _titles(list(snap.get("approaching_letters") or []), key="title")

    bits: list[str] = []
    if overdue:
        bits.append(f"Overdue, still open: {_join(overdue)}.")
    if due_today:
        bits.append(f"On today's plate: {_join(due_today)}.")
    if recent:
        bits.append(f"I recently filed {_join(recent, limit=3)}.")
    if on_this_day:
        bits.append(f"On this day in the archive: {_join(on_this_day, limit=2)}.")
    if letters:
        bits.append(f"A sealed letter comes due soon: {_join(letters, limit=2)}.")
    bits.append("That is enough for this morning.")

    href = "/reminders" if (overdue or due_today) else "/owner"
    title = "On the plate" if (overdue or due_today) else "A quiet morning note"
    return {
        "kind": "morning_brief",
        "title": title,
        "body": " ".join(bits),
        "action_type": "memory",
        "action_prompt": overdue[0] if overdue else (due_today[0] if due_today else recent[0] if recent else title),
        "action_href": href,
        "action_label": "Open reminders" if href == "/reminders" else "Sit",
    }


def pick_archive_gap(snapshot: dict | None) -> dict[str, str] | None:
    """First catalog gap not covered by titles, tags, or held fact kinds. None if unknown."""
    snap = snapshot or {}
    titles = " ".join(_titles(list(snap.get("entry_titles") or []), key="title")).lower()
    tags: list[str] = []
    for item in snap.get("entry_tags") or []:
        if isinstance(item, str) and item.strip():
            tags.append(item.strip().lower())
        elif isinstance(item, (list, tuple)):
            tags.extend(str(t).strip().lower() for t in item if t)
    fact_kinds = {
        str(k).strip().lower()
        for k in (snap.get("fact_kinds") or [])
        if str(k).strip()
    }
    blob = f"{titles} {' '.join(tags)}"
    for gap in GAP_PROMPTS:
        key = gap["key"]
        label = gap["label"].lower()
        if key in tags or key in fact_kinds:
            continue
        if label and label in blob:
            continue
        return dict(gap)
    return None


def compose_weekly_biographer(snapshot: dict | None) -> dict[str, Any] | None:
    """One grounded question, or silence when the archive is empty / fully covered."""
    snap = snapshot or {}
    entry_count = int(snap.get("entry_count") or 0)
    fact_kinds = list(snap.get("fact_kinds") or [])
    if entry_count <= 0 and not fact_kinds:
        return None
    gap = pick_archive_gap(snap)
    if not gap:
        return None
    label = gap["label"]
    question = gap["question"]
    return {
        "kind": "weekly_biographer",
        "title": f"Still thin: {label}",
        "body": (
            f"I do not have enough on file about {label.lower()} to speak that part yet. "
            f"{question} Only if you want to sit — I will not invent it."
        ),
        "action_type": "journal",
        "action_prompt": question,
        "action_href": "/interviewer",
        "action_label": "Sit with this",
    }


def compose_sealed_letter_nudge(snapshot: dict | None) -> dict[str, Any] | None:
    snap = snapshot or {}
    drafts = list(snap.get("draft_letters") or [])
    heirs_without = list(snap.get("heirs_without_letter") or [])
    draft_titles = _titles(drafts, key="title")
    heir_names = _titles(heirs_without, key="name")
    if draft_titles:
        return {
            "kind": "sealed_letter_nudge",
            "title": "A letter still unsealed",
            "body": (
                f"A draft is still open: {_join(draft_titles, limit=2)}. "
                "I will not finish it for you."
            ),
            "action_type": "memory",
            "action_prompt": draft_titles[0],
            "action_href": "/letters",
            "action_label": "Open letters",
        }
    if heir_names:
        return {
            "kind": "sealed_letter_nudge",
            "title": "No letter on file yet",
            "body": (
                f"No sealed letter is on file for {_join(heir_names, limit=2)}. "
                "Write one when you are ready — I will not invent it."
            ),
            "action_type": "memory",
            "action_prompt": heir_names[0],
            "action_href": "/letters",
            "action_label": "Open letters",
        }
    return None


def compose_routine(kind: str, snapshot: dict | None, *, name: str = "") -> dict[str, Any] | None:
    if kind == "morning_brief":
        return compose_morning_brief(snapshot, name=name)
    if kind == "weekly_biographer":
        return compose_weekly_biographer(snapshot)
    if kind == "sealed_letter_nudge":
        return compose_sealed_letter_nudge(snapshot)
    return None


def skip_reason(kind: str, snapshot: dict | None) -> str:
    if kind == "morning_brief":
        return "empty"
    if kind == "weekly_biographer":
        snap = snapshot or {}
        if int(snap.get("entry_count") or 0) <= 0 and not snap.get("fact_kinds"):
            return "empty_archive"
        return "no_gap"
    if kind == "sealed_letter_nudge":
        return "nothing_waiting"
    return "unknown"


async def gather_routine_snapshot(db: Any, user_id: str, now: datetime) -> dict[str, Any]:
    """Read reminders, recent archive, letters, and facts. Never invents rows."""
    utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    now_iso = utc.isoformat()
    end_of_day = utc.replace(hour=23, minute=59, second=59).isoformat()
    recent_since = (utc - timedelta(hours=36)).isoformat()
    letter_horizon = (utc + timedelta(days=14)).date().isoformat()
    today = utc.date().isoformat()

    overdue = await db.reminders.find(
        {
            "user_id": user_id,
            "status": "open",
            "due_at": {"$ne": None, "$lt": now_iso},
        },
        {"_id": 0, "text": 1, "due_at": 1, "reminder_id": 1},
    ).sort("due_at", 1).to_list(length=8)

    due_today = await db.reminders.find(
        {
            "user_id": user_id,
            "status": "open",
            "due_at": {"$gte": now_iso, "$lte": end_of_day},
        },
        {"_id": 0, "text": 1, "due_at": 1, "reminder_id": 1},
    ).sort("due_at", 1).to_list(length=8)

    recent_entries = await db.entries.find(
        {"user_id": user_id, "created_at": {"$gte": recent_since}},
        {"_id": 0, "title": 1, "type": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(length=8)

    mm, dd = f"{utc.month:02d}", f"{utc.day:02d}"
    otd_raw = await db.entries.find(
        {"user_id": user_id, "created_at": {"$regex": f"-{mm}-{dd}T"}},
        {"_id": 0, "title": 1, "created_at": 1},
    ).sort("created_at", -1).to_list(length=8)
    on_this_day = [
        e for e in otd_raw if not str(e.get("created_at") or "").startswith(str(utc.year))
    ]

    approaching = await db.sealed_letters.find(
        {
            "user_id": user_id,
            "sealed": True,
            "delivered": {"$ne": True},
            "trigger": "on_date",
            "delivery_date": {"$gte": today, "$lte": letter_horizon},
        },
        {"_id": 0, "title": 1, "recipient_name": 1, "delivery_date": 1},
    ).to_list(length=6)

    drafts = await db.sealed_letters.find(
        {"user_id": user_id, "sealed": False},
        {"_id": 0, "title": 1, "recipient_name": 1, "letter_id": 1, "recipient_heir_id": 1},
    ).to_list(length=8)

    heirs = await db.heirs.find(
        {"user_id": user_id}, {"_id": 0, "heir_id": 1, "name": 1}
    ).to_list(length=30)
    heir_ids = [h.get("heir_id") for h in heirs if h.get("heir_id")]
    covered: set[str] = set()
    if heir_ids:
        existing_letters = await db.sealed_letters.find(
            {"user_id": user_id, "recipient_heir_id": {"$in": heir_ids}},
            {"_id": 0, "recipient_heir_id": 1},
        ).to_list(length=80)
        covered = {str(x.get("recipient_heir_id")) for x in existing_letters if x.get("recipient_heir_id")}
    heirs_without = [h for h in heirs if h.get("heir_id") and h["heir_id"] not in covered]

    facts = await db.identity_facts.find(
        {"user_id": user_id}, {"_id": 0, "kind": 1, "fact": 1}
    ).to_list(length=40)
    entry_count = await db.entries.count_documents({"user_id": user_id})
    titled = await db.entries.find(
        {"user_id": user_id}, {"_id": 0, "title": 1, "tags": 1}
    ).sort("created_at", -1).to_list(length=80)

    return {
        "overdue": overdue,
        "due_today": due_today,
        "recent_titles": recent_entries,
        "on_this_day": on_this_day,
        "approaching_letters": approaching,
        "draft_letters": drafts,
        "heirs_without_letter": heirs_without,
        "fact_kinds": [f.get("kind") for f in facts if f.get("kind")],
        "entry_count": entry_count,
        "entry_titles": titled,
        "entry_tags": [e.get("tags") or [] for e in titled],
    }


async def persist_routine_nudge(db: Any, user_id: str, kind: str, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    date_key = period_key(kind, now)
    existing = await db.nudges.find_one(
        {"user_id": user_id, "kind": kind, "date_key": date_key}, {"_id": 0}
    )
    if existing:
        return existing
    nudge_id = f"nud_{uuid.uuid4().hex[:12]}"
    doc: dict[str, Any] = {
        "nudge_id": nudge_id,
        "user_id": user_id,
        "date_key": date_key,
        "kind": kind,
        "source": "routine",
        **payload,
        "status": "open",
        "created_at": now.isoformat(),
    }
    await db.nudges.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def mark_routine_checked(db: Any, user_id: str, kind: str, now: datetime) -> None:
    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                f"standing_routines.{kind}.last_run": period_key(kind, now),
                f"standing_routines.{kind}.last_run_at": now.isoformat(),
            }
        },
    )


async def run_due_routines(
    db: Any,
    user: dict,
    *,
    now: datetime | None = None,
    audience: str = "owner",
    heir_surface: bool = False,
) -> dict[str, Any]:
    """Fire enabled, due routines. Skip empty mornings without writing a nudge."""
    now = now or datetime.now(timezone.utc)
    if not routines_allowed(audience=audience, heir_surface=heir_surface):
        return {"fired": [], "skipped": [{"kind": "*", "reason": "heir_fence"}], "quiet": True}

    state = routines_from_user(user)
    pending = due_kinds(state, now)
    if not pending:
        already = await db.nudges.find(
            {
                "user_id": user["user_id"],
                "source": "routine",
                "status": "open",
                "date_key": {"$in": [period_key(k, now) for k in ROUTINE_KINDS]},
            },
            {"_id": 0},
        ).to_list(length=12)
        return {"fired": already, "skipped": [], "quiet": not already}

    snapshot = await gather_routine_snapshot(db, user["user_id"], now)
    fired: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for kind in pending:
        payload = compose_routine(kind, snapshot, name=user.get("name") or "")
        await mark_routine_checked(db, user["user_id"], kind, now)
        if not payload:
            skipped.append({"kind": kind, "reason": skip_reason(kind, snapshot)})
            continue
        fired.append(await persist_routine_nudge(db, user["user_id"], kind, payload, now))

    return {"fired": fired, "skipped": skipped, "quiet": not fired}


async def run_routines_for_enabled_users(db: Any, *, limit: int = 80) -> dict[str, Any]:
    """Background sweep — owners who opted in. Heirs are not in this query."""
    cursor = db.users.find(
        {
            "$or": [
                {"standing_routines.morning_brief.enabled": True},
                {"standing_routines.weekly_biographer.enabled": True},
                {"standing_routines.sealed_letter_nudge.enabled": True},
            ]
        },
        {"_id": 0},
    ).limit(limit)
    users = await cursor.to_list(length=limit)
    fired = 0
    skipped = 0
    for user in users:
        try:
            result = await run_due_routines(db, user, audience="owner", heir_surface=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("standing routine sweep failed for %s: %s", user.get("user_id"), exc)
            continue
        fired += len(result.get("fired") or [])
        skipped += len(result.get("skipped") or [])
    return {"users": len(users), "fired": fired, "skipped": skipped}
