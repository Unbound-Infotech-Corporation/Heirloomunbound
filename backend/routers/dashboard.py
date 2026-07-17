"""Dashboard stats: capture progress, counts, suggested next topics."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from deps import db, get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Suggested capture topics — the dashboard nudges the user to these gaps
TOPIC_PROMPTS = [
    {"key": "childhood", "label": "Childhood home", "question": "Describe the home you grew up in — the rooms, the people, the routines."},
    {"key": "first_love", "label": "First love", "question": "Tell the story of the first person you loved."},
    {"key": "fatherhood", "label": "Fatherhood / parenting", "question": "What did becoming a parent teach you that nothing else could?"},
    {"key": "regret", "label": "A regret", "question": "Name a regret you carry — and what you'd say to yourself back then."},
    {"key": "work", "label": "Your work / craft", "question": "Describe your work — what you do, why you do it, what it cost you."},
    {"key": "advice_son_18", "label": "Letter to your son at 18", "question": "Write a letter to your son for the day he turns 18."},
    {"key": "advice_son_30", "label": "Letter to your son at 30", "question": "Write a letter to your son for when he's 30."},
    {"key": "faith", "label": "Faith / meaning", "question": "What do you believe about why we're here?"},
    {"key": "fear", "label": "A real fear", "question": "What's a fear you've carried, and what helps you when it visits?"},
    {"key": "joy", "label": "Pure joy", "question": "Describe a moment of pure joy in vivid detail."},
    {"key": "friendship", "label": "A friendship", "question": "Tell the story of a friendship that shaped you."},
    {"key": "loss", "label": "A loss", "question": "Tell us about someone you lost and what they gave you."},
]

# Cap streak walk so a brand-new archive can't trigger hundreds of round-trips.
_STREAK_LOOKBACK_DAYS = 120


async def _counts_and_words(user_id: str) -> tuple[dict, int, int]:
    """One aggregation: per-type counts + approximate word total (no full content fetch)."""
    cursor = db.entries.aggregate([
        {"$match": {"user_id": user_id}},
        {
            "$group": {
                "_id": "$type",
                "n": {"$sum": 1},
                # Split on whitespace in-DB — avoids shipping every content blob to Python.
                "words": {
                    "$sum": {
                        "$size": {
                            "$filter": {
                                "input": {"$split": [{"$ifNull": ["$content", ""]}, " "]},
                                "as": "w",
                                "cond": {"$ne": ["$$w", ""]},
                            }
                        }
                    }
                },
            }
        },
    ])
    counts: dict = {}
    total_words = 0
    async for row in cursor:
        counts[row["_id"]] = row["n"]
        total_words += int(row.get("words") or 0)
    return counts, sum(counts.values()), total_words


async def _compute_streak(user_id: str, now: datetime) -> int:
    """Consecutive UTC days with ≥1 entry, walking back from today.

    Uses a single query for recent entry dates instead of up to 365 count_documents.
    """
    lookback_start = (now - timedelta(days=_STREAK_LOOKBACK_DAYS - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    cursor = db.entries.find(
        {
            "user_id": user_id,
            "created_at": {"$gte": lookback_start.isoformat()},
        },
        {"_id": 0, "created_at": 1},
    )
    active_days: set[str] = set()
    async for row in cursor:
        raw = row.get("created_at") or ""
        if isinstance(raw, datetime):
            day = raw.astimezone(timezone.utc).date().isoformat()
        else:
            day = str(raw)[:10]
        if len(day) == 10:
            active_days.add(day)

    streak = 0
    cur = now.date()
    for _ in range(_STREAK_LOOKBACK_DAYS):
        if cur.isoformat() in active_days:
            streak += 1
            cur = cur - timedelta(days=1)
        else:
            break
    return streak


async def _suggested_topics(user_id: str) -> list[dict]:
    """Find uncovered topics with one $facet query instead of N sequential counts."""
    facet: dict = {}
    for topic in TOPIC_PROMPTS:
        facet[topic["key"]] = [
            {
                "$match": {
                    "$or": [
                        {"tags": topic["key"]},
                        {"title": {"$regex": topic["label"], "$options": "i"}},
                    ]
                }
            },
            {"$limit": 1},
            {"$project": {"_id": 1}},
        ]

    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$facet": facet},
    ]
    rows = await db.entries.aggregate(pipeline).to_list(length=1)
    covered = rows[0] if rows else {}

    suggested = []
    for topic in TOPIC_PROMPTS:
        if not covered.get(topic["key"]):
            suggested.append(topic)
        if len(suggested) >= 6:
            break
    return suggested


@router.get("")
async def stats(user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    now = datetime.now(timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59).isoformat()

    (
        (counts, total_entries, total_words),
        interview_convs,
        twin_convs,
        heirs,
        skills,
        overdue_count,
        today_count,
        open_count,
        streak,
        suggested,
    ) = await asyncio.gather(
        _counts_and_words(user_id),
        db.conversations.count_documents({"user_id": user_id, "kind": "interviewer"}),
        db.conversations.count_documents({"user_id": user_id, "kind": "twin"}),
        db.heirs.count_documents({"user_id": user_id}),
        db.skills.count_documents({"user_id": user_id}),
        db.reminders.count_documents({
            "user_id": user_id, "status": "open",
            "due_at": {"$ne": None, "$lt": now.isoformat()},
        }),
        db.reminders.count_documents({
            "user_id": user_id, "status": "open",
            "due_at": {"$gte": now.isoformat(), "$lte": end_of_day},
        }),
        db.reminders.count_documents({"user_id": user_id, "status": "open"}),
        _compute_streak(user_id, now),
        _suggested_topics(user_id),
    )

    # Completeness: 0..100 — non-linear, very rough heuristic so the bar moves nicely
    target_entries = 80
    target_words = 8000
    completeness = min(
        100,
        int(50 * min(total_entries / target_entries, 1.0) + 50 * min(total_words / target_words, 1.0)),
    )

    return {
        "counts_by_type": counts,
        "total_entries": total_entries,
        "total_words": total_words,
        "interview_conversations": interview_convs,
        "twin_conversations": twin_convs,
        "heirs": heirs,
        "skills": skills,
        "completeness": completeness,
        "suggested_topics": suggested,
        "streak_days": streak,
        "reminders_open": open_count,
        "reminders_today": today_count,
        "reminders_overdue": overdue_count,
    }
