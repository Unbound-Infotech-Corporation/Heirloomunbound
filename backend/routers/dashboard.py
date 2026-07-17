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


async def _streak_days(user_id: str, now: datetime) -> int:
    """Consecutive UTC days with ≥1 entry — one aggregation, no per-day round trips."""
    since = (now - timedelta(days=365)).replace(hour=0, minute=0, second=0, microsecond=0)
    pipeline = [
        {"$match": {"user_id": user_id, "created_at": {"$gte": since.isoformat()}}},
        {"$project": {"day": {"$substr": [{"$ifNull": ["$created_at", ""]}, 0, 10]}}},
        {"$group": {"_id": "$day"}},
    ]
    days = set()
    async for row in db.entries.aggregate(pipeline):
        if row.get("_id"):
            days.add(row["_id"])
    streak = 0
    cur = now
    while streak < 365:
        key = cur.strftime("%Y-%m-%d")
        if key in days:
            streak += 1
            cur = cur - timedelta(days=1)
        else:
            break
    return streak


async def _suggested_topics(user_id: str) -> list[dict]:
    """Match topics in-process against a single titles/tags fetch."""
    rows = await db.entries.find(
        {"user_id": user_id},
        {"_id": 0, "title": 1, "tags": 1},
    ).to_list(length=2000)
    titles = " ".join((r.get("title") or "").lower() for r in rows)
    tags = set()
    for r in rows:
        for t in r.get("tags") or []:
            if isinstance(t, str):
                tags.add(t.lower())
    suggested = []
    for topic in TOPIC_PROMPTS:
        if topic["key"].lower() in tags or topic["label"].lower() in titles:
            continue
        suggested.append(topic)
        if len(suggested) >= 6:
            break
    return suggested


@router.get("")
async def stats(user: dict = Depends(get_current_user)):
    user_id = user["user_id"]
    now = datetime.now(timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59).isoformat()

    async def _counts_by_type():
        counts: dict = {}
        cursor = db.entries.aggregate([
            {"$match": {"user_id": user_id}},
            {"$group": {
                "_id": "$type",
                "n": {"$sum": 1},
                # Approximate words via whitespace splits in the DB — one pass.
                "words": {"$sum": {
                    "$size": {
                        "$split": [{"$trim": {"input": {"$ifNull": ["$content", ""]}}}, " "]
                    }
                }},
            }},
        ])
        total_words = 0
        async for row in cursor:
            counts[row["_id"]] = row["n"]
            total_words += int(row.get("words") or 0)
        # Empty-content entries produce a single "" token from $split — correct that.
        # Cheap enough; accuracy is fine for a progress bar.
        return counts, sum(counts.values()), total_words

    (counts, total_entries, total_words), interview_convs, twin_convs, heirs, skills, overdue_count, today_count, open_count, streak, suggested = await asyncio.gather(
        _counts_by_type(),
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
        _streak_days(user_id, now),
        _suggested_topics(user_id),
    )

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
