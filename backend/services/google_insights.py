"""YouTube + Search Console via the same Google OAuth tap. Read-only.

We do not invent rankings: Search Console numbers come from Google for sites
the owner already verified. YouTube is a channel list, not a video upload
(uploads need a video file).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests

from services.google_workspace import DOCS_EXPIRED, DOCS_RECONNECT, _raise_google

YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
WEBMASTERS_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

GSC_RECONNECT = (
    "Search Console isn't shared yet. Tap Connect Gmail again so Google can "
    "share search numbers for sites you already verified. We never see your password."
)
YT_RECONNECT = (
    "YouTube isn't shared yet. Tap Connect Gmail again. We never see your password."
)


def scope_has_youtube(scope: str) -> bool:
    text = (scope or "").lower()
    return "youtube.readonly" in text or "auth/youtube" in text


def scope_has_search_console(scope: str) -> bool:
    return "webmasters" in (scope or "").lower()


def list_youtube_channel(access_token: str) -> dict[str, Any]:
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"part": "snippet,statistics", "mine": "true"},
        timeout=20,
    )
    _raise_google(resp, DOCS_EXPIRED, YT_RECONNECT)
    items = (resp.json() or {}).get("items") or []
    if not items:
        return {"summary": "No YouTube channel on this Google account yet.", "videos": []}
    ch = items[0] if isinstance(items[0], dict) else {}
    snippet = ch.get("snippet") or {}
    stats = ch.get("statistics") or {}
    videos = list_recent_youtube_videos(access_token)
    title = snippet.get("title") or "YouTube"
    lines = [
        f"YouTube channel: {title}",
        f"Subscribers: {stats.get('subscriberCount', 'hidden')}",
        f"Videos: {stats.get('videoCount', '?')}",
        "",
        "Recent uploads:",
    ]
    for vid in videos:
        lines.append(f"- {vid.get('title')} https://youtu.be/{vid.get('id')}".strip())
    if not videos:
        lines.append("(none yet)")
    return {
        "channel": title,
        "videos": videos,
        "summary": "\n".join(lines),
    }


def list_recent_youtube_videos(access_token: str) -> list[dict[str, str]]:
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "part": "snippet",
            "forMine": "true",
            "type": "video",
            "maxResults": "6",
            "order": "date",
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        return []
    out: list[dict[str, str]] = []
    for item in (resp.json() or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        vid = ((item.get("id") or {}) if isinstance(item.get("id"), dict) else {}).get("videoId") or ""
        title = ((item.get("snippet") or {}) if isinstance(item.get("snippet"), dict) else {}).get("title") or "Untitled"
        if vid:
            out.append({"id": str(vid), "title": str(title)})
    return out


def format_search_console(plan: dict[str, Any]) -> str:
    site = plan.get("site") or ""
    rows = plan.get("queries") or []
    if not site:
        return plan.get("summary") or GSC_RECONNECT
    lines = [
        f"Search Console for {site} (last {plan.get('days') or 28} days).",
        "These are Google's numbers for sites you verified — not guesses.",
        "",
    ]
    if not rows:
        lines.append("No query rows in this window (or the property is too new).")
        return "\n".join(lines)
    lines.append("Top searches:")
    for row in rows[:12]:
        q = row.get("query") or ""
        clicks = row.get("clicks")
        imp = row.get("impressions")
        pos = row.get("position")
        lines.append(f"- {q} — clicks {clicks:.0f}, shown {imp:.0f}, avg position {pos:.1f}")
    return "\n".join(lines)


def search_console_report(access_token: str, site_url: str = "", days: int = 28) -> dict[str, Any]:
    days = max(7, min(int(days or 28), 90))
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    site = (site_url or "").strip()
    if not site:
        listed = requests.get(
            "https://www.googleapis.com/webmasters/v3/sites",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        _raise_google(listed, DOCS_EXPIRED, GSC_RECONNECT)
        entries = (listed.json() or {}).get("siteEntry") or []
        urls = [
            str(e.get("siteUrl"))
            for e in entries
            if isinstance(e, dict) and e.get("siteUrl")
        ]
        if not urls:
            return {
                "site": "",
                "queries": [],
                "days": days,
                "summary": (
                    "No Search Console sites on this Google account. Add your website "
                    "in search.google.com/search-console first, then ask again."
                ),
            }
        site = urls[0]
    encoded = quote(site, safe="")
    resp = requests.post(
        f"https://www.googleapis.com/webmasters/v3/sites/{encoded}/searchAnalytics/query",
        headers=headers,
        json={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["query"],
            "rowLimit": 12,
        },
        timeout=25,
    )
    _raise_google(resp, DOCS_EXPIRED, GSC_RECONNECT)
    raw_rows = (resp.json() or {}).get("rows") or []
    queries: list[dict[str, Any]] = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        keys = row.get("keys") or []
        queries.append({
            "query": str(keys[0]) if keys else "",
            "clicks": float(row.get("clicks") or 0),
            "impressions": float(row.get("impressions") or 0),
            "position": float(row.get("position") or 0),
        })
    plan = {"site": site, "queries": queries, "days": days}
    plan["summary"] = format_search_console(plan)
    return plan
