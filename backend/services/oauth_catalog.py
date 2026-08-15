"""Third-party OAuth apps the twin can use. Never store passwords.

Each entry is a one-tap Connect tile. Writes still draft-then-yes in the twin.
"""
from __future__ import annotations

import base64
import os
from typing import Any
from urllib.parse import urlencode

import requests

PUBLIC_BACKEND = (os.environ.get("PUBLIC_BACKEND_URL") or "").rstrip("/")
USER_AGENT = "HeirloomTwin/1.0 (https://heirloom.app)"

# Platforms we researched and skipped on purpose (grandmother-simple + OAuth-only):
# - Instagram / Facebook / Threads: Meta app review
# - Bluesky: ATProto OAuth needs PAR + DPoP + a public client-metadata URL
# - WhatsApp: Business API, not a personal OAuth tap
# - Telegram: bot token, not the owner's login
# - TikTok *publish*: needs a video file + TikTok app audit (we still connect to list)

EXTRA_OAUTH: dict[str, dict[str, Any]] = {
    "discord": {
        "label": "Discord",
        "description": "Pick a channel. The twin can post there after you say yes. Discord asks — we never see the password.",
        "authorize_url": "https://discord.com/api/oauth2/authorize",
        "token_url": "https://discord.com/api/oauth2/token",
        "scopes": "identify webhook.incoming",
        "client_id_env": "DISCORD_CLIENT_ID",
        "client_secret_env": "DISCORD_CLIENT_SECRET",
        "redirect_env": "DISCORD_REDIRECT_URI",
        "token_auth": "body",
        "accent": "#5865F2",
    },
    "reddit": {
        "label": "Reddit",
        "description": "Post to Reddit after you say yes. Reddit asks — we never see the password.",
        "authorize_url": "https://www.reddit.com/api/v1/authorize",
        "token_url": "https://www.reddit.com/api/v1/access_token",
        "scopes": "identity read submit history",
        "client_id_env": "REDDIT_CLIENT_ID",
        "client_secret_env": "REDDIT_CLIENT_SECRET",
        "redirect_env": "REDDIT_REDIRECT_URI",
        "token_auth": "basic",
        "extra_authorize": {"duration": "permanent"},
        "user_agent": True,
        "accent": "#FF4500",
    },
    "pinterest": {
        "label": "Pinterest",
        "description": "Pin a picture and a link after you say yes. Pinterest asks — we never see the password.",
        "authorize_url": "https://www.pinterest.com/oauth/",
        "token_url": "https://api.pinterest.com/v5/oauth/token",
        "scopes": "user_accounts:read boards:read pins:read pins:write",
        "client_id_env": "PINTEREST_CLIENT_ID",
        "client_secret_env": "PINTEREST_CLIENT_SECRET",
        "redirect_env": "PINTEREST_REDIRECT_URI",
        "token_auth": "basic",
        "accent": "#E60023",
    },
    "tiktok": {
        "label": "TikTok",
        "description": "See your recent TikToks. Posting a new video needs a file, so we draft captions only. TikTok asks — no password here.",
        "authorize_url": "https://www.tiktok.com/v2/auth/authorize/",
        "token_url": "https://open.tiktokapis.com/v2/oauth/token/",
        "scopes": "user.info.basic,video.list",
        "client_id_env": "TIKTOK_CLIENT_KEY",
        "client_secret_env": "TIKTOK_CLIENT_SECRET",
        "redirect_env": "TIKTOK_REDIRECT_URI",
        "token_auth": "tiktok",
        "client_id_param": "client_key",
        "accent": "#111111",
    },
    "wordpress": {
        "label": "WordPress",
        "description": "Draft or publish a WordPress.com post after you say yes. WordPress asks — we never see the password.",
        "authorize_url": "https://public-api.wordpress.com/oauth2/authorize",
        "token_url": "https://public-api.wordpress.com/oauth2/token",
        "scopes": "global",
        "client_id_env": "WORDPRESS_CLIENT_ID",
        "client_secret_env": "WORDPRESS_CLIENT_SECRET",
        "redirect_env": "WORDPRESS_REDIRECT_URI",
        "token_auth": "body",
        "accent": "#21759B",
    },
    "slack": {
        "label": "Slack",
        "description": "Post in Slack after you say yes. Slack asks — we never see the password.",
        "authorize_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "scopes": "",
        "user_scope": "chat:write,channels:read,groups:read,im:write,users:read",
        "client_id_env": "SLACK_CLIENT_ID",
        "client_secret_env": "SLACK_CLIENT_SECRET",
        "redirect_env": "SLACK_REDIRECT_URI",
        "token_auth": "body",
        "accent": "#4A154B",
    },
    "notion": {
        "label": "Notion",
        "description": "Save a page in Notion after you say yes. Notion asks — we never see the password.",
        "authorize_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "scopes": "",
        "client_id_env": "NOTION_CLIENT_ID",
        "client_secret_env": "NOTION_CLIENT_SECRET",
        "redirect_env": "NOTION_REDIRECT_URI",
        "token_auth": "notion",
        "extra_authorize": {"owner": "user"},
        "accent": "#111111",
    },
    "dropbox": {
        "label": "Dropbox",
        "description": "Save a file in Dropbox after you say yes. Dropbox asks — we never see the password.",
        "authorize_url": "https://www.dropbox.com/oauth2/authorize",
        "token_url": "https://api.dropboxapi.com/oauth2/token",
        "scopes": "files.content.write files.content.read account_info.read",
        "client_id_env": "DROPBOX_CLIENT_ID",
        "client_secret_env": "DROPBOX_CLIENT_SECRET",
        "redirect_env": "DROPBOX_REDIRECT_URI",
        "token_auth": "body",
        "extra_authorize": {"token_access_type": "offline"},
        "accent": "#0061FF",
    },
    "mailchimp": {
        "label": "Mailchimp",
        "description": "Draft a newsletter, send only after you say yes. Mailchimp asks — we never see the password.",
        "authorize_url": "https://login.mailchimp.com/oauth2/authorize",
        "token_url": "https://login.mailchimp.com/oauth2/token",
        "scopes": "",
        "client_id_env": "MAILCHIMP_CLIENT_ID",
        "client_secret_env": "MAILCHIMP_CLIENT_SECRET",
        "redirect_env": "MAILCHIMP_REDIRECT_URI",
        "token_auth": "body",
        "accent": "#FFE01B",
    },
}

