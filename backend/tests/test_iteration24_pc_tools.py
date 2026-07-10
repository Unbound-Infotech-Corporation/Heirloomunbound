"""Regression tests for the Twin's PC-control tools (iteration 24).

Runs the whole suite inside ONE event loop (motor binds to the first loop it
sees, so we avoid multiple asyncio.run() calls). Simulates a connected
companion PC with a background task that marks queued commands done and, for
`screenshot`, inserts a companion_screens doc — exercising the full
queue → execute → result round-trip that twin_tools relies on.
"""
import asyncio
import base64
import io

from datetime import datetime, timezone

from PIL import Image, ImageDraw

from deps import db
import twin_tools as t

UID = "pytest-pc-user"


async def _make_awake_device():
    await db.companion_devices.update_one(
        {"user_id": UID},
        {"$set": {
            "device_id": "dev_pytest", "user_id": UID, "name": "Pytest PC",
            "device_token": "comp_pytest", "revoked": False,
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


async def _fake_companion(stop: asyncio.Event, screenshot_b64=None):
    while not stop.is_set():
        async for cmd in db.companion_commands.find({"user_id": UID, "status": "queued"}):
            kind = cmd["kind"]
            if kind == "screenshot":
                if screenshot_b64:
                    await db.companion_screens.update_one(
                        {"cmd_id": cmd["cmd_id"]},
                        {"$set": {"cmd_id": cmd["cmd_id"], "user_id": UID, "image_b64": screenshot_b64,
                                  "mime": "image/jpeg", "created_at": datetime.now(timezone.utc).isoformat()}},
                        upsert=True,
                    )
                await db.companion_commands.update_one({"cmd_id": cmd["cmd_id"]}, {"$set": {"status": "done", "result": "captured"}})
                continue
            result = "ok"
            if kind == "clipboard_get":
                result = "sample clipboard text"
            elif kind == "system_status":
                result = "CPU: 10%\nGPU: RTX 5090 — 5% util"
            elif kind == "find_file":
                result = "Found:\n- /home/me/Desktop/taxes.pdf"
            await db.companion_commands.update_one(
                {"cmd_id": cmd["cmd_id"]},
                {"$set": {"status": "done", "result": result, "completed_at": datetime.now(timezone.utc).isoformat()}},
            )
        await asyncio.sleep(0.2)


async def _run(name, args, screenshot_b64=None):
    await _make_awake_device()
    stop = asyncio.Event()
    fc = asyncio.create_task(_fake_companion(stop, screenshot_b64))
    try:
        return await t.execute_tool(name, UID, args)
    finally:
        stop.set()
        await fc


def _make_error_screen_b64():
    img = Image.new("RGB", (600, 300), (18, 22, 38))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, 560, 120], fill=(200, 60, 60))
    d.text((60, 70), "ERROR 500: Server crashed", fill=(255, 255, 255))
    d.ellipse([60, 200, 220, 260], fill=(60, 160, 90))
    d.text((95, 225), "RETRY", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


async def _suite():
    await db.companion_commands.delete_many({"user_id": UID})
    await db.companion_screens.delete_many({"user_id": UID})
    await db.companion_devices.delete_many({"user_id": UID})

    # 1) No device → friendly note
    r = await t.execute_tool("open_on_pc", UID, {"target": "Spotify"})
    assert r["ui"].get("reason") == "no_device", r

    # 2) open app
    r = await _run("open_on_pc", {"target": "Spotify"})
    assert r["ui"]["ok"] is True, r

    # 3) open website → queues open_url with https
    await _run("open_on_pc", {"target": "youtube.com"})
    cmd = await db.companion_commands.find_one({"user_id": UID, "kind": "open_url"})
    assert cmd and cmd["payload"]["url"].startswith("https://"), cmd

    # 4) media + absolute volume
    r1 = await _run("control_media", {"action": "playpause"})
    r2 = await _run("set_volume", {"level": 42})
    assert r1["ui"]["ok"] and r2["ui"]["ok"]
    cmd = await db.companion_commands.find_one({"user_id": UID, "kind": "set_volume"})
    assert cmd["payload"]["level"] == 42

    # 5) shutdown needs confirm, not queued
    r = await _run("power_action", {"action": "shutdown"})
    assert r["ui"].get("needs_confirm") is True
    assert await db.companion_commands.find_one({"user_id": UID, "kind": "power"}) is None

    # 6) lock runs without confirm
    r = await _run("power_action", {"action": "lock"})
    assert r["ui"]["ok"] is True

    # 7) run_command gated then runs
    r = await _run("run_command", {"command": "echo hi"})
    assert r["ui"].get("needs_confirm") is True
    r2 = await _run("run_command", {"command": "echo hi", "confirmed": True})
    assert r2["ui"]["ok"] is True

    # 8) clipboard get, status, find_file
    r1 = await _run("clipboard", {"mode": "get"})
    r2 = await _run("system_status", {})
    r3 = await _run("find_file", {"query": "tax"})
    assert "sample clipboard text" in r1["summary"]
    assert "RTX 5090" in r2["summary"]
    assert "taxes.pdf" in r3["summary"]

    # 9) see_screen vision + cleanup
    r = await _run("see_screen", {"question": "What does the screen say?"}, screenshot_b64=_make_error_screen_b64())
    assert r["ui"]["ok"] is True, r
    assert ("error" in r["summary"].lower()) or ("500" in r["summary"])
    assert await db.companion_screens.find_one({"user_id": UID}) is None

    # cleanup
    await db.companion_commands.delete_many({"user_id": UID})
    await db.companion_devices.delete_many({"user_id": UID})


def test_pc_control_tools_full_round_trip():
    asyncio.run(_suite())
