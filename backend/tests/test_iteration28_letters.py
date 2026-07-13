"""Iteration 28 — Letters assist + auto-delivery + regression."""
import os
import time
import requests
import pytest
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
TOKEN = "test_session_fork23"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update(HEADERS)
    return sess


# ---------- Letters CRUD regression ----------
def test_letters_list(s):
    r = s.get(f"{BASE_URL}/api/letters")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_letters_full_crud(s):
    # Create
    r = s.post(f"{BASE_URL}/api/letters", json={
        "title": "TEST_iter28 crud", "body": "hello world body", "trigger": "on_release"
    })
    assert r.status_code == 200, r.text
    lt = r.json()
    assert lt["title"] == "TEST_iter28 crud"
    assert lt["sealed"] is False
    lid = lt["letter_id"]

    # Seal
    r = s.post(f"{BASE_URL}/api/letters/{lid}/seal")
    assert r.status_code == 200
    assert r.json()["sealed"] is True

    # GET verifies sealed persisted
    r = s.get(f"{BASE_URL}/api/letters/{lid}")
    assert r.status_code == 200
    assert r.json()["sealed"] is True

    # Delete
    r = s.delete(f"{BASE_URL}/api/letters/{lid}")
    assert r.status_code == 200

    # 404 after delete
    r = s.get(f"{BASE_URL}/api/letters/{lid}")
    assert r.status_code == 404


# ---------- /letters/assist ----------
def test_assist_empty_notes(s):
    r = s.post(f"{BASE_URL}/api/letters/assist", json={"notes": ""})
    assert r.status_code in (400, 422), r.text


def test_assist_success(s):
    r = s.post(f"{BASE_URL}/api/letters/assist", json={
        "notes": "For my daughter's 18th birthday. Remember our Saturday morning pancake tradition and the maple tree we planted.",
        "recipient_name": "Elena",
        "occasion": "18th birthday",
        "tone": "warm and sincere",
    }, timeout=60)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "title" in data and "body" in data
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["body"], str) and len(data["body"]) > 50
    # Should be first-person and touch on the notes' keywords
    body_lower = data["body"].lower()
    assert any(w in body_lower for w in ("i ", "i'", "my "))
    print(f"ASSIST TITLE: {data['title']}")
    print(f"ASSIST BODY (first 200): {data['body'][:200]}")


# ---------- /letters/run-delivery ----------
def test_run_delivery_shape_no_due(s):
    # Clean state assumed (no due letters).
    r = s.post(f"{BASE_URL}/api/letters/run-delivery")
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d.keys()) >= {"delivered", "skipped", "considered"}
    assert all(isinstance(d[k], int) for k in ("delivered", "skipped", "considered"))


def test_run_delivery_considers_due_letter(s):
    # Create a heir with an email
    hr = s.post(f"{BASE_URL}/api/heirs", json={
        "name": "TEST_iter28 heir",
        "email": "test.heir.iter28@example.com",
        "relationship": "child",
    })
    assert hr.status_code in (200, 201), hr.text
    heir_id = hr.json()["heir_id"]

    # Create an on_date letter with past date, sealed, linked to heir
    r = s.post(f"{BASE_URL}/api/letters", json={
        "title": "TEST_iter28 due letter",
        "body": "This is a due letter for delivery testing.",
        "recipient_heir_id": heir_id,
        "trigger": "on_date",
        "delivery_date": "2020-01-01",
    })
    assert r.status_code == 200, r.text
    lid = r.json()["letter_id"]
    s.post(f"{BASE_URL}/api/letters/{lid}/seal").raise_for_status()

    # Run delivery
    r = s.post(f"{BASE_URL}/api/letters/run-delivery")
    assert r.status_code == 200
    d = r.json()
    assert d["considered"] >= 1, d
    # delivered + skipped should be >= 1 too (either sent or email service in test mode)
    assert (d["delivered"] + d["skipped"]) >= 1

    # Cleanup: delete letter (if not delivered) + heir
    # If delivered, cannot delete — but we still delete heir.
    lt = s.get(f"{BASE_URL}/api/letters/{lid}").json()
    if not lt.get("delivered"):
        s.delete(f"{BASE_URL}/api/letters/{lid}")
    s.delete(f"{BASE_URL}/api/heirs/{heir_id}")
