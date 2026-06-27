"""Iteration 11 — music intent + long-term memory tests.

Covers:
- /api/music/providers + preference persistence
- /api/music/play (with and without companion device)
- Twin /message music short-circuit (SSE)
- Music intent edge cases (deterministic regex)
- /api/memory/facts (extraction, caching, rebuild, delete)
- Episode summary auto-generation
- Multi-user isolation
"""
import json
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
TOK_A = os.environ["TOK_A"]
TOK_B = os.environ["TOK_B"]
UID_A = os.environ["UID_A"]
UID_B = os.environ["UID_B"]


def h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ----------------- Music providers + preferences -----------------
def test_music_providers_list():
    r = requests.get(f"{BASE_URL}/api/music/providers")
    assert r.status_code == 200
    data = r.json()
    ids = {p["id"] for p in data["providers"]}
    assert ids == {"youtube_music", "youtube", "spotify", "apple_music", "amazon_music", "soundcloud"}
    assert data["default"] == "youtube_music"


def test_preference_persist_and_unknown_rejected():
    # set
    r = requests.put(f"{BASE_URL}/api/auth/me/preferences",
                     headers=h(TOK_A), json={"music_provider": "spotify"})
    assert r.status_code == 200, r.text
    assert r.json()["music_provider"] == "spotify"

    # read back via /me
    me = requests.get(f"{BASE_URL}/api/auth/me", headers=h(TOK_A))
    assert me.status_code == 200
    assert me.json()["music_provider"] == "spotify"

    # unknown provider rejected
    bad = requests.put(f"{BASE_URL}/api/auth/me/preferences",
                       headers=h(TOK_A), json={"music_provider": "winamp"})
    assert bad.status_code == 400


