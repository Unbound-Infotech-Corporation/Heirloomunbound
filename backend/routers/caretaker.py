"""Owner-only Caretaker API on the Twin Box."""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from caretaker import (
    CaretakerState,
    HostOps,
    ack_companion,
    append_log_line,
    companion_path,
    confirm_pending,
    handle_chat,
    health_view,
    log_path,
    read_companion,
    read_log_lines,
)
from deps import get_current_user
from presence_access import require_owner

router = APIRouter(prefix="/caretaker", tags=["caretaker"])

_state = CaretakerState()


class ChatBody(BaseModel):
    text: str = Field(default="", max_length=2000)


class ConfirmBody(BaseModel):
    id: str = Field(default="", max_length=80)


def _ops() -> HostOps:
    root = (os.environ.get("HEIRLOOM_ROOT") or "").strip()
    compose = os.path.join(root, "box") if root else ""
    ops = HostOps(compose_dir=compose)

    def observer() -> dict:
        try:
            from observer_store import status_public

            return status_public()
        except Exception:
            return {}

    def presence() -> dict:
        try:
            from presence_store import status_public as presence_status

            return presence_status()
        except Exception:
            return {}

    ops.observer = observer  # type: ignore[method-assign]
    ops.presence = presence  # type: ignore[method-assign]
    return ops


def _persist(state: CaretakerState) -> None:
    if not state.log:
        return
    try:
        append_log_line(log_path(), state.log[-1])
    except OSError:
        return


@router.get("")
async def caretaker_home(user: dict = Depends(get_current_user)):
    require_owner(user)
    ops = _ops()
    from brain_route import brain_status

    return {
        "clone": "Caretaker",
        "brain": brain_status(),
        "health": health_view(observer=ops.observer(), presence=ops.presence(), gpu_csv=ops.gpu_csv()),
        "log": read_log_lines(log_path()),
        "pending_id": next(iter(_state.pending), ""),
    }


@router.post("/chat")
async def caretaker_chat(body: ChatBody, user: dict = Depends(get_current_user)):
    require_owner(user)
    result = handle_chat(body.text, _ops(), _state)
    _persist(_state)
    return result


@router.post("/confirm")
async def caretaker_confirm(body: ConfirmBody, user: dict = Depends(get_current_user)):
    require_owner(user)
    result = confirm_pending(body.id, _ops(), _state)
    _persist(_state)
    return result


@router.get("/log")
async def caretaker_log(user: dict = Depends(get_current_user)):
    require_owner(user)
    disk = read_log_lines(log_path())
    memory = _state.log[-40:]
    return {"log": disk or memory}


@router.get("/companion")
async def caretaker_companion(user: dict = Depends(get_current_user)):
    require_owner(user)
    return read_companion(companion_path())


@router.post("/companion/ack")
async def caretaker_companion_ack(user: dict = Depends(get_current_user)):
    require_owner(user)
    ack_companion(companion_path())
    return {"ok": True}
