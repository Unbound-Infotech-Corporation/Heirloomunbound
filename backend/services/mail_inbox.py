"""Read and send the owner's own mail after OAuth.

No passwords. Tokens live in oauth_connections. The twin may read recent
mail and send only after the owner says yes. Setup help looks for
confirmation / magic-link mail (Pinokio, Ollama, Heirloom, etc.) so a
grandmother does not have to hunt her inbox.
"""
from __future__ import annotations

import base64
import re
from email.mime.text import MIMEText
from typing import Any, Optional
from urllib.parse import urlparse

import requests

MAX_MESSAGES = 8
MAX_SNIPPET = 280
MAX_BODY = 800
MAX_LINKS = 6

SETUP_TERMS = (
    "pinokio",
    "comfyui",
    "comfy ui",
    "ollama",
    "heirloom",
    "verify",
    "verification",
    "confirm your email",
    "confirm your account",
    "magic link",
    "one-time code",
    "one time code",
    "security code",
    "sign-in code",
    "signin code",
)

GMAIL_SETUP_QUERY = (
    "newer_than:21d ("
    + " OR ".join(f'"{t}"' if " " in t else t for t in SETUP_TERMS)
    + ")"
)

FOLLOW_UP_TERMS = (
    "can you",
    "could you",
    "please reply",
    "please confirm",
    "let me know",
    "waiting on",
    "waiting for",
    "rsvp",
    "need you to",
    "when you get a chance",
    "following up",
    "follow up",
    "did you get",
    "checking in",
)
NOREPLY_MARKERS = ("noreply", "no-reply", "do-not-reply", "donotreply", "mailer-daemon", "notifications@")

_LINK_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_PASSWORD_RE = re.compile(r"(password|passwd|pwd)\s*[:=]\s*\S+", re.I)


def host_is_http(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    scheme = (urlparse(url or "").scheme or "").lower()
    return scheme in ("http", "https") and bool(host) and host not in ("localhost", "127.0.0.1")


def extract_links(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in _LINK_RE.findall(text or ""):
        url = raw.rstrip(").,;]")
        if not host_is_http(url) or url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= MAX_LINKS:
            break
    return out


def snippet_safe(text: str, limit: int = MAX_SNIPPET) -> str:
    cleaned = _PASSWORD_RE.sub(r"\1: [hidden]", text or "")
    cleaned = _CARD_RE.sub("[card hidden]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def looks_like_setup(subject: str, snippet: str, sender: str) -> bool:
    blob = f"{subject} {snippet} {sender}".lower()
    return any(term in blob for term in SETUP_TERMS)


def looks_like_follow_up(subject: str, snippet: str, sender: str) -> bool:
    """Inbound mail that likely wants a human answer. Skip newsletters and robots."""
    low_sender = (sender or "").lower()
    if any(marker in low_sender for marker in NOREPLY_MARKERS):
        return False
    blob = f"{subject} {snippet}"
    if "?" in blob:
        return True
    low = blob.lower()
    return any(term in low for term in FOLLOW_UP_TERMS)


def gmail_headers(payload: Optional[dict]) -> dict[str, str]:
    headers = {}
    for row in ((payload or {}).get("headers") or []):
        name = str((row or {}).get("name") or "").lower()
        if name in ("from", "to", "subject", "date"):
            headers[name] = str((row or {}).get("value") or "")
    return headers


def gmail_plain_text(payload: Optional[dict]) -> str:
    """Walk a Gmail payload tree for text/plain (then html stripped of tags)."""
    if not isinstance(payload, dict):
        return ""
    mime = (payload.get("mimeType") or "").lower()
    data = payload.get("body", {}).get("data") if isinstance(payload.get("body"), dict) else None
    if data and mime.startswith("text/plain"):
        return _b64url_decode(data)
    parts = payload.get("parts") or []
    plains: list[str] = []
    htmls: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        nested = gmail_plain_text(part)
        child_mime = (part.get("mimeType") or "").lower()
        if child_mime.startswith("text/plain") or nested:
            plains.append(nested)
        elif child_mime.startswith("text/html"):
            htmls.append(nested or _b64url_decode((part.get("body") or {}).get("data") or ""))
    if plains:
        return "\n".join(p for p in plains if p)
    if htmls:
        return re.sub(r"<[^>]+>", " ", " ".join(htmls))
    if data:
        return _b64url_decode(data)
    return ""


def _b64url_decode(data: str) -> str:
    if not data:
        return ""
    pad = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + pad).decode("utf-8", errors="replace")
    except Exception:
        return ""


def rfc822_raw(to: str, subject: str, body: str) -> str:
    msg = MIMEText(body or "", "plain", "utf-8")
    msg["To"] = to
    msg["Subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii").rstrip("=")


def draft_preview(to: str, subject: str, body: str) -> str:
    return (
        "I drafted this. Ask them to confirm, then call send_email again with confirmed=true.\n"
        f"To: {to}\nSubject: {subject}\n\n{body[:MAX_BODY]}"
    )


def public_row(msg: dict[str, Any], *, setup: bool = False) -> dict[str, Any]:
    return {
        "from": msg.get("from") or "",
        "subject": msg.get("subject") or "(no subject)",
        "date": msg.get("date") or "",
        "snippet": snippet_safe(msg.get("snippet") or ""),
        "links": (msg.get("links") or [])[:MAX_LINKS] if setup else [],
        "setup": bool(msg.get("setup") or setup),
    }


def list_gmail(access_token: str, *, query: str = "", setup_only: bool = False) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"maxResults": MAX_MESSAGES}
    if setup_only:
        params["q"] = GMAIL_SETUP_QUERY
    elif query:
        params["q"] = str(query)[:200]
    listed = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=headers,
        params=params,
        timeout=20,
    )
    if listed.status_code == 401:
        raise RuntimeError("Gmail sign-in expired. Tap Connect my email again.")
    if listed.status_code >= 400:
        raise RuntimeError(f"Gmail said no ({listed.status_code}).")
    ids = [m.get("id") for m in (listed.json() or {}).get("messages") or [] if m.get("id")]
    out: list[dict[str, Any]] = []
    fmt = "full" if setup_only else "metadata"
    meta_headers = ["From", "Subject", "Date"]
    for mid in ids[:MAX_MESSAGES]:
        r = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
            headers=headers,
            params={"format": fmt, "metadataHeaders": meta_headers},
            timeout=20,
        )
        if r.status_code >= 400:
            continue
        data = r.json() or {}
        hdrs = gmail_headers(data.get("payload") or {})
        body = gmail_plain_text(data.get("payload") or {}) if setup_only else ""
        snippet = data.get("snippet") or body
        sender = hdrs.get("from") or ""
        subject = hdrs.get("subject") or ""
        row = {
            "from": sender,
            "subject": subject,
            "date": hdrs.get("date") or "",
            "snippet": snippet_safe(snippet, MAX_BODY if setup_only else MAX_SNIPPET),
            "links": extract_links(body or snippet) if setup_only else [],
            "setup": looks_like_setup(subject, snippet, sender),
        }
        out.append(row)
    return out


