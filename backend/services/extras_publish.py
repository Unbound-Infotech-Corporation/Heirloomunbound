"""Notion, Dropbox, Mailchimp, WordPress, Slack, Discord, Reddit, Pinterest, TikTok.

OAuth tokens only. Callers must confirm before any write.
"""
from __future__ import annotations

import json
from typing import Any

import requests

from services.oauth_catalog import USER_AGENT, extra_headers
from services.social_post import SOCIAL_EXPIRED

NOTION_VERSION = "2022-06-28"


def _fail(resp: requests.Response, reconnect: str) -> None:
    if resp.status_code == 401:
        raise RuntimeError(SOCIAL_EXPIRED)
    if resp.status_code >= 400:
        raise RuntimeError(reconnect)


def post_discord_webhook(webhook_url: str, text: str) -> dict[str, str]:
    if not webhook_url or "discord.com/api/webhooks/" not in webhook_url:
        raise RuntimeError(
            "Discord isn't connected to a channel. Tap Connect Discord and pick a channel. "
            "We never ask for a password."
        )
    resp = requests.post(webhook_url, json={"content": text[:2000]}, timeout=20)
    if resp.status_code >= 400:
        raise RuntimeError("Discord said no. Tap Connect Discord again. We never ask for a password.")
    return {"id": "", "network": "discord"}


def post_reddit(access_token: str, username: str, title: str, text: str, subreddit: str = "") -> dict[str, str]:
    sr = (subreddit or "").strip().lstrip("/")
    if sr.lower().startswith("r/"):
        sr = sr[2:]
    if not sr:
        sr = f"u_{username}" if username else ""
    if not sr:
        raise RuntimeError("Need a subreddit (like r/smallbusiness) or a connected Reddit username.")
    resp = requests.post(
        "https://oauth.reddit.com/api/submit",
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": USER_AGENT,
        },
        data={
            "api_type": "json",
            "kind": "self",
            "sr": sr,
            "title": (title or text[:80])[:300],
            "text": text,
        },
        timeout=20,
    )
    _fail(resp, "Reddit said no. Tap Connect Reddit again. We never ask for a password.")
    data = resp.json() if resp.content else {}
    j = (data.get("json") or {}) if isinstance(data, dict) else {}
    errs = j.get("errors") or []
    if errs:
        raise RuntimeError("Reddit said no. Check the subreddit name, then try again.")
    url = ((j.get("data") or {}) if isinstance(j.get("data"), dict) else {}).get("url") or ""
    return {"id": url, "network": "reddit", "url": url}


def post_pinterest(
    access_token: str,
    title: str,
    description: str,
    image_url: str,
    link: str = "",
    board_id: str = "",
) -> dict[str, str]:
    if not (image_url or "").strip().startswith("http"):
        raise RuntimeError("Pinterest needs a picture link (https://...). Add image_url, then confirm.")
    headers = extra_headers("pinterest", access_token)
    bid = (board_id or "").strip()
    if not bid:
        boards = requests.get("https://api.pinterest.com/v5/boards", headers=headers, timeout=15)
        _fail(boards, "Pinterest said no. Tap Connect Pinterest again. We never ask for a password.")
        items = (boards.json() or {}).get("items") or []
        if not items or not isinstance(items[0], dict) or not items[0].get("id"):
            raise RuntimeError("Make a Pinterest board first, then ask me to pin.")
        bid = str(items[0]["id"])
    payload: dict[str, Any] = {
        "board_id": bid,
        "title": (title or "")[:100],
        "description": (description or "")[:800],
        "media_source": {"source_type": "image_url", "url": image_url.strip()},
    }
    if (link or "").startswith("http"):
        payload["link"] = link.strip()[:2048]
    resp = requests.post("https://api.pinterest.com/v5/pins", headers=headers, json=payload, timeout=25)
    _fail(resp, "Pinterest said no. Tap Connect Pinterest again. We never ask for a password.")
    data = resp.json() if resp.content else {}
    return {"id": str((data or {}).get("id") or ""), "network": "pinterest"}


def post_wordpress(access_token: str, title: str, content: str, site_id: str = "") -> dict[str, str]:
    sid = (site_id or "").strip()
    if not sid:
        me = requests.get(
            "https://public-api.wordpress.com/rest/v1.1/me",
            headers=extra_headers("wordpress", access_token),
            timeout=15,
        )
        _fail(me, "WordPress said no. Tap Connect WordPress again. We never ask for a password.")
        sid = str((me.json() or {}).get("primary_blog") or "")
    if not sid:
        raise RuntimeError("No WordPress.com site on this account.")
    resp = requests.post(
        f"https://public-api.wordpress.com/rest/v1.1/sites/{sid}/posts/new",
        headers=extra_headers("wordpress", access_token),
        data={"title": title or "Untitled", "content": content, "status": "publish"},
        timeout=25,
    )
    _fail(resp, "WordPress said no. Tap Connect WordPress again. We never ask for a password.")
    data = resp.json() if resp.content else {}
    return {
        "id": str((data or {}).get("ID") or ""),
        "network": "wordpress",
        "url": str((data or {}).get("URL") or ""),
    }


def post_slack(access_token: str, text: str, channel: str = "") -> dict[str, str]:
    chan = (channel or "").strip() or "general"
    if chan.startswith("#"):
        chan = chan[1:]
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={**extra_headers("slack", access_token), "Content-Type": "application/json"},
        json={"channel": chan, "text": text},
        timeout=20,
    )
    _fail(resp, "Slack said no. Tap Connect Slack again. We never ask for a password.")
    data = resp.json() if resp.content else {}
    if isinstance(data, dict) and data.get("ok") is False:
        raise RuntimeError(
            "Slack needs a channel name (like general). Tap Connect Slack again if it still fails."
        )
    return {"id": str((data or {}).get("ts") or ""), "network": "slack"}


