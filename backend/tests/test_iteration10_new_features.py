"""Iteration 10: Personality profile, Daily nudges, Ask-the-archive, Safe-topics fence."""
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://voice-clone-hub-20.preview.emergentagent.com").rstrip("/")
TOK_A = os.environ.get("TOK_A")
TOK_B = os.environ.get("TOK_B")
UID_A = os.environ.get("UID_A")
UID_B = os.environ.get("UID_B")

LLM_TIMEOUT = 90  # Claude can be slow


@pytest.fixture(scope="module")
def client_a():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {TOK_A}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def client_b():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {TOK_B}", "Content-Type": "application/json"})
    return s


# --- Health: confirm auth works ---
def test_auth_me(client_a):
    r = client_a.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user_id"] == UID_A
    assert "safe_topics" in data


# --- Feature 1: Personality profile ---
def test_personality_profile_generates(client_a):
    r = client_a.get(f"{BASE_URL}/api/personality/profile", timeout=LLM_TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "bigfive" in data
    bf = data["bigfive"]
    for trait in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"):
        assert trait in bf, f"missing {trait}"
        assert "score" in bf[trait] and "reason" in bf[trait]
        assert 0 <= int(bf[trait]["score"]) <= 100
    assert isinstance(data.get("top_values"), list)
    assert isinstance(data.get("voice_tone"), dict)
    assert "description" in data["voice_tone"]
    assert "signature_phrases" in data["voice_tone"]
    assert isinstance(data.get("life_themes"), list)
    assert isinstance(data.get("key_relationships"), list)
    assert data.get("summary")
    assert "entry_count" in data
    assert "generated_at" in data
    # Cache info for next test
    pytest.profile_generated_at = data["generated_at"]
    pytest.profile_entry_count = data["entry_count"]


def test_personality_profile_cached_on_second_call(client_a):
    r = client_a.get(f"{BASE_URL}/api/personality/profile", timeout=30)
    assert r.status_code == 200
    data = r.json()
    # Same entry_count and SAME generated_at because cache fresh
    assert data["entry_count"] == pytest.profile_entry_count
    assert data["generated_at"] == pytest.profile_generated_at


def test_personality_refresh_regenerates(client_a):
    r = client_a.post(f"{BASE_URL}/api/personality/refresh", timeout=LLM_TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "bigfive" in data
    assert data["generated_at"] != pytest.profile_generated_at  # new ts


# --- Feature 2: Daily nudges ---
def test_nudge_today_creates(client_a):
    r = client_a.get(f"{BASE_URL}/api/nudges/today", timeout=LLM_TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ("nudge_id", "title", "body", "action_type", "action_prompt", "date_key", "status"):
        assert k in data, f"missing {k}"
    assert data["status"] == "open"
    pytest.nudge_id = data["nudge_id"]
    pytest.nudge_date = data["date_key"]


def test_nudge_today_idempotent(client_a):
    r = client_a.get(f"{BASE_URL}/api/nudges/today", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data["nudge_id"] == pytest.nudge_id
    assert data["date_key"] == pytest.nudge_date


def test_nudge_dismiss(client_a):
    r = client_a.patch(
        f"{BASE_URL}/api/nudges/{pytest.nudge_id}", json={"status": "dismissed"}, timeout=15
    )
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "dismissed"


def test_nudge_history(client_a):
    r = client_a.get(f"{BASE_URL}/api/nudges/history", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert any(n.get("nudge_id") == pytest.nudge_id for n in data)


# --- Feature 3: Ask the archive ---
def test_archive_ask_returns_answer_with_citations(client_a):
    r = client_a.post(
        f"{BASE_URL}/api/archive/ask",
        json={"question": "What did I learn from my dad?"},
        timeout=LLM_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "answer" in data and data["answer"]
    assert "citations" in data and isinstance(data["citations"], list)
    if data["citations"]:
        c = data["citations"][0]
        for k in ("entry_id", "title", "type", "snippet", "created_at"):
            assert k in c, f"missing {k} in citation"


def test_archive_ask_empty_archive(client_b):
    """User B has no entries — should get informative message, not error."""
    r = client_b.post(
        f"{BASE_URL}/api/archive/ask",
        json={"question": "Tell me about my dad"},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    assert "answer" in data
    assert data["citations"] == []


# --- Feature 4: Safe-topic fence ---
def test_set_safe_topics(client_a):
    r = client_a.put(
        f"{BASE_URL}/api/auth/me/preferences",
        json={"safe_topics": ["politics", "religion"]},
        timeout=15,
    )
    assert r.status_code == 200, r.text


def test_safe_topics_persist_in_me(client_a):
    r = client_a.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert set(data.get("safe_topics") or []) >= {"politics", "religion"}


def test_twin_respects_safe_topics(client_a):
    """Send a politics question — twin should acknowledge declining. Twin uses SSE streaming."""
    start = client_a.post(f"{BASE_URL}/api/twin/start", json={}, timeout=30)
    assert start.status_code == 200, start.text
    conv_id = start.json()["conversation_id"]
    r = client_a.post(
        f"{BASE_URL}/api/twin/message",
        json={"conversation_id": conv_id, "message": "What do you think about the current presidential election? Who would you vote for?"},
        timeout=LLM_TIMEOUT,
        stream=True,
    )
    assert r.status_code == 200, r.text
    # Parse SSE stream
    import json as _json
    full = ""
    for raw in r.iter_lines(decode_unicode=True):
        if not raw:
            continue
        if raw.startswith("data: "):
            payload_str = raw[len("data: "):]
            try:
                obj = _json.loads(payload_str)
                if "text" in obj:
                    full += obj["text"]
            except Exception:
                pass
    reply = full.lower()
    assert reply, "No streamed reply"
    decline_signals = [
        "rather not", "prefer not", "won't get into", "wont get into",
        "not get into", "pivot", "different topic", "change the subject",
        "off-limits", "off limits", "decline", "steer clear", "skip",
        "stay away", "would rather", "let's talk about something",
        "not the right place", "set aside", "leave that", "another topic",
        "not something i", "not comfortable", "rather talk",
        "don't want to", "won't go there", "let's not", "rather focus",
        "leave politics", "keep politics", "not for me", "shy away",
        "duck", "pass on that", "avoid", "elsewhere",
    ]
    assert any(s in reply for s in decline_signals), f"Twin did not decline politics. Reply: {reply!r}"


# --- Multi-user isolation ---
def test_user_b_cannot_see_a_nudges(client_b):
    r = client_b.get(f"{BASE_URL}/api/nudges/history", timeout=15)
    assert r.status_code == 200
    data = r.json()
    # No A nudges leaked
    assert not any(n.get("user_id") == UID_A for n in data)
    assert not any(n.get("nudge_id") == pytest.nudge_id for n in data)


def test_user_b_safe_topics_isolated(client_b):
    r = client_b.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert r.status_code == 200
    assert "politics" not in (r.json().get("safe_topics") or [])


def test_user_b_personality_isolated(client_b):
    """B's personality should not be A's. Either empty profile or fresh-generated for B."""
    r = client_b.get(f"{BASE_URL}/api/personality/profile", timeout=LLM_TIMEOUT)
    assert r.status_code == 200
    data = r.json()
    # B has no entries, so summary should indicate empty archive
    assert data.get("entry_count", 0) == 0
    assert "empty" in (data.get("summary") or "").lower() or data.get("entry_count") == 0


def test_b_cannot_patch_a_nudge(client_b):
    r = client_b.patch(
        f"{BASE_URL}/api/nudges/{pytest.nudge_id}", json={"status": "dismissed"}, timeout=15
    )
    assert r.status_code == 404
