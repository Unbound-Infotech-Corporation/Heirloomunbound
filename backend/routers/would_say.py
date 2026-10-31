"""Owner page API for the 'Would C L say that?' set. Heirs receive 404."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from brain_route import current_settings
from deps import db, get_current_user
from owner_style import _load_doc, public_profile
from presence_access import require_owner
from would_say import (
    case_from_style,
    cases_from_messages,
    execute_run,
    judge_user,
    local_only_reason,
    parse_judge,
    selectable_conversations,
    style_text,
)

router = APIRouter(prefix="/would-say", tags=["would-say"])


class CaseBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=800)
    reference: str = Field(..., min_length=1, max_length=1200)
    source: str = Field(default="owner", max_length=40)


class ImportBody(BaseModel):
    cases: list[CaseBody] = Field(default_factory=list)


class RunBody(BaseModel):
    brain: str = Field(default="local", max_length=16)


def _case_doc(user_id: str, prompt: str, reference: str, source: str) -> dict:
    from datetime import datetime, timezone

    return {
        "case_id": f"wsc_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "prompt": prompt.strip(),
        "reference": reference.strip(),
        "source": (source or "owner").strip()[:40] or "owner",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def _cases(user_id: str) -> list[dict]:
    cursor = db.would_say_cases.find({"user_id": user_id}, {"_id": 0}).sort("created_at", 1)
    return await cursor.to_list(length=200)


async def _complete_for(brain: str, profile: str):
    from llm_provider import complete_text

    settings = await current_settings()

    async def complete(prompt: str) -> str:
        system = (
            "You are the owner, speaking in first person. "
            "Match the style notes. Do not invent facts that contradict them.\n"
            + profile
        )
        if brain == "remote":
            if not settings.remote_url:
                raise RuntimeError("No remote brain is configured")
            from brain_route import auth_headers

            return await complete_text(
                system,
                prompt,
                pin_host=True,
                model=settings.remote_model,
                base_url=settings.remote_url,
                headers=auth_headers(settings.token),
            )
        return await complete_text(
            system,
            prompt,
            pin_host=True,
            model=settings.local_model,
            base_url=settings.local_url,
        )

    model = settings.remote_model if brain == "remote" else settings.local_model
    return complete, model


async def _judge(prompt: str, reference: str, reply: str) -> tuple[float, str]:
    from llm_provider import complete_text, ollama_base_url, ollama_model
    from would_say import JUDGE_SYSTEM

    raw = await complete_text(
        JUDGE_SYSTEM,
        judge_user(prompt, reference, reply),
        pin_host=True,
        model=ollama_model(),
        base_url=ollama_base_url(),
    )
    return parse_judge(raw)


@router.get("/cases")
async def list_cases(user: dict = Depends(get_current_user)):
    require_owner(user)
    rows = await _cases(user["user_id"])
    return {"cases": rows, "count": len(rows)}


@router.post("/cases")
async def add_case(body: CaseBody, user: dict = Depends(get_current_user)):
    require_owner(user)
    doc = _case_doc(user["user_id"], body.prompt, body.reference, body.source)
    await db.would_say_cases.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.post("/cases/import")
async def import_cases(body: ImportBody, user: dict = Depends(get_current_user)):
    require_owner(user)
    if not body.cases:
        raise HTTPException(status_code=400, detail="Add at least one case")
    docs = [
        _case_doc(user["user_id"], case.prompt, case.reference, case.source)
        for case in body.cases[:40]
    ]
    await db.would_say_cases.insert_many([dict(doc) for doc in docs])
    for doc in docs:
        doc.pop("_id", None)
    return {"cases": docs, "count": len(docs)}


@router.delete("/cases/{case_id}")
async def delete_case(case_id: str, user: dict = Depends(get_current_user)):
    require_owner(user)
    result = await db.would_say_cases.delete_one({"case_id": case_id, "user_id": user["user_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@router.post("/suggest")
async def suggest_cases(user: dict = Depends(get_current_user)):
    """Draft cases from saved owner lines and the style profile. Nothing is stored."""
    require_owner(user)
    cursor = db.conversations.find(
        {"user_id": user["user_id"]},
        {"_id": 0, "conversation_id": 1, "messages": 1, "audience": 1},
    ).sort("updated_at", -1).limit(20)
    conversations = await cursor.to_list(length=20)
    suggested = cases_from_messages(selectable_conversations(conversations))
    profile = await _load_doc(user["user_id"])
    style_case = case_from_style(public_profile(profile) if profile else profile)
    if style_case:
        suggested.append(style_case)
    return {"cases": suggested, "count": len(suggested)}


@router.post("/run")
async def run_cases(body: RunBody, user: dict = Depends(get_current_user)):
    require_owner(user)
    reason = local_only_reason()
    if reason:
        raise HTTPException(status_code=400, detail=reason)
    brain = (body.brain or "local").strip().lower()
    if brain == "both":
        brains = ["local", "remote"]
    elif brain in {"local", "remote"}:
        brains = [brain]
    else:
        raise HTTPException(status_code=400, detail="Brain must be local, remote, or both")
    cases = await _cases(user["user_id"])
    if not cases:
        raise HTTPException(status_code=400, detail="Add a case first")
    profile_doc = await _load_doc(user["user_id"])
    profile = style_text(public_profile(profile_doc) if profile_doc else None)
    runs = []
    for name in brains:
        complete, model = await _complete_for(name, profile)
        try:
            result = await execute_run(
                cases,
                brain=name,
                complete=complete,
                judge=_judge,
                profile_text=profile,
                model=model,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result["user_id"] = user["user_id"]
        await db.would_say_runs.insert_one(dict(result))
        result.pop("_id", None)
        runs.append(result)
    return {"runs": runs}


@router.get("/runs")
async def list_runs(user: dict = Depends(get_current_user), limit: int = 20):
    require_owner(user)
    cap = 1 if limit < 1 else min(int(limit), 50)
    cursor = (
        db.would_say_runs.find({"user_id": user["user_id"]}, {"_id": 0})
        .sort("created_at", -1)
        .limit(cap)
    )
    rows = await cursor.to_list(length=cap)
    return {"runs": rows, "count": len(rows)}
