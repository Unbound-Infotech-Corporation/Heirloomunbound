"""Iteration 23 — Twin heuristic refinement + Avatar Studio (upload/me/serve/use/enhance).

Verifies:
- POST /api/twin/message with open-ended/greeting produces 0 tool events
- POST /api/twin/message with a specific factual owner-past question fires search_archive
- POST /api/twin/start with an existing conversation_id returns that same conversation (persistence path)
- Avatar Studio: upload → /me → serve_url (public) → /use
- Avatar Studio: /enhance returns clean HTTP 400 JSON (no Cloudflare 502) with fal.ai balance error
"""
import io
import json
import os
import time
import uuid

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"].strip('"').strip("'")
DB_NAME = os.environ["DB_NAME"].strip('"').strip("'")


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def user_ctx(db):
    uid = f"test-user-iter23-{uuid.uuid4().hex[:10]}"
    token = f"test_session_iter23_{uuid.uuid4().hex[:12]}"
    db.users.insert_one({
        "user_id": uid,
        "email": f"iter23.{uid}@example.com",
        "name": "Iter23 Test",
        "picture": "https://via.placeholder.com/150",
        "setup_complete": True,
        "onboarded": True,
        "tour_completed": True,
    })
    from datetime import datetime
    db.user_sessions.insert_one({
        "user_id": uid,
        "session_token": token,
        "expires_at": datetime(2099, 1, 1),
    })
    yield {"user_id": uid, "token": token}
    db.users.delete_one({"user_id": uid})
    db.user_sessions.delete_many({"user_id": uid})
    db.conversations.delete_many({"user_id": uid})
    db.entries.delete_many({"user_id": uid})
    db.avatar_sources.delete_many({"user_id": uid})


@pytest.fixture(scope="module")
def headers(user_ctx):
    return {"Authorization": f"Bearer {user_ctx['token']}"}


def _stream_twin(headers, conv_id, message, timeout=90):
    r = requests.post(
        f"{BASE_URL}/api/twin/message",
        json={"conversation_id": conv_id, "message": message},
        headers={**headers, "Content-Type": "application/json"},
        stream=True,
        timeout=timeout,
    )
    assert r.status_code == 200, f"status={r.status_code}, body={r.text[:400]}"
    tool_events, text_deltas = [], []
    done = False
    buf = ""
    start = time.time()
    for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
        if not chunk:
            continue
        buf += chunk
        while "\n\n" in buf:
            frame, buf = buf.split("\n\n", 1)
            ev = "message"
            data = ""
            for ln in frame.split("\n"):
                if ln.startswith("event:"):
                    ev = ln[len("event:"):].strip()
                elif ln.startswith("data:"):
                    data += ln[len("data:"):].strip()
            try:
                payload = json.loads(data) if data else {}
            except json.JSONDecodeError:
                payload = {"raw": data}
            if ev == "tool":
                tool_events.append(payload)
            elif ev == "done":
                done = True
            elif ev == "error":
                raise RuntimeError(f"SSE error: {payload}")
            elif "text" in payload:
                text_deltas.append(payload["text"])
        if done:
            break
        if time.time() - start > timeout:
            break
    return {"tools": tool_events, "texts": text_deltas, "done": done, "elapsed": time.time() - start}


# ============ Twin heuristic refinement ============