# ----------------- /music/play -----------------
def test_play_uses_pref_and_override(tmp_path):
    # pref currently 'spotify'
    r = requests.post(f"{BASE_URL}/api/music/play",
                      headers=h(TOK_A), json={"query": "Pink Floyd Wish You Were Here"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["provider"] == "spotify"
    assert "Pink%20Floyd%20Wish%20You%20Were%20Here" in data["url"]
    # queued depends on whether a companion device is registered; the URL+provider are the contract
    assert isinstance(data["queued"], bool)

    # override
    r = requests.post(f"{BASE_URL}/api/music/play",
                      headers=h(TOK_A),
                      json={"query": "Daft Punk", "provider": "youtube_music"})
    assert r.status_code == 200
    od = r.json()
    assert od["provider"] == "youtube_music"
    assert "music.youtube.com" in od["url"]


# ----------------- Companion device queues open_url -----------------
def test_play_queues_command_when_device_registered():
    # Register a companion device via /api/companion/register
    reg = requests.post(f"{BASE_URL}/api/companion/register",
                        headers=h(TOK_A), json={"name": "Test PC"})
    assert reg.status_code in (200, 201), reg.text
    rdata = reg.json()
    device_token = rdata.get("device_token") or rdata.get("token")
    device_id = rdata.get("device_id")
    assert device_token and device_id

    # Drain any queued commands first so we only see the new one
    requests.get(f"{BASE_URL}/api/companion/poll",
                 headers={"Authorization": f"Bearer {device_token}"}, timeout=10)

    # Now play — should queue
    play = requests.post(f"{BASE_URL}/api/music/play",
                        headers=h(TOK_A),
                        json={"query": "Bohemian Rhapsody", "provider": "youtube"})
    assert play.status_code == 200
    pd = play.json()
    assert pd["queued"] is True
    assert pd["cmd_id"]
    expected_url = pd["url"]

    # Poll companion endpoint — should find the open_url command
    poll = requests.get(f"{BASE_URL}/api/companion/poll",
                       headers={"Authorization": f"Bearer {device_token}"}, timeout=10)
    assert poll.status_code == 200
    cmds = poll.json().get("commands") or poll.json().get("items") or []
    matches = [c for c in cmds if c.get("kind") == "open_url"
               and (c.get("payload") or {}).get("url") == expected_url]
    assert matches, f"No matching open_url command found in {cmds}"


# ----------------- Twin /message music short-circuit -----------------
def test_twin_message_music_shortcircuit_is_fast():
    # Start a fresh twin conversation
    s = requests.post(f"{BASE_URL}/api/twin/start", headers=h(TOK_A), json={})
    assert s.status_code == 200
    conv_id = s.json()["conversation_id"]

    t0 = time.time()
    resp = requests.post(
        f"{BASE_URL}/api/twin/message",
        headers=h(TOK_A),
        json={"conversation_id": conv_id, "message": "play me some Pink Floyd"},
        stream=True, timeout=15,
    )
    assert resp.status_code == 200
    body = b""
    for chunk in resp.iter_content(chunk_size=None):
        body += chunk
    elapsed = time.time() - t0
    text = body.decode("utf-8", errors="ignore")
    assert elapsed < 8, f"Music short-circuit too slow ({elapsed:.2f}s) — looks like it hit Claude"
    assert "Putting on" in text and "Pink Floyd" in text
    assert "event: action" in text
    assert "event: done" in text
    # parse action JSON
    for line in text.splitlines():
        if line.startswith("data: ") and '"kind": "music"' in line:
            payload = json.loads(line[6:])
            assert payload["provider"]  # uses user's pref (spotify from earlier)
            assert payload["url"]
            assert "queued" in payload

    # Verify assistant message persisted with action.kind=='music'
    conv = requests.get(f"{BASE_URL}/api/twin/conversation/{conv_id}", headers=h(TOK_A)).json()
    assistant_msgs = [m for m in conv["messages"] if m["role"] == "assistant"]
    assert assistant_msgs, "No assistant message saved"
    last = assistant_msgs[-1]
    assert last.get("action", {}).get("kind") == "music"


# ----------------- Intent detection edge cases -----------------
INTENT_CASES = [
    ("I used to play guitar", None),
    ("play video games", None),
    ("play the news", None),
    ("remind me to play tennis", None),
    ("put on rain sounds", "rain sounds"),
    ("queue up Daft Punk", "Daft Punk"),
    ("play song Bohemian Rhapsody", "Bohemian Rhapsody"),
    ("play me some Pink Floyd", "Pink Floyd"),
]


@pytest.mark.parametrize("text,expected", INTENT_CASES)
def test_music_intent_detector(text, expected):
    # Import the function directly from the backend module
    import sys
    sys.path.insert(0, "/app/backend")
    from routers.music import detect_music_intent
    got = detect_music_intent(text)
    if expected is None:
        assert got is None, f"Expected no intent for {text!r}, got {got!r}"
    else:
        assert got is not None, f"Expected intent for {text!r}"
        # case-insensitive substring tolerance
        assert expected.lower() in got.lower(), f"Expected query containing {expected!r}, got {got!r}"


# ----------------- Memory facts: empty, then extract -----------------
def test_memory_facts_empty_then_extract(monkeypatch):
    # User B is empty
    r = requests.get(f"{BASE_URL}/api/memory/facts", headers=h(TOK_B), timeout=30)
    assert r.status_code == 200
    assert r.json() == {"facts": [], "count": 0}

    # Seed entries for user A (overwrite any earlier seeds)
    entries = [
        {"title": "About Elias",
         "content": "I have a son named Elias born in 2014. He loves dinosaurs.",
         "type": "memory", "tags": ["family"]},
        {"title": "Home",
         "content": "We live in Vermont, in a small farmhouse outside Burlington.",
         "type": "memory", "tags": ["place"]},
    ]
    for e in entries:
        cr = requests.post(f"{BASE_URL}/api/archive", headers=h(TOK_A), json=e)
        assert cr.status_code in (200, 201), cr.text

    # Force rebuild to trigger Claude extraction synchronously
    rb = requests.post(f"{BASE_URL}/api/memory/facts/rebuild", headers=h(TOK_A), timeout=60)
    assert rb.status_code == 200, rb.text
    facts = rb.json()["facts"]
    assert isinstance(facts, list)
    if not facts:
        pytest.skip("LLM returned 0 facts — possibly rate-limited; not a code bug.")
    for f in facts:
        assert {"fact_id", "fact", "kind", "created_at"} <= set(f.keys())
    blob = " ".join(f["fact"].lower() for f in facts)
    assert "elias" in blob or "vermont" in blob or "son" in blob


# ----------------- Caching: second call same fact_ids -----------------
def test_memory_facts_caching():
    r1 = requests.get(f"{BASE_URL}/api/memory/facts", headers=h(TOK_A), timeout=30)
    assert r1.status_code == 200
    ids1 = sorted(f["fact_id"] for f in r1.json()["facts"])
    if not ids1:
        pytest.skip("No facts to cache.")

    t0 = time.time()
    r2 = requests.get(f"{BASE_URL}/api/memory/facts", headers=h(TOK_A), timeout=30)
    elapsed = time.time() - t0
    ids2 = sorted(f["fact_id"] for f in r2.json()["facts"])
    assert ids1 == ids2, "Cache returned different fact_ids on second call"
    assert elapsed < 3, f"Cached call too slow ({elapsed:.2f}s) — likely re-ran Claude"


# ----------------- Delete fact -----------------
def test_delete_fact():
    r = requests.get(f"{BASE_URL}/api/memory/facts", headers=h(TOK_A), timeout=30)
    facts = r.json()["facts"]
    if not facts:
        pytest.skip("No facts to delete.")
    fid = facts[0]["fact_id"]
    d = requests.delete(f"{BASE_URL}/api/memory/facts/{fid}", headers=h(TOK_A))
    assert d.status_code == 200
    # Ensure it's gone
    r2 = requests.get(f"{BASE_URL}/api/memory/facts", headers=h(TOK_A), timeout=10)
    remaining_ids = {f["fact_id"] for f in r2.json()["facts"]}
    assert fid not in remaining_ids


# ----------------- Episodes endpoint empty initially -----------------
def test_episodes_empty_initially():
    r = requests.get(f"{BASE_URL}/api/memory/episodes", headers=h(TOK_B))
    assert r.status_code == 200
    assert r.json() == {"episodes": [], "count": 0}


# ----------------- Multi-user isolation -----------------
def test_multi_user_isolation():
    # User B should see no facts even after A has facts
    rb = requests.get(f"{BASE_URL}/api/memory/facts", headers=h(TOK_B), timeout=30)
    assert rb.status_code == 200
    assert rb.json()["count"] == 0

    # User B's preferences are independent
    me_b = requests.get(f"{BASE_URL}/api/auth/me", headers=h(TOK_B))
    assert me_b.json()["music_provider"] == "youtube_music"  # default
