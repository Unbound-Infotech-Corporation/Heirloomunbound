"""Iteration-13: D-ID talking-head avatar end-to-end tests.

Routes tested:
  GET    /api/avatar/me
  PUT    /api/avatar/source-url
  POST   /api/avatar/talk
  GET    /api/avatar/talks/{talk_id}
  POST   /api/avatar/source-upload (intentionally 501)
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://voice-clone-hub-20.preview.emergentagent.com").rstrip("/")

# Pre-minted via mongosh (see test_credentials.md)
TOKEN_A = os.environ.get("TEST_TOKEN_A", "tk_avatar_1782543125527")
USER_A = os.environ.get("TEST_USER_A", "test-user-avatar-1782543125527")
TOKEN_B = os.environ.get("TEST_TOKEN_B", "tk_avatar_1782543125545")
USER_B = os.environ.get("TEST_USER_B", "test-user-avatar-1782543125545")


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------- Auth gating ----------------------
class TestAuthGating:
    def test_me_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/avatar/me")
        assert r.status_code == 401, r.text

    def test_talk_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/avatar/talk", json={"text": "hi"})
        assert r.status_code == 401, r.text


# ---------------------- GET /avatar/me ----------------------
class TestAvatarMe:
    def test_me_returns_configured_true_and_default_url(self):
        r = requests.get(f"{BASE_URL}/api/avatar/me", headers=_h(TOKEN_A))
        assert r.status_code == 200, r.text
        data = r.json()
        assert "avatar_source_url" in data
        assert "default_url" in data
        assert data["default_url"].startswith("https://")
        assert data["configured"] is True, "D_ID_API_KEY should be configured"


# ---------------------- PUT /avatar/source-url ----------------------
class TestSourceUrl:
    def test_put_valid_https_url_persists(self):
        url = "https://create-images-results.d-id.com/DefaultPresenters/Emma_f/v1_image.jpeg"
        r = requests.put(
            f"{BASE_URL}/api/avatar/source-url",
            headers=_h(TOKEN_A),
            json={"url": url},
        )
        assert r.status_code == 200, r.text
        assert r.json()["avatar_source_url"] == url

        # Verify persistence via /me
        me = requests.get(f"{BASE_URL}/api/avatar/me", headers=_h(TOKEN_A)).json()
        assert me["avatar_source_url"] == url

    def test_put_non_http_url_returns_400(self):
        r = requests.put(
            f"{BASE_URL}/api/avatar/source-url",
            headers=_h(TOKEN_A),
            json={"url": "ftp://example.com/face.jpg"},
        )
        assert r.status_code == 400, r.text

    def test_put_empty_url_is_accepted_as_clear(self):
        # Code path: empty string skips the http check and writes ""
        r = requests.put(
            f"{BASE_URL}/api/avatar/source-url",
            headers=_h(TOKEN_B),
            json={"url": ""},
        )
        assert r.status_code == 200, r.text


# ---------------------- POST /avatar/source-upload (501 stub) ----------------------
class TestSourceUpload:
    def test_upload_returns_501_with_helpful_detail(self):
        files = {"file": ("face.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")}
        r = requests.post(
            f"{BASE_URL}/api/avatar/source-upload",
            headers={"Authorization": f"Bearer {TOKEN_A}"},
            files=files,
        )
        assert r.status_code == 501, r.text
        body = r.json()
        detail = (body.get("detail") or "").lower()
        assert "url" in detail or "public" in detail


# ---------------------- POST /avatar/talk + GET /avatar/talks/{id} ----------------------
class TestTalkFlow:
    talk_id = None

    def test_create_talk_returns_quickly(self):
        t0 = time.time()
        r = requests.post(
            f"{BASE_URL}/api/avatar/talk",
            headers=_h(TOKEN_A),
            json={"text": "Hello from my twin."},
            timeout=40,
        )
        elapsed = time.time() - t0
        assert r.status_code == 200, f"create_talk failed in {elapsed:.1f}s: {r.status_code} {r.text}"
        assert elapsed < 35, f"create_talk too slow: {elapsed:.1f}s"
        data = r.json()
        assert "talk_id" in data and data["talk_id"]
        assert "status" in data
        assert data.get("poll", "").endswith(f"/api/avatar/talks/{data['talk_id']}")
        TestTalkFlow.talk_id = data["talk_id"]

    def test_poll_other_user_returns_404(self):
        assert TestTalkFlow.talk_id, "create_talk must have run first"
        r = requests.get(
            f"{BASE_URL}/api/avatar/talks/{TestTalkFlow.talk_id}",
            headers=_h(TOKEN_B),
        )
        assert r.status_code == 404, r.text

    def test_poll_unknown_id_returns_404(self):
        r = requests.get(
            f"{BASE_URL}/api/avatar/talks/tlk_does_not_exist_xyz",
            headers=_h(TOKEN_A),
        )
        assert r.status_code == 404, r.text

    def test_poll_until_done(self):
        assert TestTalkFlow.talk_id, "create_talk must have run first"
        deadline = time.time() + 120
        last_status = None
        result_url = None
        while time.time() < deadline:
            r = requests.get(
                f"{BASE_URL}/api/avatar/talks/{TestTalkFlow.talk_id}",
                headers=_h(TOKEN_A),
                timeout=20,
            )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["talk_id"] == TestTalkFlow.talk_id
            last_status = data.get("status")
            if last_status in ("done", "error", "rejected"):
                result_url = data.get("result_url")
                break
            time.sleep(3)

        assert last_status == "done", f"Talk did not complete in 120s, last_status={last_status}"
        assert result_url, "Expected result_url when status=done"
        assert result_url.lower().endswith(".mp4") or "mp4" in result_url.lower()
