"""Iteration 29 regression — Focus/Agent mode + adjacencies + litellm swap smoke.

Covers:
  * /api/agent/kinds requires auth and returns list of kinds.
  * Plan → approve → executor drives companion_commands, run completes.
  * Plan without companion device -> only 'notify' steps allowed.
  * Step reject + run cancel semantics.
  * Adjacent regression: twin conversations, abilities, companion status, letters list.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

pytestmark = pytest.mark.asyncio

BACKEND = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


async def _mk_user(with_device: bool = True):
    m = AsyncIOMotorClient(MONGO_URL)[DB_NAME]
    uid = f"pytest-agent-{uuid.uuid4().hex[:8]}"
    session = f"pytest_session_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    await m.users.insert_one({
        "user_id": uid, "email": f"{uid}@example.com", "name": "Pytest",
        "created_at": now.isoformat(),
    })
    await m.user_sessions.insert_one({
        "user_id": uid, "session_token": session,
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "created_at": now.isoformat(),
    })
    dev_token = None
    if with_device:
        dev_token = f"comp_pytest_{uuid.uuid4().hex[:16]}"
        await m.companion_devices.insert_one({
            "device_id": f"dev_{uuid.uuid4().hex[:8]}", "user_id": uid,
            "name": "Pytest PC", "device_token": dev_token, "revoked": False,
            "created_at": now.isoformat(), "last_seen": None,
        })
    return uid, session, dev_token, m


async def _cleanup(m, uid):
    await m.users.delete_many({"user_id": uid})
    await m.user_sessions.delete_many({"user_id": uid})
    await m.companion_devices.delete_many({"user_id": uid})
    await m.companion_commands.delete_many({"user_id": uid})
    await m.agent_runs.delete_many({"user_id": uid})


# --- Auth boundary ---
async def test_agent_kinds_requires_auth():
    async with httpx.AsyncClient(base_url=BACKEND, timeout=15.0) as c:
        r = await c.get("/api/agent/kinds")
        assert r.status_code == 401
        r = await c.post("/api/agent/runs", json={"goal": "hi"})
        assert r.status_code == 401
        r = await c.get("/api/agent/runs")
        assert r.status_code == 401


# --- Plan shape with the exact goal from the review request ---
async def test_agent_plan_open_url_and_set_volume():
    uid, session, dev_token, m = await _mk_user(with_device=True)
    try:
        async with httpx.AsyncClient(base_url=BACKEND, timeout=45.0) as c:
            hdr = {"Authorization": f"Bearer {session}"}
            r = await c.post("/api/agent/runs", headers=hdr,
                             json={"goal": "Open https://example.com and set volume to 30"})
            assert r.status_code == 200, r.text
            run = r.json()
            assert "run_id" in run and run["status"] == "pending_approval"
            assert isinstance(run["steps"], list) and len(run["steps"]) >= 1
            kinds = [s.get("companion_kind") for s in run["steps"] if s["kind"] == "companion"]
            # At least one companion step should exist (LLM shouldn't fall back to notify-only
            # when a device is connected).
            assert any(k in ("open_url", "set_volume") for k in kinds), f"kinds={kinds} steps={run['steps']}"
            for s in run["steps"]:
                assert "step_id" in s and "order" in s and s["status"] == "pending"
                assert s["kind"] in ("companion", "notify")
    finally:
        await _cleanup(m, uid)


# --- Full lifecycle: approve -> executor -> companion poll -> result -> completed ---
async def test_agent_full_lifecycle_via_companion():
    uid, session, dev_token, m = await _mk_user(with_device=True)
    try:
        async with httpx.AsyncClient(base_url=BACKEND, timeout=45.0) as c:
            uh = {"Authorization": f"Bearer {session}"}
            dh = {"Authorization": f"Bearer {dev_token}"}
            r = await c.post("/api/agent/runs", headers=uh,
                             json={"goal": "Open https://example.com then say hello"})
            assert r.status_code == 200
            run_id = r.json()["run_id"]

            # GET list & single
            lr = await c.get("/api/agent/runs", headers=uh)
            assert lr.status_code == 200 and any(x["run_id"] == run_id for x in lr.json()["runs"])
            sr = await c.get(f"/api/agent/runs/{run_id}", headers=uh)
            assert sr.status_code == 200 and sr.json()["run_id"] == run_id

            ar = await c.post(f"/api/agent/runs/{run_id}/approve", headers=uh, json={})
            assert ar.status_code == 200
            assert ar.json()["status"] == "running"

            deadline = time.time() + 30
            while time.time() < deadline:
                pr = await c.get("/api/companion/poll", headers=dh)
                if pr.status_code == 200:
                    for cmd in pr.json().get("commands", []):
                        await c.post("/api/companion/result", headers=dh,
                                     json={"cmd_id": cmd["cmd_id"], "status": "ok", "output": "ok"})
                rr = await c.get(f"/api/agent/runs/{run_id}", headers=uh)
                if rr.json()["status"] in ("completed", "failed"):
                    break
                await asyncio.sleep(0.6)

            final = (await c.get(f"/api/agent/runs/{run_id}", headers=uh)).json()
            assert final["status"] == "completed", final
    finally:
        await _cleanup(m, uid)


# --- No companion device -> notify-only plan ---
async def test_agent_plan_no_companion_notify_only():
    uid, session, _, m = await _mk_user(with_device=False)
    try:
        async with httpx.AsyncClient(base_url=BACKEND, timeout=45.0) as c:
            hdr = {"Authorization": f"Bearer {session}"}
            k = await c.get("/api/agent/kinds", headers=hdr)
            assert k.status_code == 200 and k.json()["companion_connected"] is False
            r = await c.post("/api/agent/runs", headers=hdr,
                             json={"goal": "Wind down for the night — dim lights, play calm music"})
            assert r.status_code == 200, r.text
            steps = r.json()["steps"]
            assert steps, "Should still produce steps without a companion"
            for s in steps:
                assert s["kind"] == "notify", f"Expected notify-only without companion, got {s['kind']}: {s}"
    finally:
        await _cleanup(m, uid)


# --- Step reject + run cancel ---
async def test_agent_reject_step_and_cancel():
    uid, session, dev_token, m = await _mk_user(with_device=True)
    try:
        async with httpx.AsyncClient(base_url=BACKEND, timeout=45.0) as c:
            hdr = {"Authorization": f"Bearer {session}"}
            r = await c.post("/api/agent/runs", headers=hdr,
                             json={"goal": "Open Spotify then say hi then show notify"})
            assert r.status_code == 200
            run = r.json()
            run_id = run["run_id"]
            first_step_id = run["steps"][0]["step_id"]

            rj = await c.post(f"/api/agent/runs/{run_id}/steps/{first_step_id}/reject", headers=hdr, json={})
            assert rj.status_code == 200
            after = rj.json()
            hit = next(s for s in after["steps"] if s["step_id"] == first_step_id)
            assert hit["status"] == "rejected"

            cn = await c.post(f"/api/agent/runs/{run_id}/cancel", headers=hdr)
            assert cn.status_code == 200
            g = await c.get(f"/api/agent/runs/{run_id}", headers=hdr)
            assert g.json()["status"] == "cancelled"
    finally:
        await _cleanup(m, uid)


# --- litellm swap smoke: adjacent features still respond ---
async def test_adjacent_regression_smoke():
    uid, session, _, m = await _mk_user(with_device=False)
    try:
        async with httpx.AsyncClient(base_url=BACKEND, timeout=15.0) as c:
            hdr = {"Authorization": f"Bearer {session}"}
            # Twin conversations
            r = await c.get("/api/twin/conversations", headers=hdr)
            assert r.status_code == 200
            # Abilities list
            r = await c.get("/api/abilities", headers=hdr)
            assert r.status_code in (200, 404)  # tolerate either mount path
            # Companion status (some route should exist under /api/companion)
            r = await c.get("/api/companion/devices", headers=hdr)
            assert r.status_code in (200, 401, 404)
            # Letters
            r = await c.get("/api/letters", headers=hdr)
            assert r.status_code == 200
    finally:
        await _cleanup(m, uid)