RESERVED_CONNECT = {
    "spotify", "github", "google", "microsoft", "twitter", "linkedin", "connections",
}


def extra_redirect(provider: str) -> str:
    spec = EXTRA_OAUTH[provider]
    env = os.environ.get(spec["redirect_env"]) or ""
    return (env or f"{PUBLIC_BACKEND}/api/oauth/{provider}/callback").rstrip("/")


def extra_creds(provider: str) -> tuple[str, str]:
    spec = EXTRA_OAUTH[provider]
    return os.environ.get(spec["client_id_env"], ""), os.environ.get(spec["client_secret_env"], "")


def extra_ready(provider: str) -> bool:
    cid, secret = extra_creds(provider)
    return bool(cid and secret and extra_redirect(provider).startswith("http"))


def extra_headers(provider: str, access: str) -> dict[str, str]:
    spec = EXTRA_OAUTH[provider]
    headers = {"Authorization": f"Bearer {access}"}
    if spec.get("user_agent"):
        headers["User-Agent"] = USER_AGENT
    if provider == "notion":
        headers["Notion-Version"] = "2022-06-28"
    return headers


def fetch_extra_profile(provider: str, access: str, token_json: dict[str, Any]) -> dict[str, Any]:
    """Best-effort public profile for the Settings card. Never includes tokens."""
    try:
        if provider == "discord":
            me = requests.get(
                "https://discord.com/api/users/@me",
                headers=extra_headers(provider, access),
                timeout=10,
            ).json()
            hook = token_json.get("webhook") if isinstance(token_json.get("webhook"), dict) else {}
            return {
                "id": me.get("id"),
                "display_name": me.get("global_name") or me.get("username"),
                "username": me.get("username"),
                "webhook_url": hook.get("url") or "",
                "webhook_id": hook.get("id") or "",
                "channel_id": hook.get("channel_id") or "",
            }
        if provider == "reddit":
            me = requests.get(
                "https://oauth.reddit.com/api/v1/me",
                headers=extra_headers(provider, access),
                timeout=10,
            ).json()
            name = me.get("name") or ""
            return {"id": me.get("id"), "display_name": name, "username": name}
        if provider == "pinterest":
            me = requests.get(
                "https://api.pinterest.com/v5/user_account",
                headers=extra_headers(provider, access),
                timeout=10,
            ).json()
            return {
                "id": me.get("id") or me.get("username"),
                "display_name": me.get("business_name") or me.get("username"),
                "username": me.get("username"),
            }
        if provider == "tiktok":
            me = requests.get(
                "https://open.tiktokapis.com/v2/user/info/",
                headers=extra_headers(provider, access),
                params={"fields": "open_id,display_name,avatar_url"},
                timeout=10,
            ).json()
            user = ((me.get("data") or {}).get("user") if isinstance(me, dict) else {}) or {}
            return {
                "id": user.get("open_id") or token_json.get("open_id"),
                "display_name": user.get("display_name"),
                "open_id": user.get("open_id") or token_json.get("open_id"),
            }
        if provider == "wordpress":
            me = requests.get(
                "https://public-api.wordpress.com/rest/v1.1/me",
                headers=extra_headers(provider, access),
                timeout=10,
            ).json()
            return {
                "id": me.get("ID") or me.get("username"),
                "display_name": me.get("display_name") or me.get("username"),
                "username": me.get("username"),
                "primary_blog": str(me.get("primary_blog") or ""),
            }
        if provider == "slack":
            authed = token_json.get("authed_user") if isinstance(token_json.get("authed_user"), dict) else {}
            team = token_json.get("team") if isinstance(token_json.get("team"), dict) else {}
            return {
                "id": authed.get("id"),
                "display_name": team.get("name") or authed.get("id"),
                "team_id": team.get("id"),
                "user_token": True,
            }
        if provider == "notion":
            owner = token_json.get("owner") if isinstance(token_json.get("owner"), dict) else {}
            user = owner.get("user") if isinstance(owner.get("user"), dict) else {}
            return {
                "id": token_json.get("bot_id") or user.get("id"),
                "display_name": (token_json.get("workspace_name") or user.get("name") or "Notion"),
                "workspace_id": token_json.get("workspace_id"),
                "bot_id": token_json.get("bot_id"),
            }
        if provider == "dropbox":
            me = requests.post(
                "https://api.dropboxapi.com/2/users/get_current_account",
                headers=extra_headers(provider, access),
                timeout=10,
            ).json()
            name = ((me.get("name") or {}) if isinstance(me, dict) else {}).get("display_name")
            return {"id": me.get("account_id"), "display_name": name or me.get("email")}
        if provider == "mailchimp":
            meta = requests.get(
                "https://login.mailchimp.com/oauth2/metadata",
                headers=extra_headers(provider, access),
                timeout=10,
            ).json()
            return {
                "id": meta.get("user_id") or meta.get("accountname"),
                "display_name": meta.get("accountname") or meta.get("login_url"),
                "api_endpoint": meta.get("api_endpoint") or "",
                "dc": meta.get("dc") or "",
            }
    except Exception:  # noqa: BLE001
        return {"display_name": EXTRA_OAUTH[provider]["label"]}
    return {"display_name": EXTRA_OAUTH[provider]["label"]}


