"""Legacy Continuity + heir portal fidelity tests (no LLM required)."""
import os
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/workspace/backend/.env")
load_dotenv("/workspace/frontend/.env")

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")
TOKEN = "hello_world_token_123"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update(HEADERS)
    return sess


def test_legacy_status_shape(s):
    r = s.get(f"{BASE_URL}/api/legacy/status")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "readiness" in data
    assert "score" in data["readiness"]
    assert "devices" in data
    assert "heirs" in data


def test_legacy_check_in(s):
    r = s.post(f"{BASE_URL}/api/legacy/check-in")
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True
    assert r.json().get("checked_in_at")


def test_legacy_settings(s):
    r = s.put(
        f"{BASE_URL}/api/legacy/settings",
        json={
            "inactivity_days_default": 45,
            "legacy_message": "TEST leave it better than you found it.",
        },
    )
    assert r.status_code == 200, r.text
    status = s.get(f"{BASE_URL}/api/legacy/status").json()
    assert status.get("inactivity_days_default") == 45
    assert "leave it better" in (status.get("legacy_message") or "")


def test_legacy_export_zip(s):
    r = s.get(f"{BASE_URL}/api/legacy/export")
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("application/zip")
    assert r.content[:2] == b"PK"
    assert len(r.content) > 100


def test_twin_prompt_personality_unit():
    from twin_prompt import build_twin_system, format_personality_for_prompt

    blob = format_personality_for_prompt(
        {
            "summary": "You are steady and warm.",
            "top_values": ["kindness", "honesty"],
            "voice_tone": {
                "description": "plainspoken",
                "signature_phrases": ["leave it better"],
            },
        }
    )
    assert "PERSONALITY PORTRAIT" in blob
    system = build_twin_system(
        "Ada",
        memory_blob="I love Grace",
        archive_blob="[MEMORY] pancakes",
        personality_blob=blob,
        heir_mode=True,
        heir_name="Grace",
        heir_relationship="daughter",
        safe_topics=["finances"],
    )
    assert "Grace" in system
    assert "SAFE-TOPIC FENCE" in system
    assert "Do NOT take any actions" in system
    assert "PERSONALITY" in system


def test_owner_presence_blocks_false_inactivity(s):
    """After a check-in, an heir with a short inactivity window must not release."""
    # Create heir with 7-day inactivity
    r = s.post(
        f"{BASE_URL}/api/heirs",
        json={
            "name": "TEST Legacy Heir",
            "email": "legacy.heir@example.com",
            "relationship": "child",
            "inactivity_days": 7,
        },
    )
    assert r.status_code == 200, r.text
    heir_id = r.json()["heir_id"]

    # Fresh check-in
    assert s.post(f"{BASE_URL}/api/legacy/check-in").status_code == 200

    # Sweep should not release
    sweep = s.post(f"{BASE_URL}/api/heirs/check-releases")
    assert sweep.status_code == 200, sweep.text
    released_ids = [h["heir_id"] for h in sweep.json().get("released", [])]
    assert heir_id not in released_ids

    # Cleanup
    s.delete(f"{BASE_URL}/api/heirs/{heir_id}")
