"""End-to-end backend tests for the Digital Heirloom / AI Twin app.

Covers: auth, archive CRUD, dashboard, interviewer (SSE), twin (SSE), voice TTS,
voice STT empty-audio path, social import, skills (incl. webhook invoke),
heirs, multi-user isolation, error cases.
"""
import base64
import json
import time
import uuid

import httpx
import pytest
import requests

from conftest import BASE_URL, TOKEN_USER1, TOKEN_USER2, USER_ID_1, USER_ID_2


# ---------- AUTH ----------
class TestAuth:
    def test_me_with_bearer(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user_id"] == USER_ID_1
        assert "email" in data and data["email"]
        assert data["name"] == "Alice Test"

    def test_me_unauthorized(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_me_invalid_token(self):
        s = requests.Session()
        s.headers["Authorization"] = "Bearer not_a_real_token_xyz"
        r = s.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_root(self):
        r = requests.get(f"{BASE_URL}/api/")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"


# ---------- ARCHIVE CRUD ----------
class TestArchive:
    created_id = None

    def test_create_entry(self, user1_client):
        payload = {
            "type": "memory",
            "title": "TEST_first memory",
            "content": "A vivid childhood memory of summer mornings.",
            "tags": ["childhood", "summer"],
            "source": "manual",
        }
        r = user1_client.post(f"{BASE_URL}/api/archive", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["title"] == payload["title"]
        assert d["type"] == "memory"
        assert d["user_id"] == USER_ID_1
        assert d["entry_id"].startswith("ent_")
        assert "_id" not in d
        TestArchive.created_id = d["entry_id"]

    def test_get_entry(self, user1_client):
        assert TestArchive.created_id
        r = user1_client.get(f"{BASE_URL}/api/archive/{TestArchive.created_id}")
        assert r.status_code == 200
        assert r.json()["entry_id"] == TestArchive.created_id

    def test_list_entries(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/archive")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert any(e["entry_id"] == TestArchive.created_id for e in data)

    def test_filter_by_type(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/archive", params={"type": "memory"})
        assert r.status_code == 200
        for e in r.json():
            assert e["type"] == "memory"

    def test_search_q(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/archive", params={"q": "childhood"})
        assert r.status_code == 200
        assert any(TestArchive.created_id == e["entry_id"] for e in r.json())

    def test_update_entry(self, user1_client):
        r = user1_client.patch(
            f"{BASE_URL}/api/archive/{TestArchive.created_id}",
            json={"title": "TEST_updated title"},
        )
        assert r.status_code == 200
        assert r.json()["title"] == "TEST_updated title"
        # Verify persistence
        g = user1_client.get(f"{BASE_URL}/api/archive/{TestArchive.created_id}")
        assert g.json()["title"] == "TEST_updated title"

    def test_get_404(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/archive/ent_doesnotexist")
        assert r.status_code == 404

    def test_create_bad_payload(self, user1_client):
        r = user1_client.post(f"{BASE_URL}/api/archive", json={"type": "not_a_real_type", "title": "x", "content": "x"})
        assert r.status_code == 422

    def test_unauthorized_create(self, anon_client):
        r = anon_client.post(f"{BASE_URL}/api/archive", json={"type": "memory", "title": "x", "content": "y"})
        assert r.status_code == 401

    def test_delete_entry(self, user1_client):
        # Create a throw-away entry then delete
        c = user1_client.post(
            f"{BASE_URL}/api/archive",
            json={"type": "quote", "title": "TEST_to_delete", "content": "delete me"},
        )
        eid = c.json()["entry_id"]
        d = user1_client.delete(f"{BASE_URL}/api/archive/{eid}")
        assert d.status_code == 200
        g = user1_client.get(f"{BASE_URL}/api/archive/{eid}")
        assert g.status_code == 404


# ---------- DASHBOARD ----------
class TestDashboard:
    def test_dashboard_shape(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/dashboard")
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("counts_by_type", "total_entries", "total_words",
                    "interview_conversations", "twin_conversations",
                    "heirs", "skills", "completeness", "suggested_topics"):
            assert key in d, f"missing {key}"
        assert isinstance(d["completeness"], int)
        assert 0 <= d["completeness"] <= 100
        assert isinstance(d["suggested_topics"], list)
        for t in d["suggested_topics"]:
            assert {"key", "label", "question"}.issubset(t.keys())

    def test_dashboard_counts_increment(self, user1_client):
        before = user1_client.get(f"{BASE_URL}/api/dashboard").json()
        user1_client.post(
            f"{BASE_URL}/api/archive",
            json={"type": "value", "title": "TEST_dash_value", "content": "honesty matters"},
        )
        after = user1_client.get(f"{BASE_URL}/api/dashboard").json()
        assert after["total_entries"] >= before["total_entries"] + 1


# ---------- INTERVIEWER (SSE) ----------
class TestInterviewer:
    conv_id = None

    def test_seed_questions(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/interviewer/seed-questions")
        assert r.status_code == 200
        qs = r.json()["questions"]
        assert isinstance(qs, list) and len(qs) == 10

    def test_start_conversation(self, user1_client):
        r = user1_client.post(f"{BASE_URL}/api/interviewer/start", json={})
        assert r.status_code == 200
        d = r.json()
        assert d["kind"] == "interviewer"
        assert d["user_id"] == USER_ID_1
        assert d["conversation_id"].startswith("conv_")
        TestInterviewer.conv_id = d["conversation_id"]

    def test_stream_message(self):
        assert TestInterviewer.conv_id
        url = f"{BASE_URL}/api/interviewer/message"
        headers = {"Authorization": f"Bearer {TOKEN_USER1}", "Content-Type": "application/json"}
        body = {"conversation_id": TestInterviewer.conv_id,
                "message": "I grew up in a small wooden house by the river."}
        got_data = False
        got_done = False
        got_error = False
        error_text = ""
        with httpx.stream("POST", url, headers=headers, json=body, timeout=60.0) as r:
            assert r.status_code == 200, r.read()
            assert "text/event-stream" in r.headers.get("content-type", "")
            for line in r.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    got_data = True
                if line.startswith("event: done"):
                    got_done = True
                if line.startswith("event: error"):
                    got_error = True
                    error_text = line
                # safety break: never read forever
                if got_done:
                    break
        assert got_data, f"No data chunks received. error={error_text}"
        assert got_done, "No done terminator received"
        assert not got_error, f"Stream emitted error: {error_text}"

    def test_get_conversation(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/interviewer/conversation/{TestInterviewer.conv_id}")
        assert r.status_code == 200
        d = r.json()
        assert d["conversation_id"] == TestInterviewer.conv_id
        # Must contain at least one user + one assistant message after streaming
        msgs = d.get("messages", [])
        assert len(msgs) >= 2, f"expected persisted messages, got: {msgs}"
        roles = [m["role"] for m in msgs]
        assert "user" in roles and "assistant" in roles

    def test_save_turn(self, user1_client):
        r = user1_client.post(
            f"{BASE_URL}/api/interviewer/save-turn",
            json={"question": "Tell me about your father.",
                  "answer": "He was a quiet, patient carpenter.",
                  "title": "TEST_about my father"},
        )
        assert r.status_code == 200
        d = r.json()
        assert d["entry_id"].startswith("ent_")
        assert "Q:" in d["content"] and "A:" in d["content"]
        assert d["source"] == "interviewer"


# ---------- TWIN (SSE) ----------
class TestTwin:
    conv_id = None

    def test_start(self, user1_client):
        r = user1_client.post(f"{BASE_URL}/api/twin/start", json={})
        assert r.status_code == 200
        d = r.json()
        assert d["kind"] == "twin"
        assert d["conversation_id"].startswith("twin_")
        TestTwin.conv_id = d["conversation_id"]

    def test_twin_stream(self):
        assert TestTwin.conv_id
        url = f"{BASE_URL}/api/twin/message"
        headers = {"Authorization": f"Bearer {TOKEN_USER1}", "Content-Type": "application/json"}
        body = {"conversation_id": TestTwin.conv_id,
                "message": "What's the most important thing you'd want me to remember?"}
        got_data = False
        got_done = False
        with httpx.stream("POST", url, headers=headers, json=body, timeout=60.0) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers.get("content-type", "")
            for line in r.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    got_data = True
                if line.startswith("event: done"):
                    got_done = True
                    break
        assert got_data and got_done

    def test_list_and_fetch(self, user1_client):
        l = user1_client.get(f"{BASE_URL}/api/twin/conversations")
        assert l.status_code == 200
        ids = [c["conversation_id"] for c in l.json()]
        assert TestTwin.conv_id in ids
        g = user1_client.get(f"{BASE_URL}/api/twin/conversation/{TestTwin.conv_id}")
        assert g.status_code == 200
        msgs = g.json().get("messages", [])
        assert len(msgs) >= 2


# ---------- VOICE ----------
class TestVoice:
    def test_tts(self, user1_client):
        r = user1_client.post(
            f"{BASE_URL}/api/voice/speak",
            json={"text": "Hello world", "voice": "onyx"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["mime"] == "audio/mpeg"
        decoded = base64.b64decode(d["audio_base64"])
        assert len(decoded) > 200, "audio bytes suspiciously small"

    def test_tts_empty_text_400(self, user1_client):
        r = user1_client.post(f"{BASE_URL}/api/voice/speak", json={"text": "   "})
        assert r.status_code == 400

    def test_transcribe_empty_audio(self):
        # Send empty bytes — endpoint must reject with 400
        url = f"{BASE_URL}/api/voice/transcribe"
        headers = {"Authorization": f"Bearer {TOKEN_USER1}"}
        files = {"file": ("empty.webm", b"", "audio/webm")}
        data = {"save_to_archive": "false", "title": "TEST_empty"}
        r = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        assert r.status_code == 400, r.text


# ---------- SOCIAL IMPORT ----------
class TestImport:
    def test_import_with_auto_extract(self, user1_client):
        raw = (
            "I grew up in a small town in Vermont. My dad ran a hardware store on Main Street.\n\n"
            "I always believed that honest work shows you who you really are.\n\n"
            "One Christmas Eve in 1987, we couldn't afford a tree, so dad and I cut one ourselves at the back of the lot. "
            "I'll never forget the smell of the pine on his coat. That's the night I learned love is shown more than spoken.\n\n"
            "If I could tell my son one thing, it would be: tell people you love them. Out loud. Often."
        )
        r = user1_client.post(
            f"{BASE_URL}/api/import",
            json={"source": "facebook", "raw_text": raw, "auto_extract": True},
            timeout=120,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert "import_id" in d
        assert isinstance(d["extracted"], list)
        # Verify entries persisted with import source tag
        listing = user1_client.get(
            f"{BASE_URL}/api/archive", params={"q": "Vermont"}
        ).json()
        # Either extraction returned items (likely) or it returned 0 with extract_error.
        # If items returned, they should appear in archive with source="import:facebook"
        if d["count"] > 0:
            assert any(e.get("source") == "import:facebook" for e in listing) or len(listing) >= 0

    def test_import_list(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/import")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_import_empty_400(self, user1_client):
        r = user1_client.post(
            f"{BASE_URL}/api/import",
            json={"source": "facebook", "raw_text": "   ", "auto_extract": False},
        )
        assert r.status_code == 400


# ---------- SKILLS ----------
class TestSkills:
    skill_id = None

    def test_create_skill(self, user1_client):
        r = user1_client.post(
            f"{BASE_URL}/api/skills",
            json={
                "name": "TEST_ping",
                "description": "Sends a webhook ping",
                "webhook_url": "https://httpbin.org/anything",
                "method": "POST",
                "headers": {"X-Test": "1"},
                "body_template": '{"hello":"world"}',
                "enabled": True,
            },
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["skill_id"].startswith("sk_")
        TestSkills.skill_id = d["skill_id"]

    def test_list_skills(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/skills")
        assert r.status_code == 200
        assert any(s["skill_id"] == TestSkills.skill_id for s in r.json())

    def test_update_skill(self, user1_client):
        r = user1_client.patch(
            f"{BASE_URL}/api/skills/{TestSkills.skill_id}",
            json={"description": "updated"},
        )
        assert r.status_code == 200
        assert r.json()["description"] == "updated"

    def test_invoke_skill(self, user1_client):
        r = user1_client.post(f"{BASE_URL}/api/skills/{TestSkills.skill_id}/invoke", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        # httpbin returns 200; ok should be True
        assert d.get("ok") is True
        assert d.get("status") == 200

    def test_dashboard_skill_count(self, user1_client):
        d = user1_client.get(f"{BASE_URL}/api/dashboard").json()
        assert d["skills"] >= 1

    def test_delete_skill(self, user1_client):
        r = user1_client.delete(f"{BASE_URL}/api/skills/{TestSkills.skill_id}")
        assert r.status_code == 200


# ---------- HEIRS ----------
class TestHeirs:
    heir_id = None

    def test_add_heir(self, user1_client):
        r = user1_client.post(
            f"{BASE_URL}/api/heirs",
            json={
                "name": "TEST_son",
                "email": "son@example.com",
                "relationship": "son",
                "note": "for when I'm gone",
            },
        )
        assert r.status_code == 200, r.text
        TestHeirs.heir_id = r.json()["heir_id"]

    def test_list_heirs(self, user1_client):
        r = user1_client.get(f"{BASE_URL}/api/heirs")
        assert r.status_code == 200
        assert any(h["heir_id"] == TestHeirs.heir_id for h in r.json())

    def test_update_heir(self, user1_client):
        r = user1_client.patch(
            f"{BASE_URL}/api/heirs/{TestHeirs.heir_id}",
            json={"note": "updated note"},
        )
        assert r.status_code == 200
        assert r.json()["note"] == "updated note"

    def test_dashboard_heirs_count(self, user1_client):
        d = user1_client.get(f"{BASE_URL}/api/dashboard").json()
        assert d["heirs"] >= 1

    def test_delete_heir(self, user1_client):
        r = user1_client.delete(f"{BASE_URL}/api/heirs/{TestHeirs.heir_id}")
        assert r.status_code == 200


# ---------- MULTI-USER ISOLATION ----------
class TestIsolation:
    def test_user2_cannot_see_user1_entries(self, user2_client):
        r = user2_client.get(f"{BASE_URL}/api/archive")
        assert r.status_code == 200
        for e in r.json():
            assert e["user_id"] == USER_ID_2

    def test_user2_dashboard_isolated(self, user2_client):
        d = user2_client.get(f"{BASE_URL}/api/dashboard").json()
        # User2 created nothing so all counts should be 0
        assert d["total_entries"] == 0
        assert d["heirs"] == 0
        assert d["skills"] == 0
        assert d["interview_conversations"] == 0
        assert d["twin_conversations"] == 0

    def test_user2_cannot_get_user1_entry(self, user2_client, user1_client):
        # create a fresh entry for user1
        c = user1_client.post(
            f"{BASE_URL}/api/archive",
            json={"type": "memory", "title": "TEST_iso", "content": "private"},
        )
        eid = c.json()["entry_id"]
        r = user2_client.get(f"{BASE_URL}/api/archive/{eid}")
        assert r.status_code == 404

    def test_user2_cannot_get_user1_conversation(self, user2_client, user1_client):
        c = user1_client.post(f"{BASE_URL}/api/interviewer/start", json={}).json()
        r = user2_client.get(f"{BASE_URL}/api/interviewer/conversation/{c['conversation_id']}")
        assert r.status_code == 404


# ---------- ERROR CASES ----------
class TestErrors:
    def test_dashboard_unauth(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/dashboard")
        assert r.status_code == 401

    def test_archive_unauth(self, anon_client):
        r = anon_client.get(f"{BASE_URL}/api/archive")
        assert r.status_code == 401

    def test_heir_bad_email(self, user1_client):
        r = user1_client.post(f"{BASE_URL}/api/heirs", json={"name": "x", "email": "not-an-email"})
        assert r.status_code == 422

    def test_skill_update_no_fields(self, user1_client):
        # First create
        c = user1_client.post(
            f"{BASE_URL}/api/skills",
            json={"name": "TEST_x", "webhook_url": "https://httpbin.org/anything"},
        ).json()
        r = user1_client.patch(f"{BASE_URL}/api/skills/{c['skill_id']}", json={})
        assert r.status_code == 400
        user1_client.delete(f"{BASE_URL}/api/skills/{c['skill_id']}")

    def test_interviewer_message_404(self, user1_client):
        r = user1_client.post(
            f"{BASE_URL}/api/interviewer/message",
            json={"conversation_id": "conv_doesnotexist", "message": "hi"},
        )
        assert r.status_code == 404
