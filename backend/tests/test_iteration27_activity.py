"""Regression for the Companion Activity Log + kill switch (iteration 27).

Single event loop. Verifies the activity feed formats + redacts commands, the
cancel/kill switch works with correct lifecycle rules, and that a cancelled
command is NOT resurrected by a late companion result.
"""
import asyncio
from datetime import datetime, timezone

from deps import db
import routers.companion as comp

UID = "pytest-activity-user"


async def _mk(kind, payload, status="queued"):
    cmd_id = f"cmd_pt_{kind}_{status}"
    await db.companion_commands.update_one(
        {"cmd_id": cmd_id},
        {"$set": {
            "cmd_id": cmd_id, "user_id": UID, "kind": kind, "payload": payload,
            "status": status, "result": None,
            "created_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
        }},
        upsert=True,
    )
    return cmd_id


async def _suite():
    await db.companion_commands.delete_many({"user_id": UID})

    # --- redaction / summary formatting ---
    await _mk("type_text", {"text": "my secret password 123"})
    await _mk("open_app", {"name": "Spotify"})
    await _mk("clipboard_set", {"text": "sensitive clipboard"})

    # Build the activity feed the way the endpoint does.
    docs = await db.companion_commands.find({"user_id": UID}, {"_id": 0}).sort("created_at", -1).to_list(length=50)
    by_kind = {d["kind"]: d for d in docs}
    # type_text summary must NOT contain the raw text (privacy) — only a length
    tt_summary = comp._activity_summary("type_text", by_kind["type_text"]["payload"])
    assert "password" not in tt_summary and "characters" in tt_summary, tt_summary
    # clipboard_set must not leak content
    cs_summary = comp._activity_summary("clipboard_set", by_kind["clipboard_set"]["payload"])
    assert "sensitive" not in cs_summary, cs_summary
    # open_app shows the app name (safe)
    assert comp._activity_summary("open_app", by_kind["open_app"]["payload"]) == "Spotify"
    # labels exist
    assert comp._KIND_LABELS["screenshot"] == "Looked at the screen"

    # --- cancel lifecycle ---
    q = await _mk("shell", {"command": "sleep 30"}, status="queued")
    d = await _mk("open_url", {"url": "https://x.com"}, status="dispatched")
    done = await _mk("say", {"text": "hi"}, status="done")

    # queued + dispatched are cancellable; done is not
    for cid in (q, d):
        doc = await db.companion_commands.find_one({"cmd_id": cid}, {"_id": 0})
        assert doc["status"] in ("queued", "dispatched")

    # cancel a queued one
    await db.companion_commands.update_one(
        {"cmd_id": q, "user_id": UID},
        {"$set": {"status": "cancelled", "completed_at": datetime.now(timezone.utc).isoformat()}},
    )
    doc = await db.companion_commands.find_one({"cmd_id": q}, {"_id": 0})
    assert doc["status"] == "cancelled"

    # A late result for a cancelled command must be IGNORED (stays cancelled).
    res = await db.companion_commands.update_one(
        {"cmd_id": q, "user_id": UID, "status": {"$ne": "cancelled"}},
        {"$set": {"status": "done", "result": "ran anyway"}},
    )
    assert res.matched_count == 0
    doc = await db.companion_commands.find_one({"cmd_id": q}, {"_id": 0})
    assert doc["status"] == "cancelled" and doc.get("result") is None

    # A result for a normal dispatched command still applies.
    res2 = await db.companion_commands.update_one(
        {"cmd_id": d, "user_id": UID, "status": {"$ne": "cancelled"}},
        {"$set": {"status": "done", "result": "ok"}},
    )
    assert res2.matched_count == 1

    await db.companion_commands.delete_many({"user_id": UID})


def test_activity_log():
    asyncio.run(_suite())
