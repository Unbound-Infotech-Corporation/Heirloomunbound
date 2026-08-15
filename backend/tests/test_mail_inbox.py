"""Inbox helpers for twin email — no Mongo, no live Gmail."""
from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.mail_inbox import (
    GMAIL_SETUP_QUERY,
    SETUP_TERMS,
    draft_preview,
    extract_links,
    looks_like_setup,
    rfc822_raw,
    snippet_safe,
    valid_recipient,
)


def test_setup_query_covers_grandmother_installers():
    q = GMAIL_SETUP_QUERY.lower()
    assert "newer_than:21d" in q
    for term in ("pinokio", "comfyui", "ollama", "heirloom"):
        assert term in q
    assert "magic link" in SETUP_TERMS


def test_extract_links_keeps_http_drops_localhost():
    text = "click https://github.com/pinokiofactory/app and http://localhost/secret and https://ollama.com/verify"
    links = extract_links(text)
    assert "https://github.com/pinokiofactory/app" in links
    assert "https://ollama.com/verify" in links
    assert all("localhost" not in u for u in links)


def test_snippet_redacts_password_and_card_keeps_otp():
    cleaned = snippet_safe("password: hunter2 card 4111111111111111 code 482193")
    assert "hunter2" not in cleaned
    assert "[hidden]" in cleaned
    assert "[card hidden]" in cleaned
    assert "482193" in cleaned


def test_looks_like_setup_and_not_spam():
    assert looks_like_setup("Verify your Heirloom login", "magic link inside", "noreply@heirloom.app")
    assert looks_like_setup("Pinokio", "confirm your email", "hello@pinokio.computer")
    assert not looks_like_setup("Your weekly newsletter", "recipes and tips", "news@example.com")


def test_valid_recipient():
    assert valid_recipient("grandma@example.com")
    assert not valid_recipient("not-an-email")
    assert not valid_recipient("a b@c.com")
    assert not valid_recipient("")


def test_rfc822_and_draft_are_sendable_shape():
    raw = rfc822_raw("a@b.com", "Hello", "Body text")
    pad = "=" * (-len(raw) % 4)
    decoded = base64.urlsafe_b64decode(raw + pad).decode("utf-8", errors="replace")
    assert "a@b.com" in decoded
    assert "Hello" in decoded
    inner = base64.b64decode(decoded.split("\n\n", 1)[-1]).decode("utf-8")
    assert "Body text" in inner
    preview = draft_preview("a@b.com", "Hello", "Body text")
    assert "confirmed=true" in preview
    assert "To: a@b.com" in preview


def test_catalog_files_declare_email_tools():
    root = Path(__file__).resolve().parents[1]
    abilities = (root / "abilities.py").read_text()
    tools = (root / "twin_tools.py").read_text()
    assert '"id": "email"' in abilities
    for name in ("read_inbox", "search_mail", "find_setup_mail", "send_email"):
        assert name in abilities
        assert name in tools
        assert f'"{name}": exec_{name}' in tools or f"'{name}': exec_{name}" in tools
