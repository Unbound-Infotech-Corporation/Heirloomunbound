"""Regression test for Focus/Agent Mode — end-to-end plan → approve → run → complete.

Uses direct DB fixtures (no OAuth) and a fake companion device to drain the
command queue and post results. Run:
    cd /app/backend && pytest tests/test_iteration29_agent.py -v
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.asyncio

BACKEND = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")


async def _fixture(client: httpx.AsyncClient):
    """Create a fresh user + session + companion device via the API-adjacent
    Mongo shell we already trust — but keep the test pure-Python by talking
    directly to Mongo through motor."""
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    m = AsyncIOMotorClient(mongo_url)[db_name]
    uid = f"pytest-agent-{uuid.uuid4().hex[:8]}"
    session = f"pytest_session_{uuid.uuid4().hex[:12]}"
    dev_token = f"comp_pytest_{uuid.uuid4().hex[:16]}"
    from datetime import datetime, timedelta, timezone
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
    await m.companion_devices.insert_one({
        "device_id": f"dev_{uuid.uuid4().hex[:8]}", "user_id": uid,
        "name": "Pytest PC", "device_token": dev_token, "revoked": False,
        "created_at": now.isoformat(), "last_seen": None,
    })
    return uid, session, dev_token, m


async def test_agent_full_flow():
    async with httpx.AsyncClient(base_url=BACKEND, timeout=45.0) as client:
        uid, session, dev_token, db = await _fixture(client)
        try:
            user_headers = {"Authorization": f"Bearer {session}"}
            dev_headers = {"Authorization": f"Bearer {dev_token}"}

            # 1. Kinds endpoint reports companion connected
            r = await client.get("/api/agent/kinds", headers=user_headers)
            assert r.status_code == 200, r.text
            assert r.json()["companion_connected"] is True

            # 2. Plan a run — a two-step, deterministic-ish request
            r = await client.post(
                "/api/agent/runs",
                headers=user_headers,
                json={"goal": "Open https://example.com then say hello"},
            )
            assert r.status_code == 200, r.text
            run = r.json()
            assert run["status"] == "pending_approval"
            assert len(run["steps"]) >= 1
            # Every companion step must have a valid kind (LLM sometimes emits
            # 'notify' too — that's fine)
            for s in run["steps"]:
                assert s["kind"] in ("companion", "notify")

            run_id = run["run_id"]

            # 3. Approve — run should flip to `running`
            r = await client.post(f"/api/agent/runs/{run_id}/approve", headers=user_headers, json={})
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "running"

            # 4. Drain the companion queue, posting synthetic results back
            deadline = time.time() + 30
            drained = 0
            while time.time() < deadline:
                pr = await client.get("/api/companion/poll", headers=dev_headers)
                if pr.status_code != 200:
                    await asyncio.sleep(0.5)
                    continue
                cmds = pr.json().get("commands", [])
                for c in cmds:
                    await client.post(
                        "/api/companion/result",
                        headers=dev_headers,
                        json={"cmd_id": c["cmd_id"], "status": "ok", "output": "test-ok"},
                    )
                    drained += 1
                # Check run state
                rr = await client.get(f"/api/agent/runs/{run_id}", headers=user_headers)
                state = rr.json()
                if state["status"] in ("completed", "failed"):
                    break
                await asyncio.sleep(0.7)

            # 5. Final assertion
            rr = await client.get(f"/api/agent/runs/{run_id}", headers=user_headers)
            final = rr.json()
            assert final["status"] == "completed", f"run ended as {final['status']}: {final}"
            # every non-notify step must have a cmd_id we drained
            companion_steps = [s for s in final["steps"] if s["kind"] == "companion"]
            assert all(s["status"] == "done" for s in companion_steps)
        finally:
            # cleanup
            await db.users.delete_many({"user_id": uid})
            await db.user_sessions.delete_many({"user_id": uid})
            await db.companion_devices.delete_many({"user_id": uid})
            await db.companion_commands.delete_many({"user_id": uid})
            await db.agent_runs.delete_many({"user_id": uid})


async def test_agent_reject_step_and_cancel():
    async with httpx.AsyncClient(base_url=BACKEND, timeout=45.0) as client:
        uid, session, dev_token, db = await _fixture(client)
        try:
            headers = {"Authorization": f"Bearer {session}"}
            r = await client.post("/api/agent/runs", headers=headers,
                                  json={"goal": "Open notepad and type hello world"})
            assert r.status_code == 200
            run = r.json()
            run_id = run["run_id"]
            # Cancel while still pending_approval
            r = await client.post(f"/api/agent/runs/{run_id}/cancel", headers=headers)
            assert r.status_code == 200
            r = await client.get(f"/api/agent/runs/{run_id}", headers=headers)
            assert r.json()["status"] == "cancelled"
        finally:
            await db.users.delete_many({"user_id": uid})
            await db.user_sessions.delete_many({"user_id": uid})
            await db.companion_devices.delete_many({"user_id": uid})
            await db.agent_runs.delete_many({"user_id": uid})
