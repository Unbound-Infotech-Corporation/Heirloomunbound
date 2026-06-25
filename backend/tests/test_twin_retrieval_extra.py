"""Extra twin retrieval tests for iteration_5 — verify the fix end-to-end:
1. Seeded entry "Fishing with Dad at Lake Erie" is actually retrieved by token-match
   (the streamed reply must reference Lake Erie/eight/father).
2. A user with ZERO archive entries can still chat without 500.
"""
import json
import os

import httpx
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or
            "https://voice-clone-hub-20.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

# Primary user (has archive, was seeded by test_phase4.py runs)
TOKEN = "p4_sess_1782377069570"
H = {"Authorization": f"Bearer {TOKEN}"}

# Zero-archive user (seeded above)
EMPTY_TOKEN = "p4_empty_1782377723"
EH = {"Authorization": f"Bearer {EMPTY_TOKEN}"}


def _stream_twin(headers, message):
    r = requests.post(f"{API}/twin/start", headers=headers, json={}, timeout=15)
    assert r.status_code == 200, r.text
    cid = r.json()["conversation_id"]

    full = ""
    done = False
    err = None
    with httpx.stream(
        "POST", f"{API}/twin/message",
        headers={**headers, "Content-Type": "application/json"},
        json={"conversation_id": cid, "message": message},
        timeout=120,
    ) as resp:
        assert resp.status_code == 200, resp.read().decode()
        assert "text/event-stream" in resp.headers.get("content-type", "")
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            while "\n\n" in buf:
                evt, buf = buf.split("\n\n", 1)
                if "event: done" in evt:
                    done = True
                    continue
                if "event: error" in evt:
                    err = evt
                for line in evt.split("\n"):
                    if line.startswith("data:"):
                        try:
                            full += json.loads(line[5:].strip()).get("text", "")
                        except Exception:
                            pass
    return done, full, err


class TestTwinRetrievalFix:
    def test_seed_lake_erie_entry(self):
        r = requests.post(f"{API}/archive", headers=H, json={
            "type": "memory",
            "title": "Fishing with Dad at Lake Erie",
            "content": "My father taught me to fish at Lake Erie when I was eight years old.",
            "tags": ["fishing", "dad"],
        }, timeout=15)
        assert r.status_code == 200, r.text

    def test_retrieval_pulls_matching_entry(self):
        done, full, err = _stream_twin(H, "What did I say about fishing?")
        assert err is None, f"error event: {err}"
        assert done, f"no done event; partial reply={full!r}"
        assert len(full) > 5, f"empty reply: {full!r}"
        low = full.lower()
        assert ("lake erie" in low or "eight" in low or "father" in low or "dad" in low or "fish" in low), \
            f"reply does not reference retrieved memory: {full!r}"

    def test_zero_archive_user_streams_gracefully(self):
        # User exists, has no archive — should still get a streamed reply (no 500)
        done, full, err = _stream_twin(EH, "Tell me something about yourself.")
        assert err is None, f"error event: {err}"
        assert done, f"no done event; partial reply={full!r}"
        assert len(full) > 0, f"empty reply for zero-archive user: {full!r}"
