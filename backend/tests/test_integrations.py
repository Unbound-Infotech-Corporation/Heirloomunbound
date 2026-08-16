"""Third-party OAuth catalog — no Mongo, no live vendor calls."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from services.google_insights import (
    GSC_RECONNECT,
    YT_RECONNECT,
    format_search_console,
    scope_has_search_console,
    scope_has_youtube,
)
from services.oauth_catalog import EXTRA_OAUTH, extra_ready, slack_user_token
from services.social_post import (
    SOCIAL_CONNECT,
    coming_soon_message,
    normalize_network,
)


EXPECTED_EXTRA = {
    "discord", "reddit", "pinterest", "tiktok", "wordpress",
    "slack", "notion", "dropbox", "mailchimp",
}


def test_catalog_covers_researched_oauth_apps():
    assert set(EXTRA_OAUTH) == EXPECTED_EXTRA
    for pid, spec in EXTRA_OAUTH.items():
        assert spec["label"]
        assert "password" in spec["description"].lower() or "no password" in spec["description"].lower()
        assert spec["authorize_url"].startswith("https://")
        assert spec["token_url"].startswith("https://")
        assert spec["client_id_env"]
        assert spec["client_secret_env"]
        assert extra_ready(pid) is False  # no secrets in unit tests


def test_tiktok_uses_client_key_not_password():
    assert EXTRA_OAUTH["tiktok"]["client_id_env"] == "TIKTOK_CLIENT_KEY"
    assert EXTRA_OAUTH["tiktok"]["token_auth"] == "tiktok"


def test_slack_prefers_user_token():
    token = slack_user_token(
        {"access_token": "bot-x", "authed_user": {"access_token": "user-x"}},
        "bot-x",
    )
    assert token == "user-x"
    assert slack_user_token({}, "fallback") == "fallback"


def test_google_insight_scopes():
    full = (
        "https://www.googleapis.com/auth/youtube.readonly "
        "https://www.googleapis.com/auth/webmasters.readonly"
    )
    assert scope_has_youtube(full)
    assert scope_has_search_console(full)
    assert not scope_has_youtube("gmail.readonly documents")
    assert not scope_has_search_console("gmail.readonly")
    assert "never see your password" in GSC_RECONNECT.lower()
    assert "never see your password" in YT_RECONNECT.lower()
    blob = format_search_console({
        "site": "https://example.com/",
        "days": 28,
        "queries": [{"query": "maple syrup", "clicks": 12, "impressions": 80, "position": 4.2}],
    })
    assert "maple syrup" in blob
    assert "not guesses" in blob.lower()


def test_social_aliases_and_coming_soon():
    assert normalize_network("discord") == "discord"
    assert normalize_network("reddit") == "reddit"
    assert normalize_network("pinterest") == "pinterest"
    assert normalize_network("wordpress") == "wordpress"
    assert normalize_network("slack") == "slack"
    assert normalize_network("facebook") == ""
    assert normalize_network("instagram") == ""
    assert "Meta" in coming_soon_message("instagram")
    assert "password" in coming_soon_message("bluesky").lower()
    assert "never see" in SOCIAL_CONNECT.lower()
    assert "Bluesky" in SOCIAL_CONNECT


def test_tools_and_oauth_routes_declare_extras():
    tools = (ROOT / "twin_tools.py").read_text(encoding="utf-8")
    abilities = (ROOT / "abilities.py").read_text(encoding="utf-8")
    oauth = (ROOT / "routers" / "oauth.py").read_text(encoding="utf-8")
    for name in (
        "read_search_console",
        "list_youtube",
        "list_tiktok",
        "write_notion_page",
        "save_to_dropbox",
        "send_mailchimp",
    ):
        assert name in tools
        assert name in abilities
        assert f'"{name}": exec_{name}' in tools
    assert "confirmed=true" in abilities
    assert "NEVER ask for a password" in abilities
    assert "youtube.readonly" in oauth
    assert "webmasters.readonly" in oauth
    assert 'EXTRA_OAUTH' in oauth
    router_src = (ROOT / "services" / "llm_router.py").read_text(encoding="utf-8")
    assert '"ollama"' not in router_src.split("PROVIDERS", 1)[1].split("TASKS", 1)[0]


def test_ui_lists_extra_tiles_and_honest_coming_soon():
    setup = (REPO / "frontend" / "src" / "pages" / "SetupKeys.jsx").read_text(encoding="utf-8")
    settings = (REPO / "frontend" / "src" / "pages" / "Settings.jsx").read_text(encoding="utf-8")
    for pid in EXPECTED_EXTRA:
        assert f'id: "{pid}"' in setup
    assert "oauth-coming-discord" not in setup
    assert 'name="Instagram"' in setup
    assert 'name="Facebook"' in setup
    assert 'name="Threads"' in setup
    assert 'name="Bluesky"' in setup
    assert 'name="WhatsApp"' in setup
    assert 'name="Telegram"' in setup
    assert "discord: \"Discord\"" in settings
    assert "Share Docs, Search & YouTube too" in settings
    secrets = (REPO / "memory" / "SECRETS_ROTATION.md").read_text(encoding="utf-8")
    assert "TIKTOK_CLIENT_KEY" in secrets
    assert "youtube.readonly" in secrets
    assert "webmasters.readonly" in secrets
