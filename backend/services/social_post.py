"""Social posts after OAuth. Never store passwords. Never post until confirmed."""
from __future__ import annotations

from typing import Optional

import requests

TWITTER_MAX = 280
LINKEDIN_MAX = 3000
DISCORD_MAX = 2000
REDDIT_MAX = 40000
SLACK_MAX = 4000
WORDPRESS_MAX = 50000
PINTEREST_MAX = 800
DEFAULT_MAX = 3000

SOCIAL_CONNECT = (
    "That app isn't connected. Tap Connect on Settings (X, LinkedIn, Discord, Reddit, "
    "Pinterest, WordPress, Slack). They will ask — we never see the password. "
    "Instagram, Facebook, and Threads need extra approval from Meta. "
    "Bluesky, WhatsApp, and Telegram are not wired yet."
)
SOCIAL_EXPIRED = (
    "That sign-in expired. Tap Connect again on Settings. Never ask for a password."
)

COMING_SOON_ALIASES = {
    "facebook": "facebook",
    "fb": "facebook",
    "instagram": "instagram",
    "ig": "instagram",
    "threads": "threads",
    "bluesky": "bluesky",
    "bsky": "bluesky",
    "whatsapp": "whatsapp",
    "telegram": "telegram",
}

COMING_SOON_MESSAGES = {
    "facebook": (
        "Facebook isn't available yet — Meta has to approve the app. "
        "X, LinkedIn, Discord, Reddit, Pinterest, WordPress, and Slack work today. "
        "We never ask for a password."
    ),
    "instagram": (
        "Instagram isn't available yet — Meta has to approve the app. "
        "Start with X, LinkedIn, Pinterest, or TikTok (list only). We never ask for a password."
    ),
    "threads": (
        "Threads isn't available yet — Meta has to approve the app. "
        "X and LinkedIn work today. We never ask for a password."
    ),
    "bluesky": (
        "Bluesky isn't wired yet — their login needs extra setup we don't have. "
        "We never ask for an app password."
    ),
    "whatsapp": (
        "WhatsApp isn't a personal login we can tap — it's a business number. "
        "We never ask for your WhatsApp password."
    ),
    "telegram": (
        "Telegram uses a bot token, not your login. We don't ask for that. "
        "Try Discord or Slack instead."
    ),
}

NETWORK_ALIASES = {
    "x": "twitter",
    "twitter": "twitter",
    "tweet": "twitter",
    "linkedin": "linkedin",
    "li": "linkedin",
    "discord": "discord",
    "reddit": "reddit",
    "pinterest": "pinterest",
    "pin": "pinterest",
    "wordpress": "wordpress",
    "wp": "wordpress",
    "blog": "wordpress",
    "slack": "slack",
}

NETWORK_LABELS = {
    "twitter": "X",
    "linkedin": "LinkedIn",
    "discord": "Discord",
    "reddit": "Reddit",
    "pinterest": "Pinterest",
    "wordpress": "WordPress",
    "slack": "Slack",
}

LIMITS = {
    "twitter": TWITTER_MAX,
    "linkedin": LINKEDIN_MAX,
    "discord": DISCORD_MAX,
    "reddit": REDDIT_MAX,
    "slack": SLACK_MAX,
    "wordpress": WORDPRESS_MAX,
    "pinterest": PINTEREST_MAX,
}


def clip_post(text: str, network: str) -> tuple[str, Optional[str]]:
    body = " ".join((text or "").split())
    if not body:
        return "", "Need some words to post."
    network = (network or "").lower().strip()
    limit = LIMITS.get(network, DEFAULT_MAX)
    if len(body) <= limit:
        return body, None
    clipped = body[: max(0, limit - 1)].rstrip() + "…"
    return clipped, f"Shortened to {limit} characters for {network or 'this network'}."


def post_preview(network: str, text: str) -> str:
    label = NETWORK_LABELS.get(network, network)
    return (
        f"I drafted this {label} post. Ask them to confirm, then call post_to_social again "
        f"with confirmed=true.\n---\n{text}"
    )


def coming_soon_message(raw: str) -> str:
    key = COMING_SOON_ALIASES.get((raw or "").strip().lower(), "")
    return COMING_SOON_MESSAGES.get(key, "")


def normalize_network(raw: str) -> str:
    name = (raw or "").strip().lower()
    return NETWORK_ALIASES.get(name, "")


def post_tweet(access_token: str, text: str) -> dict:
    resp = requests.post(
        "https://api.twitter.com/2/tweets",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"text": text},
        timeout=20,
    )
    if resp.status_code == 401:
        raise RuntimeError(SOCIAL_EXPIRED)
    if resp.status_code >= 400:
        raise RuntimeError("X said no. Tap Connect X again. We never ask for a password.")
    data = resp.json() if resp.content else {}
    tweet_id = str(((data.get("data") or {}) if isinstance(data, dict) else {}).get("id") or "")
    return {"id": tweet_id, "network": "twitter"}


def post_linkedin(access_token: str, person_urn: str, text: str) -> dict:
    urn = person_urn if person_urn.startswith("urn:") else f"urn:li:person:{person_urn}"
    payload = {
        "author": urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = requests.post(
        "https://api.linkedin.com/v2/ugcPosts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json=payload,
        timeout=20,
    )
    if resp.status_code == 401:
        raise RuntimeError(SOCIAL_EXPIRED)
    if resp.status_code >= 400:
        raise RuntimeError("LinkedIn said no. Tap Connect LinkedIn again. We never ask for a password.")
    post_id = str(resp.headers.get("x-restli-id") or "")
    return {"id": post_id, "network": "linkedin"}
