"""Unit tests for Retell helpers (no network)."""
from __future__ import annotations

import hashlib
import hmac

import phone_retell as retell


def test_verify_webhook_signature(monkeypatch):
    monkeypatch.setenv("RETELL_API_KEY", "secret-key")
    body = b'{"event":"call_ended"}'
    sig = hmac.new(b"secret-key", body, hashlib.sha256).hexdigest()
    assert retell.verify_webhook_signature(body, sig) is True
    assert retell.verify_webhook_signature(body, "sha256=" + sig) is True
    assert retell.verify_webhook_signature(body, "nope") is False
    assert retell.verify_webhook_signature(body, "") is False


def test_latest_user_text_skips_agent():
    transcript = [
        {"role": "agent", "content": "Hey."},
        {"role": "user", "content": "Where did you grow up?"},
        {"role": "agent", "content": "Vermont."},
    ]
    assert retell.latest_user_text(transcript) == "Where did you grow up?"
    assert retell.agent_has_spoken(transcript) is True
    assert retell.latest_user_text([]) == ""


def test_spoken_reply_end_and_transfer():
    bye = retell.spoken_reply("Goodbye.", response_id=4, end_call=True)
    assert bye["end_call"] is True
    assert bye["content_complete"] is True
    xfer = retell.spoken_reply("One moment.", response_id=5, transfer_number="+15551212")
    assert xfer["transfer_number"] == "+15551212"


def test_urls_from_public_backend(monkeypatch):
    monkeypatch.setenv("PUBLIC_BACKEND_URL", "https://voice.example.com")
    monkeypatch.delenv("REACT_APP_BACKEND_URL", raising=False)
    assert retell.llm_websocket_url() == "wss://voice.example.com/api/phone/retell/llm"
    assert retell.webhook_url() == "https://voice.example.com/api/phone/retell/webhook"


def test_event_key():
    assert retell.event_key("call_ended", "abc") == "call_ended:abc"


def test_for_speech_strips_citations():
    assert retell.for_speech("Grew up in Vermont. [#12]") == "Grew up in Vermont."
    assert retell.for_speech("**Hey.**  I remember.") == "Hey. I remember."


def test_format_transcript_names_the_caller():
    blob = retell.format_transcript(
        [
            {"role": "agent", "content": "Hey Sam. It's Alex."},
            {"role": "user", "content": "Where did you grow up?"},
        ],
        caller_name="Sam",
    )
    assert "Twin: Hey Sam. It's Alex." in blob
    assert "Sam: Where did you grow up?" in blob
    assert retell.format_transcript("already a string") == "already a string"
