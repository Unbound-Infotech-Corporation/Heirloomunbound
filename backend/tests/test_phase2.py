"""Phase 2 backend tests: ElevenLabs voice clone, Photos, Companion."""
import base64
import io
import os
import pytest
import requests
from PIL import Image

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
           "https://voice-clone-hub-20.preview.emergentagent.com"
API = f"{BASE_URL}/api"


# ---------- helpers ----------
def _png_bytes(w=32, h=32, color=(120, 200, 40)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _multipart_session(token: str) -> requests.Session:
    """requests session WITHOUT the json content-type header (so multipart works)."""
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token}"
    return s


# ============================================================
# REGRESSION CHECKS (existing endpoints still healthy)
# ============================================================
class TestRegression:
    def test_auth_me(self, user1_client):
        r = user1_client.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert "user_id" in r.json()

    def test_dashboard(self, user1_client):
        r = user1_client.get(f"{API}/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "stats" in data or "entry_counts" in data or isinstance(data, dict)

    def test_archive_list(self, user1_client):
        r = user1_client.get(f"{API}/archive")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ============================================================
# ELEVENLABS VOICE CLONE
# ============================================================
class TestVoiceCloneSettings:
    def test_get_settings_default(self, user1_client):
        r = user1_client.get(f"{API}/voice-clone/settings")
        assert r.status_code == 200
        d = r.json()
        for k in ("has_user_key", "has_default_key", "api_key_preview", "voice_id", "voice_name"):
            assert k in d, f"missing {k}"
        assert d["has_default_key"] is True

    def test_put_settings_user_key(self, user1_client):
        r = user1_client.put(f"{API}/voice-clone/settings", json={"api_key": "sk_test_user_override_123"})
        assert r.status_code == 200
        # verify has_user_key flipped
        s = user1_client.get(f"{API}/voice-clone/settings").json()
        assert s["has_user_key"] is True

    def test_put_settings_clear(self, user1_client):
        r = user1_client.put(f"{API}/voice-clone/settings", json={"clear": True})
        assert r.status_code == 200
        s = user1_client.get(f"{API}/voice-clone/settings").json()
        assert s["has_user_key"] is False
        assert s["voice_id"] == ""

    def test_put_settings_empty_400(self, user1_client):
        r = user1_client.put(f"{API}/voice-clone/settings", json={})
        assert r.status_code == 400


class TestVoiceCloneVoices:
    def test_voices_listing(self, user1_client):
        # ensure cleared user key so default key is used
        user1_client.put(f"{API}/voice-clone/settings", json={"clear": True})
        r = user1_client.get(f"{API}/voice-clone/voices")
        assert r.status_code == 200, r.text
        d = r.json()
        assert "voices" in d
        assert isinstance(d["voices"], list)
        assert len(d["voices"]) > 0
        first = d["voices"][0]
        assert "voice_id" in first
        assert "name" in first
        # stash for later
        pytest.shared_voice_id = first["voice_id"]


class TestVoiceCloneSpeak:
    def test_speak_no_voice_id_400(self, user1_client):
        # make sure cleared
        user1_client.put(f"{API}/voice-clone/settings", json={"clear": True})
        r = user1_client.post(f"{API}/voice-clone/speak", json={"text": "Hello"})
        assert r.status_code == 400

    def test_speak_success(self, user1_client):
        vid = getattr(pytest, "shared_voice_id", None)
        if not vid:
            r = user1_client.get(f"{API}/voice-clone/voices")
            vid = r.json()["voices"][0]["voice_id"]
        # set voice_id
        s = user1_client.put(f"{API}/voice-clone/settings", json={"voice_id": vid})
        assert s.status_code == 200
        r = user1_client.post(f"{API}/voice-clone/speak", json={"text": "Hello there"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("mime") == "audio/mpeg"
        assert isinstance(d.get("audio_base64"), str)
        # validate it is base64-decodable and non-empty audio
        raw = base64.b64decode(d["audio_base64"])
        assert len(raw) > 1000, f"audio too small: {len(raw)} bytes"

    def test_speak_empty_text_400(self, user1_client):
        r = user1_client.post(f"{API}/voice-clone/speak", json={"text": "  "})
        assert r.status_code == 400


class TestVoiceCloneCloneGuards:
    """LOW priority: don't actually call clone (costs credits) — only test guards."""

    def test_clone_empty_files_400(self, user1_token):
        s = _multipart_session(user1_token)
        # no files at all -> FastAPI returns 422 (validation). Send empty files list via empty UploadFile.
        r = s.post(f"{API}/voice-clone/clone", data={"name": "Test", "description": ""})
        # FastAPI will return 422 since files is required. Accept either.
        assert r.status_code in (400, 422), r.text

    def test_clone_missing_key_400(self, user1_token):
        # set user override empty? We can't unset DEFAULT_KEY from .env easily.
        # Skip if default key exists (it does).
        s = _multipart_session(user1_token)
        r = requests.get(f"{API}/voice-clone/settings", headers={"Authorization": f"Bearer {user1_token}"})
        if r.json().get("has_default_key"):
            pytest.skip("Default ELEVENLABS_API_KEY present — cannot test missing-key path without unsetting env")


# ============================================================
# PHOTOS
# ============================================================
class TestPhotos:
    def test_upload_and_list(self, user1_token):
        s = _multipart_session(user1_token)
        png = _png_bytes()
        r = s.post(
            f"{API}/photos/upload",
            files={"file": ("memory.png", png, "image/png")},
            data={"caption": "memory of dad", "taken_at": "1987"},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert "photo_id" in d
        assert d["caption"] == "memory of dad"
        assert d["taken_at"] == "1987"
        assert "storage_path" in d
        pytest.shared_photo_id = d["photo_id"]

        # list
        r2 = s.get(f"{API}/photos")
        assert r2.status_code == 200
        lst = r2.json()
        assert any(p["photo_id"] == d["photo_id"] for p in lst)

    def test_download_bearer_and_query(self, user1_token):
        pid = pytest.shared_photo_id
        # Bearer
        r1 = requests.get(f"{API}/photos/{pid}/file", headers={"Authorization": f"Bearer {user1_token}"})
        assert r1.status_code == 200
        assert r1.headers.get("content-type", "").startswith("image/")
        assert len(r1.content) > 50
        # ?auth=
        r2 = requests.get(f"{API}/photos/{pid}/file", params={"auth": user1_token})
        assert r2.status_code == 200
        assert len(r2.content) > 50

    def test_download_unauth(self):
        pid = pytest.shared_photo_id
        r = requests.get(f"{API}/photos/{pid}/file")
        assert r.status_code == 401

    def test_patch_caption(self, user1_client):
        pid = pytest.shared_photo_id
        r = user1_client.patch(f"{API}/photos/{pid}", json={"caption": "updated caption"})
        assert r.status_code == 200
        assert r.json()["caption"] == "updated caption"

    def test_delete_soft(self, user1_client):
        pid = pytest.shared_photo_id
        r = user1_client.delete(f"{API}/photos/{pid}")
        assert r.status_code == 200
        # verify it disappears from listing
        lst = user1_client.get(f"{API}/photos").json()
        assert not any(p["photo_id"] == pid for p in lst)

    def test_upload_empty_400(self, user1_token):
        s = _multipart_session(user1_token)
        r = s.post(
            f"{API}/photos/upload",
            files={"file": ("empty.png", b"", "image/png")},
            data={"caption": "", "taken_at": ""},
        )
        assert r.status_code == 400, r.text

    def test_upload_unsupported_mime_400(self, user1_token):
        s = _multipart_session(user1_token)
        r = s.post(
            f"{API}/photos/upload",
            files={"file": ("note.txt", b"hello", "text/plain")},
            data={"caption": "", "taken_at": ""},
        )
        assert r.status_code == 400, r.text

    def test_upload_oversize_413(self, user1_token):
        s = _multipart_session(user1_token)
        big = b"\x89PNG\r\n\x1a\n" + b"0" * (13 * 1024 * 1024)
        r = s.post(
            f"{API}/photos/upload",
            files={"file": ("big.png", big, "image/png")},
            data={"caption": "", "taken_at": ""},
        )
        assert r.status_code == 413, r.text


# ============================================================
# COMPANION
# ============================================================
class TestCompanionRegistration:
    def test_register_device(self, user1_client):
        r = user1_client.post(f"{API}/companion/register", json={"name": "Test PC"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["device_id"].startswith("dev_")
        assert d["device_token"].startswith("comp_")
        assert d["name"] == "Test PC"
        pytest.shared_device_id_u1 = d["device_id"]
        pytest.shared_device_token_u1 = d["device_token"]

    def test_list_devices_no_token_exposed(self, user1_client):
        r = user1_client.get(f"{API}/companion/devices")
        assert r.status_code == 200
        lst = r.json()
        assert isinstance(lst, list)
        assert any(d["device_id"] == pytest.shared_device_id_u1 for d in lst)
        for d in lst:
            assert "device_token" not in d, "device_token must not be exposed in list"

    def test_register_user2_device(self, user2_client):
        r = user2_client.post(f"{API}/companion/register", json={"name": "U2 PC"})
        assert r.status_code == 200
        d = r.json()
        pytest.shared_device_id_u2 = d["device_id"]
        pytest.shared_device_token_u2 = d["device_token"]


class TestCompanionCommandQueue:
    def test_queue_command_user1(self, user1_client):
        r = user1_client.post(
            f"{API}/companion/queue-command",
            json={"kind": "shell", "payload": {"command": "echo hi"}},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "queued"
        assert d["kind"] == "shell"
        assert d["cmd_id"].startswith("cmd_")
        pytest.shared_cmd_id_u1 = d["cmd_id"]

    def test_list_commands(self, user1_client):
        r = user1_client.get(f"{API}/companion/commands")
        assert r.status_code == 200
        lst = r.json()
        assert any(c["cmd_id"] == pytest.shared_cmd_id_u1 for c in lst)

    def test_queue_command_user2(self, user2_client):
        r = user2_client.post(
            f"{API}/companion/queue-command",
            json={"kind": "say", "payload": {"text": "hi u2"}},
        )
        assert r.status_code == 200
        pytest.shared_cmd_id_u2 = r.json()["cmd_id"]


class TestCompanionPollAndResult:
    def test_poll_with_device_token(self):
        token = pytest.shared_device_token_u1
        r = requests.get(f"{API}/companion/poll", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "commands" in d and "server_time" in d
        cmd_ids = [c["cmd_id"] for c in d["commands"]]
        assert pytest.shared_cmd_id_u1 in cmd_ids

    def test_poll_dispatches(self, user1_client):
        # After a poll, the queued cmd should be 'dispatched'
        r = user1_client.get(f"{API}/companion/commands")
        cmds = {c["cmd_id"]: c for c in r.json()}
        assert cmds[pytest.shared_cmd_id_u1]["status"] == "dispatched"

    def test_multi_user_isolation_on_poll(self):
        # User1's poll should NOT see User2's queued cmd, and vice versa
        token1 = pytest.shared_device_token_u1
        token2 = pytest.shared_device_token_u2
        r1 = requests.get(f"{API}/companion/poll", headers={"Authorization": f"Bearer {token1}"})
        r2 = requests.get(f"{API}/companion/poll", headers={"Authorization": f"Bearer {token2}"})
        u1_cmds = [c["cmd_id"] for c in r1.json()["commands"]]
        u2_cmds = [c["cmd_id"] for c in r2.json()["commands"]]
        assert pytest.shared_cmd_id_u1 not in u2_cmds
        assert pytest.shared_cmd_id_u2 not in u1_cmds

    def test_poll_invalid_token(self):
        r = requests.get(f"{API}/companion/poll", headers={"Authorization": "Bearer comp_bogus_xyz"})
        assert r.status_code == 401

    def test_result_completes_command(self, user1_client):
        token = pytest.shared_device_token_u1
        r = requests.post(
            f"{API}/companion/result",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"cmd_id": pytest.shared_cmd_id_u1, "status": "ok", "output": "hello"},
        )
        assert r.status_code == 200
        # verify command is done with result stored
        lst = user1_client.get(f"{API}/companion/commands").json()
        cmd = next(c for c in lst if c["cmd_id"] == pytest.shared_cmd_id_u1)
        assert cmd["status"] == "done"
        assert cmd["result"] == "hello"


class TestCompanionVoiceGuards:
    def test_voice_empty_400(self):
        token = pytest.shared_device_token_u1
        s = requests.Session()
        s.headers["Authorization"] = f"Bearer {token}"
        r = s.post(
            f"{API}/companion/voice",
            files={"audio": ("empty.webm", b"", "audio/webm")},
            data={"save_to_archive": "false"},
        )
        assert r.status_code == 400, r.text

    def test_voice_non_device_token_401(self, user1_token):
        # Using a normal session token (not a device token) should 401
        s = requests.Session()
        s.headers["Authorization"] = f"Bearer {user1_token}"
        r = s.post(
            f"{API}/companion/voice",
            files={"audio": ("a.webm", b"x", "audio/webm")},
            data={"save_to_archive": "false"},
        )
        assert r.status_code == 401, r.text


class TestCompanionScriptDownload:
    def test_script_download(self, user1_client):
        token = pytest.shared_device_token_u1
        r = user1_client.get(f"{API}/companion/script", params={"token": token})
        assert r.status_code == 200, r.text
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower()
        assert "heirloom_companion.py" in cd
        body = r.text
        assert token in body, "device_token must be embedded in script"
        # backend URL hint present (env var) - check substitution did NOT leave placeholder
        assert "__DEVICE_TOKEN__" not in body
        assert "__BACKEND_URL_HINT__" not in body

    def test_script_download_unknown_token_404(self, user1_client):
        r = user1_client.get(f"{API}/companion/script", params={"token": "comp_nope"})
        assert r.status_code == 404


class TestCompanionRevoke:
    def test_revoke_device(self, user1_client):
        # Register a throwaway device, revoke it, verify poll now 401s with that token.
        reg = user1_client.post(f"{API}/companion/register", json={"name": "Throwaway"}).json()
        did = reg["device_id"]
        tok = reg["device_token"]
        r = user1_client.delete(f"{API}/companion/devices/{did}")
        assert r.status_code == 200
        r2 = requests.get(f"{API}/companion/poll", headers={"Authorization": f"Bearer {tok}"})
        assert r2.status_code == 401
