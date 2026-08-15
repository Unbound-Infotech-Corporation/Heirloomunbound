"""Focus/Agent Mode — the twin plans and executes multi-step tasks.

Flow:
    1. User states a goal → `POST /api/agent/runs {goal}`.
    2. Backend asks the LLM (Claude Sonnet 4.5) to break it into concrete steps,
       constrained to the abilities the owner has enabled and the companion
       command kinds they actually have.
    3. Steps come back in `pending_approval` — the UI shows the plan and the
       user approves everything (or cancels).
    4. On approval, an asyncio background task walks the steps sequentially:
         - "companion" steps → queued into `companion_commands` and awaited via
           polling the same collection the desktop app already drains.
         - "notify" steps → informational only (no side effects; instantly done).
         - "summary" step (auto-appended) → LLM writes a final one-liner.
    5. Frontend polls `GET /api/agent/runs/{run_id}` to watch progress.

Design notes:
    - Sequential only. Simple > clever.
    - No branching / retries in v1. If a step fails the run halts.
    - The whole runbook lives in one `agent_runs` doc; no auxiliary collections.
    - Executor loops on the ORIGINAL user_id (no impersonation), and reads the
      command status from `companion_commands` — so cancellation the user makes
      from the Activity Log kills the run naturally.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import abilities as ab
from deps import EMERGENT_LLM_KEY, db, get_current_user
from services.model_runtime import complete_text

router = APIRouter(prefix="/agent", tags=["agent"])
log = logging.getLogger("agent")


# ---------------- Constants ----------------
# Companion command kinds we let the planner emit. Must match handlers in
# routers/companion.py and the companion desktop executor.
COMPANION_KINDS: dict[str, str] = {
    "open_url": "Open a URL/website in the default browser. payload={url:str}",
    "open_app": "Open a native app by name. payload={name:str}",
    "say": "Speak a short line aloud on the PC. payload={text:str}",
    "notify": "Show a desktop notification/toast. payload={title:str, message:str}",
    "media_key": "Send a media key. payload={action:'playpause'|'next'|'previous'|'mute'|'volume_up'|'volume_down'}",
    "set_volume": "Set the master volume 0-100. payload={level:int}",
    "power": "Power action. payload={action:'lock'|'sleep'|'shutdown'|'restart'}",
    "type_text": "Type text into the focused window. payload={text:str}",
    "clipboard_set": "Set the clipboard. payload={text:str}",
    "find_file": "Search common folders and optionally open. payload={query:str, open:bool}",
    "system_status": "Read CPU/RAM/disk/battery/GPU stats. payload={}",
    "creative_job": (
        "Sketch art/video/music on this PC then open a studio. "
        "payload={kind:'art'|'video'|'music'|'open', prompt:str, pinokio_url:str, studio_label:str}"
    ),
}

STEP_TIMEOUT_SEC = 45  # per-step wall clock; long enough for slow open_url on cold browsers


# ---------------- Helpers ----------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step_id() -> str:
    return f"stp_{uuid.uuid4().hex[:10]}"


def _run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def _public(run: dict) -> dict:
    """Strip Mongo _id and image blobs for API responses."""
    run = dict(run)
    run.pop("_id", None)
    return run


async def _companion_connected(user_id: str) -> bool:
    dev = await db.companion_devices.find_one(
        {"user_id": user_id, "revoked": False}, {"_id": 0, "device_id": 1}
    )
    return dev is not None


async def _plan_with_llm(
    user: dict,
    goal: str,
    enabled_ability_ids: set[str],
    has_companion: bool,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> list[dict]:
    """Ask Claude to produce a stepwise plan. Returns list of step dicts
    (missing step_ids/status — the caller fills those in)."""
    # Which kinds are usable? All if companion is connected, none otherwise.
    kinds_desc = "\n".join(f"- {k}: {v}" for k, v in COMPANION_KINDS.items()) if has_companion else "(no PC companion connected — only 'notify' steps allowed)"
    abilities_line = ", ".join(sorted(enabled_ability_ids)) or "(none enabled)"

    system = (
        "You are the planning brain for the owner's digital twin. The owner will state a goal. "
        "You produce a short, concrete, SEQUENTIAL plan of steps the twin can execute on the owner's own PC.\n\n"
        "Rules:\n"
        "- 1 to 6 steps. Fewer is better if the goal is simple.\n"
        "- Each step is either 'companion' (runs on the PC) or 'notify' (informational — you just tell the owner something).\n"
        "- Do NOT invent steps beyond what the owner asked. No 'ask for confirmation' meta-steps.\n"
        "- Every companion step MUST use one of the listed kinds and its exact payload schema.\n"
        "- URLs must be full https:// URLs. App names must be real desktop app names (Spotify, Notion, Chrome, VS Code…).\n"
        "- For 'power' actions like shutdown/restart, use a 'notify' step FIRST warning the owner. (lock/sleep are fine directly.)\n"
        "- Descriptions are single sentences, present-tense, natural voice (e.g. 'Open Spotify', not 'The twin will open Spotify').\n\n"
        f"Enabled abilities for this owner: {abilities_line}\n"
        f"Companion PC connected: {'yes' if has_companion else 'no'}\n\n"
        f"Available companion kinds:\n{kinds_desc}\n\n"
        "Respond with STRICT JSON only, no markdown:\n"
        '{"steps": [{"description": "<one sentence>", "kind": "companion"|"notify", '
        '"companion_kind": "<one of the kinds above OR null for notify>", '
        '"companion_payload": {<matches the kind\'s schema OR null for notify>}, '
        '"message": "<used only when kind=notify: what to tell the owner>"}]}'
    )

    text, _resolved = await complete_text(
        user["user_id"], "tools",
        session_id=f"plan_{uuid.uuid4().hex[:8]}",
        system_message=system,
        user_text=f"Goal from {user.get('name') or 'the owner'}: {goal}",
        provider_override=provider,
        model_override=model,
    )
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"): text.rfind("}") + 1]

    try:
        data = json.loads(text)
        raw_steps = data.get("steps") or []
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Planner returned invalid JSON: {exc!s}") from exc

    steps: list[dict] = []
    for i, s in enumerate(raw_steps[:6]):
        kind = s.get("kind")
        if kind not in ("companion", "notify"):
            continue
        step = {
            "step_id": _step_id(),
            "order": i,
            "description": str(s.get("description") or "").strip()[:220] or f"Step {i + 1}",
            "kind": kind,
            "companion_kind": None,
            "companion_payload": None,
            "message": None,
            "status": "pending",
            "result": None,
            "cmd_id": None,
            "started_at": None,
            "finished_at": None,
        }
        if kind == "companion":
            ck = s.get("companion_kind")
            if ck not in COMPANION_KINDS:
                # Skip malformed steps rather than fail the whole plan
                continue
            step["companion_kind"] = ck
            step["companion_payload"] = s.get("companion_payload") or {}
        else:  # notify
            step["message"] = str(s.get("message") or s.get("description") or "").strip()[:600]
        steps.append(step)

    if not steps:
        raise HTTPException(status_code=502, detail="Planner produced no runnable steps")
    return steps


# ---------------- Executor ----------------
async def _execute_run(run_id: str, user_id: str) -> None:
    """Background task: walk the run's steps sequentially. Idempotent — safe to
    re-invoke; already-done steps are skipped."""
    try:
        await db.agent_runs.update_one(
            {"run_id": run_id, "user_id": user_id},
            {"$set": {"status": "running", "updated_at": _now()}},
        )
        while True:
            run = await db.agent_runs.find_one({"run_id": run_id, "user_id": user_id}, {"_id": 0})
            if not run:
                return
            if run["status"] in ("cancelled", "completed", "failed"):
                return
            # Find next actionable step (approved & pending run)
            next_step = None
            for s in run["steps"]:
                if s["status"] == "approved":
                    next_step = s
                    break
                if s["status"] in ("rejected", "done", "skipped"):
                    continue
                if s["status"] == "failed":
                    # A failed step halts the run
                    await db.agent_runs.update_one(
                        {"run_id": run_id, "user_id": user_id},
                        {"$set": {"status": "failed", "completed_at": _now(), "updated_at": _now()}},
                    )
                    return
                if s["status"] == "pending":
                    # Waiting on approval — pause execution
                    return
                if s["status"] == "running":
                    # Something else is driving it — bail out (avoid double-drive)
                    return
            if next_step is None:
                # All steps have been resolved — mark completed
                await db.agent_runs.update_one(
                    {"run_id": run_id, "user_id": user_id},
                    {"$set": {"status": "completed", "completed_at": _now(), "updated_at": _now()}},
                )
                return
            await _run_single_step(run_id, user_id, next_step)
    except Exception as exc:  # noqa: BLE001
        log.exception("agent run %s crashed", run_id)
        await db.agent_runs.update_one(
            {"run_id": run_id, "user_id": user_id},
            {"$set": {"status": "failed", "completed_at": _now(), "updated_at": _now(),
                      "error": str(exc)[:500]}},
        )


async def _set_step(run_id: str, user_id: str, step_id: str, changes: dict) -> None:
    ops = {f"steps.$.{k}": v for k, v in changes.items()}
    ops["updated_at"] = _now()
    await db.agent_runs.update_one(
        {"run_id": run_id, "user_id": user_id, "steps.step_id": step_id},
        {"$set": ops},
    )


async def _run_single_step(run_id: str, user_id: str, step: dict) -> None:
    step_id = step["step_id"]
    await _set_step(run_id, user_id, step_id, {"status": "running", "started_at": _now()})

    if step["kind"] == "notify":
        # Informational: just mark done. The frontend renders `message` inline.
        await _set_step(run_id, user_id, step_id, {
            "status": "done",
            "result": step.get("message") or "",
            "finished_at": _now(),
        })
        return

    # companion step — queue a command and await result
    cmd_id = f"cmd_{uuid.uuid4().hex[:10]}"
    await db.companion_commands.insert_one({
        "cmd_id": cmd_id,
        "user_id": user_id,
        "kind": step["companion_kind"],
        "payload": step["companion_payload"] or {},
        "status": "queued",
        "result": None,
        "created_at": _now(),
        "completed_at": None,
        "agent_run_id": run_id,
        "agent_step_id": step_id,
    })
    await _set_step(run_id, user_id, step_id, {"cmd_id": cmd_id})

    # Poll for completion
    deadline = asyncio.get_event_loop().time() + STEP_TIMEOUT_SEC
    while asyncio.get_event_loop().time() < deadline:
        # If the whole run was cancelled, stop
        run_doc = await db.agent_runs.find_one({"run_id": run_id, "user_id": user_id}, {"_id": 0, "status": 1})
        if not run_doc or run_doc["status"] == "cancelled":
            await _set_step(run_id, user_id, step_id, {"status": "skipped", "finished_at": _now()})
            return
        cmd = await db.companion_commands.find_one({"cmd_id": cmd_id}, {"_id": 0, "status": 1, "result": 1})
        if not cmd:
            break
        st = cmd["status"]
        if st == "done":
            await _set_step(run_id, user_id, step_id, {
                "status": "done",
                "result": (cmd.get("result") or "")[:800],
                "finished_at": _now(),
            })
            return
        if st == "error":
            await _set_step(run_id, user_id, step_id, {
                "status": "failed",
                "result": (cmd.get("result") or "")[:800],
                "finished_at": _now(),
            })
            return
        if st == "cancelled":
            await _set_step(run_id, user_id, step_id, {"status": "skipped", "finished_at": _now()})
            return
        await asyncio.sleep(1.0)

    # Timed out — mark failed but leave the companion command alone (it may still
    # complete late; that's fine, it just won't affect the run).
    await _set_step(run_id, user_id, step_id, {
        "status": "failed",
        "result": "timed out waiting for the PC companion",
        "finished_at": _now(),
    })


def _schedule(run_id: str, user_id: str) -> None:
    """Kick off the executor without blocking the request."""
    asyncio.create_task(_execute_run(run_id, user_id))


# ---------------- API ----------------
class CreateRunReq(BaseModel):
    goal: str = Field(min_length=3, max_length=500)
    auto_approve: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None


@router.post("/runs")
async def create_run(payload: CreateRunReq, user: dict = Depends(get_current_user)):
    goal = payload.goal.strip()
    if not goal:
        raise HTTPException(status_code=400, detail="Goal is empty")
    enabled = await ab.enabled_ability_ids(user["user_id"])
    has_pc = await _companion_connected(user["user_id"])
    steps = await _plan_with_llm(
        user, goal, enabled, has_pc,
        provider=payload.provider, model=payload.model,
    )
    if payload.auto_approve:
        for s in steps:
            s["status"] = "approved"
    run = {
        "run_id": _run_id(),
        "user_id": user["user_id"],
        "goal": goal,
        "auto_approve": bool(payload.auto_approve),
        "status": "running" if payload.auto_approve else "pending_approval",
        "steps": steps,
        "created_at": _now(),
        "updated_at": _now(),
        "completed_at": None,
        "companion_connected_at_plan": has_pc,
        "enabled_abilities_at_plan": sorted(enabled),
    }
    await db.agent_runs.insert_one(run)
    if payload.auto_approve:
        _schedule(run["run_id"], user["user_id"])
    return _public(run)


class ApproveReq(BaseModel):
    step_ids: list[str] | None = None  # None → approve all pending


@router.post("/runs/{run_id}/approve")
async def approve(run_id: str, payload: ApproveReq, user: dict = Depends(get_current_user)):
    run = await db.agent_runs.find_one({"run_id": run_id, "user_id": user["user_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Run already {run['status']}")

    target = set(payload.step_ids or [])
    changed = 0
    for s in run["steps"]:
        if s["status"] == "pending" and (not target or s["step_id"] in target):
            s["status"] = "approved"
            changed += 1
    if not changed:
        raise HTTPException(status_code=400, detail="No pending steps to approve")

    run["status"] = "running"
    run["updated_at"] = _now()
    await db.agent_runs.replace_one({"run_id": run_id, "user_id": user["user_id"]}, run)
    _schedule(run_id, user["user_id"])
    return _public(run)


@router.post("/runs/{run_id}/steps/{step_id}/reject")
async def reject_step(run_id: str, step_id: str, user: dict = Depends(get_current_user)):
    run = await db.agent_runs.find_one({"run_id": run_id, "user_id": user["user_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Run already {run['status']}")
    hit = False
    for s in run["steps"]:
        if s["step_id"] == step_id:
            if s["status"] not in ("pending", "approved"):
                raise HTTPException(status_code=409, detail=f"Step already {s['status']}")
            s["status"] = "rejected"
            s["finished_at"] = _now()
            hit = True
            break
    if not hit:
        raise HTTPException(status_code=404, detail="Step not found")
    run["updated_at"] = _now()
    await db.agent_runs.replace_one({"run_id": run_id, "user_id": user["user_id"]}, run)
    return _public(run)


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str, user: dict = Depends(get_current_user)):
    run = await db.agent_runs.find_one({"run_id": run_id, "user_id": user["user_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] in ("completed", "failed", "cancelled"):
        return _public(run)
    # Cancel any queued/dispatched companion command tied to a running step so
    # the desktop app quietly drops it.
    for s in run["steps"]:
        if s.get("cmd_id") and s["status"] in ("running", "approved"):
            await db.companion_commands.update_one(
                {"cmd_id": s["cmd_id"], "user_id": user["user_id"], "status": {"$in": ["queued", "dispatched"]}},
                {"$set": {"status": "cancelled", "completed_at": _now()}},
            )
    await db.agent_runs.update_one(
        {"run_id": run_id, "user_id": user["user_id"]},
        {"$set": {"status": "cancelled", "completed_at": _now(), "updated_at": _now()}},
    )
    return {"ok": True, "run_id": run_id, "status": "cancelled"}


@router.get("/runs")
async def list_runs(user: dict = Depends(get_current_user), limit: int = 20):
    cursor = db.agent_runs.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).limit(min(limit, 50))
    return {"runs": await cursor.to_list(length=min(limit, 50))}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: dict = Depends(get_current_user)):
    run = await db.agent_runs.find_one({"run_id": run_id, "user_id": user["user_id"]}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _public(run)


@router.get("/kinds")
async def list_kinds(user: dict = Depends(get_current_user)):
    """Utility for the frontend: what a plan step might look like."""
    return {
        "companion_kinds": [{"kind": k, "description": v} for k, v in COMPANION_KINDS.items()],
        "companion_connected": await _companion_connected(user["user_id"]),
    }