class TestTwinHeuristic:
    def _fresh_conv(self, headers):
        r = requests.post(f"{BASE_URL}/api/twin/start", json={}, headers={**headers, "Content-Type": "application/json"}, timeout=15)
        assert r.status_code == 200
        return r.json()["conversation_id"]

    def test_open_ended_opinion_no_tools(self, headers):
        conv = self._fresh_conv(headers)
        res = _stream_twin(headers, conv, "what do you think about life?")
        assert res["done"], "stream did not complete"
        tool_names = [t.get("name") for t in res["tools"]]
        assert not res["tools"], f"open-ended opinion should NOT fire tools; got={tool_names}"
        assert res["texts"], "no reply text"

    def test_greeting_no_tools(self, headers):
        conv = self._fresh_conv(headers)
        res = _stream_twin(headers, conv, "hi, how are you?")
        assert res["done"]
        assert not res["tools"], f"greeting should NOT fire tools; got={[t.get('name') for t in res['tools']]}"

    def test_specific_factual_owner_past_triggers_search(self, headers, db, user_ctx):
        # Deliberately DO NOT seed archive — empty archive_blob forces the model
        # to call search_archive to answer a factual owner-past question.
        conv = self._fresh_conv(headers)
        res = _stream_twin(headers, conv, "where did you grow up and what was your first job?")
        assert res["done"]
        srch = [t for t in res["tools"] if t.get("name") == "search_archive"]
        assert srch, f"search_archive should fire for a specific factual owner-past q; got={[t.get('name') for t in res['tools']]}"

    def test_twin_start_returns_same_conv_when_id_passed(self, headers):
        conv = self._fresh_conv(headers)
        # Now pass conversation_id back; should return the same one
        r = requests.post(
            f"{BASE_URL}/api/twin/start",
            json={"conversation_id": conv},
            headers={**headers, "Content-Type": "application/json"},
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json()["conversation_id"] == conv, "start with existing id must return same conv (persistence path)"


# ============ Avatar Studio ============

def _tiny_jpeg_bytes():
    # 8x8 white JPEG via PIL (valid, small)
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(buf, format="JPEG")
    return buf.getvalue()


class TestAvatarStudio:
    image_id = None  # class-level cache for chaining tests

    def test_upload_front(self, headers, user_ctx):
        files = {"file": ("front.jpg", io.BytesIO(_tiny_jpeg_bytes()), "image/jpeg")}
        r = requests.post(
            f"{BASE_URL}/api/avatar-studio/upload",
            files=files,
            data={"angle": "front"},
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200, f"upload failed: {r.status_code} {r.text[:400]}"
        j = r.json()
        assert j.get("angle") == "front"
        assert j.get("image_id"), f"no image_id: {j}"
        assert j.get("serve_url"), f"no serve_url in response: {j}"
        TestAvatarStudio.image_id = j["image_id"]

    def test_me_returns_uploaded(self, headers):
        r = requests.get(f"{BASE_URL}/api/avatar-studio/me", headers=headers, timeout=15)
        assert r.status_code == 200
        j = r.json()
        front = j.get("front")
        assert front, f"no 'front' angle present in /me: {j}"
        assert front.get("serve_url"), f"front has no serve_url: {front}"
        assert front.get("image_id"), f"front has no image_id: {front}"

    def test_serve_url_returns_image_bytes(self, headers):
        j = requests.get(f"{BASE_URL}/api/avatar-studio/me", headers=headers, timeout=15).json()
        front = j.get("front")
        serve_url = front["serve_url"]
        if serve_url.startswith("/"):
            serve_url = BASE_URL + serve_url
        # public endpoint — no auth header needed (token-gated via ?t=)
        r2 = requests.get(serve_url, timeout=15)
        assert r2.status_code == 200, f"serve_url did not return 200: {r2.status_code} {r2.text[:200]}"
        assert r2.content[:2] == b"\xff\xd8", f"not a JPEG (magic mismatch): {r2.content[:8]!r}"

    def test_use_sets_active(self, headers):
        # image_id from earlier upload
        j = requests.get(f"{BASE_URL}/api/avatar-studio/me", headers=headers, timeout=15).json()
        img_id = j["front"]["image_id"]
        r = requests.post(
            f"{BASE_URL}/api/avatar-studio/use",
            json={"image_id": img_id},
            headers={**headers, "Content-Type": "application/json"},
            timeout=15,
        )
        assert r.status_code == 200, f"use failed: {r.status_code} {r.text[:400]}"
        me = requests.get(f"{BASE_URL}/api/avatar-studio/me", headers=headers, timeout=15).json()
        assert me.get("active_source_url"), f"active_source_url not set after /use: {me}"

    def test_enhance_returns_clean_400_with_fal_detail(self, headers):
        j = requests.get(f"{BASE_URL}/api/avatar-studio/me", headers=headers, timeout=15).json()
        img_id = j["front"]["image_id"]
        r = requests.post(
            f"{BASE_URL}/api/avatar-studio/enhance",
            json={"image_id": img_id},
            headers={**headers, "Content-Type": "application/json"},
            timeout=90,
        )
        # Expected clean 400 with fal balance error. 200 is also OK if fal balance somehow returned.
        assert r.status_code in (200, 400), f"expected 200 or 400 (NOT Cloudflare 502 HTML), got {r.status_code}: {r.text[:300]}"
        if r.status_code == 400:
            ct = r.headers.get("content-type", "")
            assert "json" in ct.lower(), f"non-JSON 400 response: content-type={ct}, body[:200]={r.text[:200]}"
            j = r.json()
            detail = j.get("detail", "")
            assert "fal" in detail.lower(), f"detail should mention fal: {detail}"
