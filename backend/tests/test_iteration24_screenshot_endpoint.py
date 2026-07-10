"""Test /api/companion/screenshot device-auth endpoint."""
import io
import os
import uuid
import asyncio
import requests
from PIL import Image
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timezone

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


def _setup_device():
    async def _run():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        device_token = "test_dev_tok_" + uuid.uuid4().hex[:12]
        user_id = "test-user-fork23"
        cmd_id = "cmd_" + uuid.uuid4().hex[:10]
        await db.companion_devices.insert_one({
            "device_id": "dev_" + uuid.uuid4().hex[:10],
            "device_token": device_token,
            "user_id": user_id,
            "name": "TEST PC",
            "revoked": False,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.companion_commands.insert_one({
            "cmd_id": cmd_id,
            "user_id": user_id,
            "kind": "screenshot",
            "status": "pending",
            "args": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return device_token, cmd_id, user_id
    return asyncio.get_event_loop().run_until_complete(_run())


def _fetch_state(cmd_id):
    async def _run():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        screen = await db.companion_screens.find_one({"cmd_id": cmd_id}, {"_id": 0})
        cmd = await db.companion_commands.find_one({"cmd_id": cmd_id}, {"_id": 0})
        return screen, cmd
    return asyncio.get_event_loop().run_until_complete(_run())


def _cleanup(cmd_id, device_token):
    async def _run():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        await db.companion_screens.delete_many({"cmd_id": cmd_id})
        await db.companion_commands.delete_many({"cmd_id": cmd_id})
        await db.companion_devices.delete_many({"device_token": device_token})
    asyncio.get_event_loop().run_until_complete(_run())


def test_companion_screenshot_upload():
    device_token, cmd_id, user_id = _setup_device()
    try:
        # Build a small JPEG in-memory
        img = Image.new("RGB", (640, 400), color=(200, 20, 20))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60)
        buf.seek(0)

        r = requests.post(
            f"{BASE_URL}/api/companion/screenshot",
            headers={"Authorization": f"Bearer {device_token}"},
            data={"cmd_id": cmd_id},
            files={"file": ("shot.jpg", buf.getvalue(), "image/jpeg")},
            timeout=30,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        assert r.json().get("ok") is True

        screen, cmd = _fetch_state(cmd_id)
        assert screen is not None, "companion_screens doc not created"
        assert screen["cmd_id"] == cmd_id
        assert screen["user_id"] == user_id
        assert len(screen["image_b64"]) > 100
        assert cmd["status"] == "done"
    finally:
        _cleanup(cmd_id, device_token)


def test_companion_screenshot_requires_auth():
    r = requests.post(
        f"{BASE_URL}/api/companion/screenshot",
        data={"cmd_id": "nope"},
        files={"file": ("x.jpg", b"xx", "image/jpeg")},
        timeout=10,
    )
    assert r.status_code in (401, 403), f"expected auth failure, got {r.status_code}"
