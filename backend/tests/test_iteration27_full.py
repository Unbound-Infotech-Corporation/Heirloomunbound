"""Iteration 27 — Activity Log + Photo→Story E2E backend checks.

Runs against the live app using the fork23 session/device from
/app/memory/test_credentials.md.
"""
import io
import os

import pytest
import requests

def _load_backend_url():
    for p in ("/app/frontend/.env",):
        try:
            for line in open(p):
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
        except OSError:
            pass
    return os.environ["REACT_APP_BACKEND_URL"].rstrip("/")

BASE = _load_backend_url()
SESSION = "test_session_fork23"
DEVICE = "comp_test"
USER_HDR = {"Authorization": f"Bearer {SESSION}"}
DEV_HDR = {"Authorization": f"Bearer {DEVICE}"}


# ---------- Activity Log ----------

def _queue(kind, payload):
    r = requests.post(f"{BASE}/api/companion/queue-command",
                      json={"kind": kind, "payload": payload}, headers=USER_HDR, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["cmd_id"]


def test_activity_feed_redacts_type_text_and_clipboard():
    cmd_type = _queue("type_text", {"text": "SUPER SECRET PASSWORD 12345"})
    cmd_clip = _queue("clipboard_set", {"text": "another secret string"})
    cmd_url = _queue("open_url", {"url": "https://example.com/hello"})

    r = requests.get(f"{BASE}/api/companion/activity?limit=50", headers=USER_HDR, timeout=15)
    assert r.status_code == 200
    items = {i["cmd_id"]: i for i in r.json()["items"]}

    t = items[cmd_type]
    assert t["kind"] == "type_text"
    assert t["label"] == "Typed text"
    assert "SECRET" not in t["summary"] and "PASSWORD" not in t["summary"]
    assert t["summary"].endswith("characters")
    assert t["status"] == "queued"
    assert t["cancellable"] is True

    c = items[cmd_clip]
    assert "secret" not in c["summary"].lower()
    assert "clipboard" in c["summary"].lower()

    u = items[cmd_url]
    assert u["summary"] == "https://example.com/hello"


def test_cancel_lifecycle_and_result_ignored():
    cmd = _queue("open_url", {"url": "https://cancel.test"})
    r1 = requests.post(f"{BASE}/api/companion/activity/{cmd}/cancel", headers=USER_HDR, timeout=10)
    assert r1.status_code == 200
    assert r1.json()["status"] == "cancelled"

    # already cancelled -> 409
    r2 = requests.post(f"{BASE}/api/companion/activity/{cmd}/cancel", headers=USER_HDR, timeout=10)
    assert r2.status_code == 409

    # non-existent -> 404
    r3 = requests.post(f"{BASE}/api/companion/activity/cmd_doesnotexist/cancel",
                       headers=USER_HDR, timeout=10)
    assert r3.status_code == 404

    # device posting result must NOT resurrect a cancelled cmd
    rr = requests.post(f"{BASE}/api/companion/result",
                       json={"cmd_id": cmd, "status": "ok", "result": "should be ignored"},
                       headers=DEV_HDR, timeout=10)
    assert rr.status_code in (200, 202), rr.text

    # verify still cancelled
    r4 = requests.get(f"{BASE}/api/companion/activity?limit=50", headers=USER_HDR, timeout=10)
    row = next(i for i in r4.json()["items"] if i["cmd_id"] == cmd)
    assert row["status"] == "cancelled"


# ---------- Photo → Story ----------

def _real_jpeg_bytes() -> bytes:
    """Build a JPEG with real visual features (shapes, edges, gradient)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (640, 480), (30, 60, 120))
    d = ImageDraw.Draw(img)
    # gradient bg
    for y in range(480):
        d.line([(0, y), (640, y)], fill=(30 + y // 4, 60 + y // 6, 120 - y // 8))
    # a sun
    d.ellipse([(430, 60), (580, 210)], fill=(250, 220, 90), outline=(240, 160, 20), width=4)
    # ground
    d.rectangle([(0, 340), (640, 480)], fill=(60, 130, 60))
    # a house
    d.rectangle([(120, 240), (300, 380)], fill=(200, 180, 140), outline=(80, 50, 30), width=3)
    d.polygon([(110, 240), (210, 160), (310, 240)], fill=(160, 60, 40))
    d.rectangle([(190, 300), (240, 380)], fill=(90, 55, 30))
    # a tree
    d.rectangle([(430, 300), (455, 380)], fill=(90, 55, 30))
    d.ellipse([(390, 240), (500, 340)], fill=(40, 110, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


@pytest.fixture(scope="module")
def photo_story_id():
    jpeg = _real_jpeg_bytes()
    r = requests.post(
        f"{BASE}/api/photo-story/start",
        files={"file": ("scene.jpg", jpeg, "image/jpeg")},
        headers=USER_HDR,
        timeout=90,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["photo_story_id"].startswith("ps_")
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert isinstance(data["questions"], list) and len(data["questions"]) == 3
    assert data["image_url"].endswith(f"/{data['photo_story_id']}/image")
    return data["photo_story_id"]


def test_photo_story_image_endpoint(photo_story_id):
    r = requests.get(f"{BASE}/api/photo-story/{photo_story_id}/image",
                     headers=USER_HDR, timeout=15)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert len(r.content) > 1000
    # JPEG magic
    assert r.content[:3] == b"\xff\xd8\xff"


def test_photo_story_compose_and_archive(photo_story_id):
    r = requests.post(
        f"{BASE}/api/photo-story/{photo_story_id}/compose",
        json={"answers": [
            "This is our first house — my wife and I moved in the summer of 2011.",
            "That's the maple we planted the week we arrived.",
            "It felt like standing inside a promise we'd made to each other.",
        ]},
        headers=USER_HDR,
        timeout=120,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["entry_id"].startswith("ent_")
    assert data["title"]
    assert len(data["content"]) > 50

    # Archive should include this entry as story/photo_story
    a = requests.get(f"{BASE}/api/archive?limit=100", headers=USER_HDR, timeout=15)
    assert a.status_code == 200
    entries = a.json() if isinstance(a.json(), list) else a.json().get("entries", a.json().get("items", []))
    matches = [e for e in entries if e.get("entry_id") == data["entry_id"]]
    assert matches, f"entry {data['entry_id']} not in /api/archive"
    e = matches[0]
    assert e["type"] == "story"
    assert e["source"] == "photo_story"
