"""Onboarding — 5-minute Twin-led intro that pre-seeds the personality archive."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import db, get_current_user

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

DEFAULT_WIDGETS = {
    "reflection": True,
    "reminders": True,
    "on_this_day": True,
    "suggested_topics": True,
    "recent_journals": False,
    "last_twin_chat": False,
    "photo_of_day": False,
    "quote_of_day": False,
    "sources_status": False,
}


class OnboardingAnswers(BaseModel):
    preferred_name: str
    chapter: str  # e.g. "Parent of young kids", "Career builder", "Retired"
    key_people: str
    guiding_values: list[str]
    favorite_saying: Optional[str] = ""
    one_thing_to_remember: str
    daily_routine: Optional[str] = ""


@router.get("/state")
async def state(user: dict = Depends(get_current_user)):
    return {
        "onboarded": bool(user.get("onboarded")),
        "preferred_name": user.get("preferred_name") or user.get("name", ""),
        "profile": user.get("profile") or {},
        "dashboard_widgets": user.get("dashboard_widgets") or DEFAULT_WIDGETS,
    }


@router.post("/complete")
async def complete(answers: OnboardingAnswers, user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()

    profile = {
        "chapter": answers.chapter.strip(),
        "key_people": answers.key_people.strip(),
        "guiding_values": [v.strip() for v in answers.guiding_values if v.strip()][:8],
        "favorite_saying": (answers.favorite_saying or "").strip(),
        "daily_routine": (answers.daily_routine or "").strip(),
    }

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {
            "$set": {
                "onboarded": True,
                "preferred_name": answers.preferred_name.strip() or user.get("name", ""),
                "profile": profile,
                "dashboard_widgets": user.get("dashboard_widgets") or DEFAULT_WIDGETS,
                "onboarded_at": now,
            }
        },
    )

    # Pre-seed archive with the deepest answers
    seeds = []
    if profile["key_people"]:
        seeds.append(
            {
                "type": "memory",
                "title": "Who matters most to me right now",
                "content": profile["key_people"],
                "tags": ["onboarding", "people"],
            }
        )
    if profile["favorite_saying"]:
        seeds.append(
            {
                "type": "quote",
                "title": "A saying I find myself repeating",
                "content": profile["favorite_saying"],
                "tags": ["onboarding", "voice"],
            }
        )
    if profile["guiding_values"]:
        seeds.append(
            {
                "type": "value",
                "title": "What I try to live by",
                "content": ", ".join(profile["guiding_values"]),
                "tags": ["onboarding", "values"] + profile["guiding_values"],
            }
        )
    if answers.one_thing_to_remember.strip():
        seeds.append(
            {
                "type": "advice",
                "title": "One thing I want them to remember about me",
                "content": answers.one_thing_to_remember.strip(),
                "tags": ["onboarding", "heirloom"],
            }
        )
    if profile["chapter"]:
        seeds.append(
            {
                "type": "memory",
                "title": f"My current chapter — {profile['chapter']}",
                "content": f"This is the chapter of life I'm in right now: {profile['chapter']}.",
                "tags": ["onboarding", "chapter"],
            }
        )

    inserted = []
    for s in seeds:
        eid = f"ent_{uuid.uuid4().hex[:12]}"
        doc = {
            "entry_id": eid,
            "user_id": user["user_id"],
            **s,
            "source": "onboarding",
            "created_at": now,
            "updated_at": now,
        }
        await db.entries.insert_one(doc)
        inserted.append({"entry_id": eid, "type": s["type"], "title": s["title"]})

    return {"ok": True, "seeded": inserted, "count": len(inserted)}


class WidgetsUpdate(BaseModel):
    widgets: dict


@router.put("/widgets")
async def update_widgets(payload: WidgetsUpdate, user: dict = Depends(get_current_user)):
    # Validate: only allow known keys, only bool values
    clean = {
        k: bool(v)
        for k, v in (payload.widgets or {}).items()
        if k in DEFAULT_WIDGETS
    }
    if not clean:
        raise HTTPException(status_code=400, detail="No valid widget keys")
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$set": {"dashboard_widgets": clean}}
    )
    return {"ok": True, "widgets": clean}
