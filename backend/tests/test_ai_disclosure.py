"""Disclosure is off by default and lands in the approval payload the owner sees."""
from __future__ import annotations

from ai_disclosure import AI_DISCLOSURE, disclosure_enabled, label_outbound_payload
from assignments import new_approval


def test_disclosure_defaults_off(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_AI_DISCLOSURE", raising=False)
    assert disclosure_enabled() is False
    payload = {"to": "ada@example.com", "body": "Hello Ada"}
    assert label_outbound_payload(payload, action_kind="send") == payload


def test_disclosure_labels_send_and_post_only(monkeypatch):
    monkeypatch.setenv("HEIRLOOM_AI_DISCLOSURE", "1")
    labeled = label_outbound_payload(
        {"to": "ada@example.com", "body": "Hello Ada"},
        action_kind="send",
    )
    assert labeled["body"].startswith("Hello Ada")
    assert AI_DISCLOSURE in labeled["body"]
    posted = label_outbound_payload({"text": "Note"}, action_kind="post")
    assert posted["text"].endswith(AI_DISCLOSURE)
    deleted = label_outbound_payload({"ref": "draft-1"}, action_kind="delete")
    assert deleted == {"ref": "draft-1"}
    again = label_outbound_payload(labeled, action_kind="send")
    assert again["body"].count(AI_DISCLOSURE) == 1


def test_new_approval_keeps_exact_body_when_disclosure_is_off(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_AI_DISCLOSURE", raising=False)
    approval = new_approval(
        assignment={"assignment_id": "asn_1", "user_id": "u"},
        action_kind="send_email",
        summary="Send it",
        payload={"to": "ada@example.com", "body": "Hello"},
        now="2026-10-12T00:00:00+00:00",
    )
    assert approval["action_kind"] == "send"
    assert approval["payload"]["body"] == "Hello"
    assert approval["status"] == "pending"


def test_new_approval_shows_disclosure_before_send(monkeypatch):
    monkeypatch.setenv("HEIRLOOM_AI_DISCLOSURE", "1")
    approval = new_approval(
        assignment={"assignment_id": "asn_1", "user_id": "u"},
        action_kind="send",
        summary="Send it",
        payload={"to": "ada@example.com", "body": "Hello"},
        now="2026-10-12T00:00:00+00:00",
    )
    assert approval["status"] == "pending"
    assert approval["payload"]["body"].startswith("Hello")
    assert AI_DISCLOSURE in approval["payload"]["body"]
