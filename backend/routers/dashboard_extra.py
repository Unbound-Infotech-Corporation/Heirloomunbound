"""On This Day — surface archive entries created on this calendar date in past years."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from deps import db, get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard-extra"])


@router.get("/on-this-day")
async def on_this_day(user: dict = Depends(get_current_user)):
    """Entries written on this month+day in prior years."""
    now = datetime.now(timezone.utc)
    mm = f"{now.month:02d}"
    dd = f"{now.day:02d}"
    # created_at is stored as ISO strings — match 'YYYY-MM-DD' pattern with our mm-dd
    regex = f"-{mm}-{dd}T"
    cursor = db.entries.find(
        {"user_id": user["user_id"], "created_at": {"$regex": regex}},
        {"_id": 0},
    ).sort("created_at", -1).limit(10)
    items = await cursor.to_list(length=10)
    return {"date": f"{mm}-{dd}", "entries": items}


@router.get("/recent-journals")
async def recent_journals(user: dict = Depends(get_current_user)):
    cursor = db.entries.find(
        {"user_id": user["user_id"], "type": "voice"}, {"_id": 0}
    ).sort("created_at", -1).limit(5)
    return {"entries": await cursor.to_list(length=5)}


@router.get("/last-twin-chat")
async def last_twin_chat(user: dict = Depends(get_current_user)):
    conv = await db.conversations.find_one(
        {"user_id": user["user_id"], "kind": "twin", "messages.1": {"$exists": True}},
        {"_id": 0},
        sort=[("updated_at", -1)],
    )
    if not conv:
        return {"conversation": None}
    msgs = conv.get("messages", [])[-4:]  # last 4 turns
    return {
        "conversation_id": conv["conversation_id"],
        "updated_at": conv.get("updated_at"),
        "tail": msgs,
    }
