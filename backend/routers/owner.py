"""Owner rail chat — session-auth teammate entry (web).

Heirs use the portal, not this router. One composer; server classifies
each turn to Assist (Do) and/or Twin (As you).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user
from owner_rail import owner_response_fields, run_owner_turn
from routers.live import publish_turn as live_publish_turn
from twin_runtime import ensure_conversation

router = APIRouter(prefix="/owner", tags=["owner"])


class OwnerChatReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    grounded: Optional[bool] = None
    persona: Optional[str] = Field(None, max_length=24)


@router.get("/conversation")
async def get_owner_conversation(user: dict = Depends(get_current_user), limit: int = 80):
    conv = await ensure_conversation(user["user_id"], kind="companion_owner")
    msgs = conv.get("messages", [])
    if limit and len(msgs) > limit:
        msgs = msgs[-limit:]
    return {
        "conversation_id": conv["conversation_id"],
        "kind": "companion_owner",
        "messages": msgs,
    }


@router.post("/chat")
async def owner_chat(body: OwnerChatReq, user: dict = Depends(get_current_user)):
    """Owner-only teammate turn. Always audience=owner; never an heir surface.

    Assist / Do legs include `receipt`. Both-leg turns also return
    `twin_reply` and `assist_reply` so Sit can keep Ask and Do separate.
    """
    if user.get("account_status") == "refunded":
        raise HTTPException(status_code=403, detail="account_inactive")

    conv = await ensure_conversation(user["user_id"], kind="companion_owner")
    try:
        result = await run_owner_turn(
            user,
            body.text,
            conversation=conv,
            source="web_owner",
            persist=True,
            summarise=True,
            grounded=body.grounded,
            persona_hint=body.persona,
            audience="owner",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await live_publish_turn(user["user_id"], "user", body.text, source="web_owner")
    await live_publish_turn(user["user_id"], "assistant", result.reply, source="web_owner")

    out: dict = {
        "reply": result.reply,
        "ts": result.ts,
        "conversation_id": result.conversation_id,
        "tool_trace": result.tool_trace,
        "twin_backend": result.backend,
        **owner_response_fields(result),
    }
    if result.action:
        out["action"] = result.action
    return out
