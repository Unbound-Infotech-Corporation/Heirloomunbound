"""Dashboard stats: capture progress, counts, suggested next topics."""
from datetime import timedelta

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


@router.get("")
async def stats(user: dict = Depends(get_current_user)):
    user_id = user["user_id"]

    counts: dict = {}
    cursor = db.entries.aggregate([
        {"$match": {"user_id": user_id}},
        {"$group": {"_id": "$type", "n": {"$sum": 1}}},
    ])
    async for row in cursor:
        counts[row["_id"]] = row["n"]
    total_entries = sum(counts.values())

    # Total words archived
    total_words = 0
    word_cursor = db.entries.find({"user_id": user_id}, {"_id": 0, "content": 1})
    async for row in word_cursor:
        total_words += len((row.get("content") or "").split())

    interview_convs = await db.conversations.count_documents(
        {"user_id": user_id, "kind": "interviewer"}
    )
    twin_convs = await db.conversations.count_documents(
        {"user_id": user_id, "kind": "twin"}
    )
    heirs = await db.heirs.count_documents({"user_id": user_id})
    skills = await db.skills.count_documents({"user_id": user_id})

    # Live Assistant — Today snapshot
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59).isoformat()
    overdue_count = await db.reminders.count_documents({
        "user_id": user_id, "status": "open",
        "due_at": {"$ne": None, "$lt": now.isoformat()},
    })
    today_count = await db.reminders.count_documents({
        "user_id": user_id, "status": "open",
        "due_at": {"$gte": now.isoformat(), "$lte": end_of_day},
    })
    open_count = await db.reminders.count_documents({"user_id": user_id, "status": "open"})

    # Streak: consecutive UTC days with at least one new entry, walking back from today.
    streak = 0
    cur = now
    while True:
        day_start = cur.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = cur.replace(hour=23, minute=59, second=59, microsecond=999000)
        exists = await db.entries.count_documents({
            "user_id": user_id,
            "created_at": {"$gte": day_start.isoformat(), "$lte": day_end.isoformat()},
        })
        if exists:
            streak += 1
            cur = cur - timedelta(days=1)
            if streak >= 365:
                break
        else:
            break

    # Suggested topics user hasn't covered — match by tag/title heuristic
    suggested = []
    for topic in TOPIC_PROMPTS:
        covered = await db.entries.count_documents({
            "user_id": user_id,
            "$or": [
                {"tags": topic["key"]},
                {"title": {"$regex": topic["label"], "$options": "i"}},
            ],
        })
        if covered == 0:
            suggested.append(topic)
        if len(suggested) >= 6:
            break

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