def list_graph(access_token: str, *, query: str = "", setup_only: bool = False) -> list[dict[str, Any]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "$top": str(MAX_MESSAGES),
        "$select": "subject,from,receivedDateTime,bodyPreview,body,webLink",
        "$orderby": "receivedDateTime desc",
    }
    r = requests.get(
        "https://graph.microsoft.com/v1.0/me/messages",
        headers=headers,
        params=params,
        timeout=20,
    )
    if r.status_code == 401:
        raise RuntimeError("Outlook sign-in expired. Tap Connect my email again.")
    if r.status_code >= 400:
        raise RuntimeError(f"Outlook said no ({r.status_code}).")
    needle = (query or "").strip().lower()
    out: list[dict[str, Any]] = []
    for item in (r.json() or {}).get("value") or []:
        sender = ((item.get("from") or {}).get("emailAddress") or {}).get("address") or ""
        subject = item.get("subject") or ""
        preview = item.get("bodyPreview") or ""
        body = ((item.get("body") or {}).get("content") or "") if setup_only else ""
        blob = f"{subject} {preview} {sender}".lower()
        if setup_only and not looks_like_setup(subject, preview, sender):
            continue
        if needle and needle not in blob:
            continue
        out.append({
            "from": sender,
            "subject": subject,
            "date": item.get("receivedDateTime") or "",
            "snippet": snippet_safe(preview or body, MAX_BODY if setup_only else MAX_SNIPPET),
            "links": extract_links(body or preview or item.get("webLink") or "") if setup_only else [],
            "setup": looks_like_setup(subject, preview, sender),
        })
        if len(out) >= MAX_MESSAGES:
            break
    return out


def send_gmail(access_token: str, to: str, subject: str, body: str) -> None:
    raw = rfc822_raw(to, subject, body)
    r = requests.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"raw": raw},
        timeout=20,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Gmail could not send ({r.status_code}).")


def send_graph(access_token: str, to: str, subject: str, body: str) -> None:
    r = requests.post(
        "https://graph.microsoft.com/v1.0/me/sendMail",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            }
        },
        timeout=20,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Outlook could not send ({r.status_code}).")


def valid_recipient(to: str) -> bool:
    addr = (to or "").strip()
    return "@" in addr and "." in addr.split("@")[-1] and " " not in addr and len(addr) < 200