def slack_user_token(token_json: dict[str, Any], fallback: str) -> str:
    authed = token_json.get("authed_user") if isinstance(token_json.get("authed_user"), dict) else {}
    return str(authed.get("access_token") or fallback or "")


def build_authorize_url(provider: str, state: str) -> str:
    spec = EXTRA_OAUTH[provider]
    cid, _secret = extra_creds(provider)
    params: dict[str, str] = {
        "response_type": "code",
        "redirect_uri": extra_redirect(provider),
        "state": state,
    }
    params[str(spec.get("client_id_param") or "client_id")] = cid
    if spec.get("scopes"):
        params["scope"] = str(spec["scopes"])
    if spec.get("user_scope"):
        params["user_scope"] = str(spec["user_scope"])
    extra = spec.get("extra_authorize") or {}
    if isinstance(extra, dict):
        for key, value in extra.items():
            params[str(key)] = str(value)
    return spec["authorize_url"] + "?" + urlencode(params)


def exchange_extra_code(provider: str, code: str) -> tuple[int, dict[str, Any]]:
    """Trade an OAuth code for tokens. Never logs the code or tokens."""
    spec = EXTRA_OAUTH[provider]
    cid, secret = extra_creds(provider)
    redirect = extra_redirect(provider)
    mode = spec.get("token_auth") or "body"
    headers: dict[str, str] = {}
    if spec.get("user_agent"):
        headers["User-Agent"] = USER_AGENT
    if mode == "tiktok":
        resp = requests.post(
            spec["token_url"],
            data={
                "client_key": cid,
                "client_secret": secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect,
            },
            timeout=20,
        )
    elif mode == "notion":
        basic = base64.b64encode(f"{cid}:{secret}".encode("ascii")).decode("ascii")
        resp = requests.post(
            spec["token_url"],
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/json",
            },
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
            },
            timeout=20,
        )
    elif mode == "basic":
        resp = requests.post(
            spec["token_url"],
            auth=(cid, secret),
            headers=headers,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
            },
            timeout=20,
        )
    else:
        resp = requests.post(
            spec["token_url"],
            headers=headers,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": cid,
                "client_secret": secret,
            },
            timeout=20,
        )
    try:
        body = resp.json() if resp.content else {}
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    return resp.status_code, body


def refresh_extra_token(provider: str, refresh_token: str) -> tuple[int, dict[str, Any]]:
    spec = EXTRA_OAUTH[provider]
    cid, secret = extra_creds(provider)
    mode = spec.get("token_auth") or "body"
    headers: dict[str, str] = {}
    if spec.get("user_agent"):
        headers["User-Agent"] = USER_AGENT
    if mode == "tiktok":
        resp = requests.post(
            spec["token_url"],
            data={
                "client_key": cid,
                "client_secret": secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=20,
        )
    elif mode == "basic":
        resp = requests.post(
            spec["token_url"],
            auth=(cid, secret),
            headers=headers,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            timeout=20,
        )
    elif mode == "notion":
        return 400, {}
    else:
        resp = requests.post(
            spec["token_url"],
            headers=headers,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": cid,
                "client_secret": secret,
            },
            timeout=20,
        )
    try:
        body = resp.json() if resp.content else {}
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    return resp.status_code, body


def pick_access_token(provider: str, token_json: dict[str, Any]) -> str:
    if provider == "slack":
        return slack_user_token(token_json, str(token_json.get("access_token") or ""))
    return str(token_json.get("access_token") or "")