def list_tiktok_videos(access_token: str) -> dict[str, Any]:
    resp = requests.post(
        "https://open.tiktokapis.com/v2/video/list/?fields=id,title,create_time,share_url",
        headers={**extra_headers("tiktok", access_token), "Content-Type": "application/json"},
        json={"max_count": 8},
        timeout=20,
    )
    _fail(resp, "TikTok said no. Tap Connect TikTok again. We never ask for a password.")
    videos = ((resp.json() or {}).get("data") or {}).get("videos") or []
    lines = ["Recent TikToks:"]
    out = []
    for item in videos:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "TikTok")
        url = str(item.get("share_url") or "")
        out.append({"title": title, "url": url, "id": str(item.get("id") or "")})
        lines.append(f"- {title} {url}".strip())
    if len(lines) == 1:
        lines.append("(none yet, or TikTok hasn't shared the list.)")
    lines.append("Posting a new TikTok needs a video file — I can draft a caption, but I can't upload the clip yet.")
    return {"videos": out, "summary": "\n".join(lines)}


def write_notion_page(access_token: str, title: str, body: str) -> dict[str, str]:
    headers = {**extra_headers("notion", access_token), "Content-Type": "application/json"}
    search = requests.post(
        "https://api.notion.com/v1/search",
        headers=headers,
        json={"page_size": 5, "filter": {"value": "page", "property": "object"}},
        timeout=20,
    )
    _fail(search, "Notion said no. Tap Connect Notion again and share a page with Heirloom.")
    results = (search.json() or {}).get("results") or []
    parent_id = ""
    for item in results:
        if isinstance(item, dict) and item.get("id") and item.get("object") == "page":
            parent_id = str(item["id"])
            break
    if not parent_id:
        raise RuntimeError(
            "In Notion, share at least one page with Heirloom, then tap Connect Notion again."
        )
    children = []
    for chunk in _split_paragraphs(body):
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": chunk[:1900]}}],
            },
        })
    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": (title or "Untitled")[:200]}}],
            }
        },
        "children": children[:20],
    }
    resp = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload, timeout=25)
    _fail(resp, "Notion said no. Share a page with Heirloom, then try again.")
    data = resp.json() if resp.content else {}
    url = str((data or {}).get("url") or "")
    return {"id": str((data or {}).get("id") or ""), "url": url, "network": "notion"}


def save_dropbox_file(access_token: str, filename: str, body: str) -> dict[str, str]:
    name = (filename or "heirloom-note.txt").replace("\\", "/").split("/")[-1]
    if not name.lower().endswith((".txt", ".md")):
        name = name + ".txt"
    path = f"/Heirloom/{name}"
    arg = json.dumps({"path": path, "mode": "add", "autorename": True})
    resp = requests.post(
        "https://content.dropboxapi.com/2/files/upload",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Dropbox-API-Arg": arg,
            "Content-Type": "application/octet-stream",
        },
        data=(body or "").encode("utf-8"),
        timeout=25,
    )
    _fail(resp, "Dropbox said no. Tap Connect Dropbox again. We never ask for a password.")
    data = resp.json() if resp.content else {}
    return {"id": str((data or {}).get("id") or ""), "path": str((data or {}).get("path_display") or path), "network": "dropbox"}


def send_mailchimp_campaign(
    access_token: str,
    api_endpoint: str,
    subject: str,
    body: str,
    from_name: str = "Heirloom",
) -> dict[str, str]:
    base = (api_endpoint or "").rstrip("/")
    if not base:
        raise RuntimeError("Mailchimp isn't fully connected. Tap Connect Mailchimp again.")
    headers = extra_headers("mailchimp", access_token)
    lists = requests.get(f"{base}/3.0/lists", headers=headers, params={"count": 5}, timeout=15)
    _fail(lists, "Mailchimp said no. Tap Connect Mailchimp again. We never ask for a password.")
    items = (lists.json() or {}).get("lists") or []
    if not items or not isinstance(items[0], dict):
        raise RuntimeError("Make an audience (list) in Mailchimp first, then ask me to send.")
    list_id = str(items[0].get("id") or "")
    camp = requests.post(
        f"{base}/3.0/campaigns",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "type": "regular",
            "recipients": {"list_id": list_id},
            "settings": {
                "subject_line": (subject or "Hello")[:150],
                "from_name": (from_name or "Heirloom")[:100],
                "title": (subject or "Heirloom note")[:100],
            },
        },
        timeout=20,
    )
    _fail(camp, "Mailchimp said no. Tap Connect Mailchimp again.")
    cid = str((camp.json() or {}).get("id") or "")
    if not cid:
        raise RuntimeError("Mailchimp didn't create the draft.")
    html = "<p>" + (body or "").replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
    put = requests.put(
        f"{base}/3.0/campaigns/{cid}/content",
        headers={**headers, "Content-Type": "application/json"},
        json={"html": html},
        timeout=20,
    )
    _fail(put, "Mailchimp said no while saving the letter.")
    send = requests.post(f"{base}/3.0/campaigns/{cid}/actions/send", headers=headers, timeout=25)
    _fail(send, "Mailchimp wouldn't send. Check the audience, then try again.")
    return {"id": cid, "network": "mailchimp"}


def _split_paragraphs(body: str) -> list[str]:
    parts = [p.strip() for p in (body or "").split("\n\n")]
    return [p for p in parts if p][:20] or [(body or " ")[:1900]]
