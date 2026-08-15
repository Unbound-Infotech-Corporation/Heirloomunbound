"""Social posts after OAuth. Never store passwords. Never post until confirmed."""
from __future__ import annotations

from typing import Optional

import requests

TWITTER_MAX = 280
LINKEDIN_MAX = 3000

SOCIAL_CONNECT = (
    "Social isn't connected. Tap Connect X or Connect LinkedIn on Settings. "
    "They will ask — we never see the password. Instagram and Facebook need extra "
    "approval from Meta, so we start with X and LinkedIn."
)
SOCIAL_EXPIRED = (
    "That social sign-in expired. Tap Connect X or Connect LinkedIn again. Never ask for a password."
)


def clip_post(text: str, network: str) -> tuple[str, Optional[str]]:
    body = " ".join((text or "").split())
    if not body:
        return "", "Need some words to post."
    network = (network or "").lower().strip()
    limit = TWITTER_MAX if network in ("twitter", "x") else LINKEDIN_MAX
    if len(body) <= limit:
        return body, None
    clipped = body[: max(0, limit - 1)].rstrip() + "…"
    return clipped, f"Shortened to {limit} characters for {network or 'this network'}."


def post_preview(network: str, text: str) -> str:
    label = "X" if network in ("twitter", "x") else ("LinkedIn" if network == "linkedin" else network)
    return (
        f"I drafted this {label} post. Ask them to confirm, then call post_to_social again "
        f"with confirmed=true.\n---\n{text}"
    )


def normalize_network(raw: str) -> str:
    name = (raw or "").strip().lower()
    if name in ("x", "twitter", "tweet"):
        return "twitter"
    if name in ("linkedin", "li"):
        return "linkedin"
    return ""


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
