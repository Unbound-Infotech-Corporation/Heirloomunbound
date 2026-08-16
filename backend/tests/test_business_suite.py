"""Business suite — Docs, Sheets, SEO, social (no Mongo, no live Google)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from services.google_workspace import (
    DOCS_RECONNECT,
    business_plan_outline,
    doc_preview,
    normalize_headers,
    normalize_rows,
    scope_has_docs,
    scope_has_sheets,
    sheet_preview,
)
from services.seo_campaign import (
    assemble_campaign,
    campaign_as_sheet,
    format_campaign,
    keyword_ideas,
)
from services.social_post import (
    SOCIAL_CONNECT,
    TWITTER_MAX,
    clip_post,
    normalize_network,
    post_preview,
)


def test_scope_detects_docs_and_sheets_not_gmail_only():
    full = (
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/documents "
        "https://www.googleapis.com/auth/spreadsheets "
        "https://www.googleapis.com/auth/drive.file"
    )
    assert scope_has_docs(full)
    assert scope_has_sheets(full)
    assert not scope_has_docs("gmail.readonly gmail.send calendar.events")
    assert not scope_has_sheets("gmail.readonly")
    assert not scope_has_docs("https://www.googleapis.com/auth/drive.file")
    assert not scope_has_sheets("https://www.googleapis.com/auth/drive.file")
    assert "password" not in DOCS_RECONNECT.lower() or "never see your password" in DOCS_RECONNECT.lower()


def test_previews_require_confirm():
    d = doc_preview("Cafe plan", "We roast beans in Vermont.")
    assert "confirmed=true" in d
    assert "Cafe plan" in d
    assert "Vermont" in d
    s = sheet_preview("Keywords", ["Phrase", "Intent"], [["coffee shop", "near me"]])
    assert "confirmed=true" in s
    assert "Keywords" in s
    assert "coffee shop" in s


def test_normalize_table_from_messy_llm_shapes():
    headers = normalize_headers("Month, Spend, Notes")
    assert headers == ["Month", "Spend", "Notes"]
    rows = normalize_rows(
        [["Jan", "100"], "Feb, 80, ads", {"a": "Mar", "b": "90", "c": "flyers"}],
        column_count=3,
    )
    assert rows[0] == ["Jan", "100", ""]
    assert rows[1][0] == "Feb"
    assert len(rows) == 3


def test_business_plan_outline_is_plain_language():
    text = business_plan_outline("Maple Co", "maple syrup", "gift buyers")
    assert "Maple Co" in text
    assert "maple syrup" in text
    assert "gift buyers" in text
    assert "90 days" in text.lower() or "Month 1" in text


def test_seo_campaign_does_not_invent_rankings():
    plan = assemble_campaign(
        "maple syrup",
        location="Vermont",
        audience="gift buyers",
        results=[{"title": "Best maple syrup gifts 2026", "href": "https://example.com/gifts"}],
    )
    blob = format_campaign(plan)
    assert "not secret Google rankings" in blob.lower() or "not secret" in plan["honest"].lower()
    assert any("Vermont" in k or "vermont" in k.lower() for k in plan["keywords"]) or "maple syrup in Vermont" in plan["keywords"]
    assert len(plan["posts"]) == 4
    headers, rows = campaign_as_sheet(plan)
    assert headers == ["Kind", "Item"]
    assert any(r[0] == "phrase" for r in rows)
    ideas = keyword_ideas("bakery", "Austin")
    assert "bakery in Austin" in ideas
    assert all("volume" not in k.lower() for k in ideas)


def test_social_clips_tweets_and_requires_confirm():
    assert normalize_network("X") == "twitter"
    assert normalize_network("linkedin") == "linkedin"
    assert normalize_network("facebook") == ""
    short, warn = clip_post("hello from the shop", "twitter")
    assert short == "hello from the shop"
    assert warn is None
    long_text = "x" * 400
    clipped, warn = clip_post(long_text, "twitter")
    assert len(clipped) <= TWITTER_MAX
    assert warn
    preview = post_preview("twitter", "Come by Saturday.")
    assert "confirmed=true" in preview
    assert "Come by Saturday" in preview
    assert "never see" in SOCIAL_CONNECT.lower()
    assert "Instagram" in SOCIAL_CONNECT


def test_catalog_and_tools_declare_business():
    abilities = (ROOT / "abilities.py").read_text(encoding="utf-8")
    tools = (ROOT / "twin_tools.py").read_text(encoding="utf-8")
    oauth = (ROOT / "routers" / "oauth.py").read_text(encoding="utf-8")
    assert '"id": "business"' in abilities
    for name in (
        "write_google_doc",
        "write_google_sheet",
        "list_workspace_files",
        "research_seo",
        "post_to_social",
        "read_search_console",
        "list_youtube",
        "write_notion_page",
    ):
        assert name in abilities
        assert name in tools
        assert f'"{name}": exec_{name}' in tools
    assert "confirmed=true" in abilities
    assert "NEVER ask for a password" in abilities
    assert "auth/documents" in oauth
    assert "auth/spreadsheets" in oauth
    assert "drive.file" in oauth
    assert "youtube.readonly" in oauth
    assert "webmasters.readonly" in oauth
    assert '@router.get("/twitter/connect")' in oauth
    assert '@router.get("/linkedin/connect")' in oauth
    assert "password" in oauth.lower()
    # Local Ollama stays out of routing providers.
    router_src = (ROOT / "services" / "llm_router.py").read_text(encoding="utf-8")
    assert '"ollama"' not in router_src.split("PROVIDERS", 1)[1].split("TASKS", 1)[0]


def test_ui_copy_is_grandmother_simple():
    settings = (REPO / "frontend" / "src" / "pages" / "Settings.jsx").read_text(encoding="utf-8")
    setup = (REPO / "frontend" / "src" / "pages" / "SetupKeys.jsx").read_text(encoding="utf-8")
    abilities = (REPO / "frontend" / "src" / "pages" / "Abilities.jsx").read_text(encoding="utf-8")
    avatar = (REPO / "frontend" / "src" / "pages" / "AvatarStudio.jsx").read_text(encoding="utf-8")
    assert "Docs, Sheets, Search, and YouTube" in setup or "Docs, and Sheets" in setup
    assert 'id: "twitter"' in setup
    assert 'id: "linkedin"' in setup
    assert 'id: "discord"' in setup
    assert 'id: "notion"' in setup
    assert "briefcase" in abilities
    assert "work:" in abilities or 'work: "Work"' in abilities
    assert "write Docs" in avatar
    assert "twitter: \"X\"" in settings
    assert "linkedin: \"LinkedIn\"" in settings
    assert "Share Docs, Search & YouTube too" in settings
    assert "Google Drive (Calendar is live" not in settings
    assert "Instagram" in setup
    assert "Facebook" in setup
    assert "Bluesky" in setup
    assert "oauth-coming-discord" not in setup
