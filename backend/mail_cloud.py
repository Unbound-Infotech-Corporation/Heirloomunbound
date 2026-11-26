"""Gmail API and Microsoft Graph mailboxes: read and draft, never send.

Both implement ``mail_provider.MailProvider`` plus ``search``. ``send_message``
raises on both: an owner who wants a message to go out opens the draft in
their own mail app and presses send there.
"""
from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from typing import Any, Callable, Optional

from mail_provider import MailAccessError, MailDraft, MailMessage, MailThreadSummary

NEVER_SENDS = "Heirloom only reads and drafts email. Open the draft in your mail app to send it."
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
GRAPH = "https://graph.microsoft.com/v1.0/me"


class _Http:
    """requests with a bearer token. Injected in tests."""

    def __init__(self, token: str, session: Any = None):
        import requests

        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def get(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
        r = self.session.get(url, params=params, headers={**self.headers, **(headers or {})}, timeout=20)
        if r.status_code >= 400:
            raise MailAccessError(f"Mail service said HTTP {r.status_code}.")
        return r.json()

    def post(self, url: str, body: dict) -> dict:
        r = self.session.post(url, json=body, headers=self.headers, timeout=20)
        if r.status_code >= 400:
            raise MailAccessError(f"Mail service said HTTP {r.status_code}.")
        return r.json() if r.content else {}


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>", "\n", text)
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _b64(data: str) -> str:
    try:
        return base64.urlsafe_b64decode((data or "") + "=" * (-len(data or "") % 4)).decode("utf-8", "ignore")
    except (ValueError, TypeError):
        return ""


def gmail_body(payload: dict) -> str:
    """Prefer text/plain; fall back to stripped HTML."""
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict) -> None:
        mime = str(part.get("mimeType") or "")
        data = ((part.get("body") or {}).get("data")) or ""
        if mime == "text/plain" and data:
            plain.append(_b64(data))
        elif mime == "text/html" and data:
            html.append(_strip_html(_b64(data)))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload or {})
    return ("\n".join(plain) or "\n".join(html)).strip()


def _header(payload: dict, name: str) -> str:
    for h in (payload or {}).get("headers") or []:
        if str(h.get("name") or "").lower() == name.lower():
            return str(h.get("value") or "")
    return ""


class GmailApiProvider:
    provider_id = "gmail"

    def __init__(self, token: str, *, http: Any = None):
        self.http = http or _Http(token)

    def search(self, query: str = "", *, limit: int = 10) -> list[MailThreadSummary]:
        params = {"maxResults": max(1, min(limit, 25))}
        if query:
            params["q"] = query
        listed = self.http.get(f"{GMAIL}/threads", params=params)
        out: list[MailThreadSummary] = []
        for row in listed.get("threads") or []:
            meta = self.http.get(
                f"{GMAIL}/threads/{row['id']}",
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
            )
            first = (meta.get("messages") or [{}])[0]
            payload = first.get("payload") or {}
            out.append(MailThreadSummary(
                thread_id=row["id"],
                subject=_header(payload, "Subject"),
                sender=_header(payload, "From"),
                date=_header(payload, "Date"),
                unread="UNREAD" in (first.get("labelIds") or []),
            ))
        return out

    def list_threads(self, *, limit: int = 10) -> list[MailThreadSummary]:
        return self.search("in:inbox", limit=limit)

    def get_thread(self, thread_id: str) -> list[MailMessage]:
        data = self.http.get(f"{GMAIL}/threads/{thread_id}", params={"format": "full"})
        out = []
        for m in data.get("messages") or []:
            payload = m.get("payload") or {}
            out.append(MailMessage(
                thread_id=thread_id,
                subject=_header(payload, "Subject"),
                sender=_header(payload, "From"),
                to=_header(payload, "To"),
                date=_header(payload, "Date"),
                body=gmail_body(payload)[:8000],
                unread="UNREAD" in (m.get("labelIds") or []),
            ))
        return out

    def create_draft(self, *, to: str, subject: str, body: str, thread_id: str = "") -> MailDraft:
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        message: dict[str, Any] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        made = self.http.post(f"{GMAIL}/drafts", {"message": message})
        return MailDraft(draft_id=str(made.get("id") or ""), to=to, subject=subject, body=body, thread_id=thread_id)

    def send_message(self, **_: Any) -> dict[str, Any]:
        raise MailAccessError(NEVER_SENDS)


def _addr(row: dict) -> str:
    email = (row or {}).get("emailAddress") or {}
    name = str(email.get("name") or "")
    addr = str(email.get("address") or "")
    return f"{name} <{addr}>" if name and addr else (addr or name)


class OutlookMailProvider:
    provider_id = "outlook"

    def __init__(self, token: str, *, http: Any = None):
        self.http = http or _Http(token)

    def search(self, query: str = "", *, limit: int = 10) -> list[MailThreadSummary]:
        params = {"$top": max(1, min(limit, 25)), "$select": "id,conversationId,subject,from,receivedDateTime,isRead"}
        headers = None
        if query:
            params["$search"] = '"' + query.replace('"', " ") + '"'
            headers = {"ConsistencyLevel": "eventual"}
        else:
            params["$orderby"] = "receivedDateTime desc"
        data = self.http.get(f"{GRAPH}/mailFolders/inbox/messages" if not query else f"{GRAPH}/messages", params=params, headers=headers)
        return [
            MailThreadSummary(
                thread_id=str(m.get("id") or ""),
                subject=str(m.get("subject") or ""),
                sender=_addr(m.get("from") or {}),
                date=str(m.get("receivedDateTime") or ""),
                unread=not bool(m.get("isRead")),
            )
            for m in data.get("value") or []
        ]

    def list_threads(self, *, limit: int = 10) -> list[MailThreadSummary]:
        return self.search("", limit=limit)

    def get_thread(self, thread_id: str) -> list[MailMessage]:
        m = self.http.get(
            f"{GRAPH}/messages/{thread_id}",
            params={"$select": "id,subject,from,toRecipients,receivedDateTime,isRead,body"},
            headers={"Prefer": 'outlook.body-content-type="text"'},
        )
        body = (m.get("body") or {})
        text = str(body.get("content") or "")
        if str(body.get("contentType") or "").lower() == "html":
            text = _strip_html(text)
        return [MailMessage(
            thread_id=thread_id,
            subject=str(m.get("subject") or ""),
            sender=_addr(m.get("from") or {}),
            to=", ".join(_addr(r) for r in m.get("toRecipients") or []),
            date=str(m.get("receivedDateTime") or ""),
            body=text[:8000],
            unread=not bool(m.get("isRead")),
        )]

    def create_draft(self, *, to: str, subject: str, body: str, thread_id: str = "") -> MailDraft:
        if thread_id:
            made = self.http.post(f"{GRAPH}/messages/{thread_id}/createReply", {"comment": body})
        else:
            made = self.http.post(f"{GRAPH}/messages", {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": a.strip()}} for a in (to or "").split(",") if a.strip()],
            })
        return MailDraft(draft_id=str(made.get("id") or ""), to=to, subject=subject, body=body, thread_id=thread_id)

    def send_message(self, **_: Any) -> dict[str, Any]:
        raise MailAccessError(NEVER_SENDS)


MAIL_CLASSES: dict[str, Callable[..., Any]] = {"google": GmailApiProvider, "microsoft": OutlookMailProvider}
