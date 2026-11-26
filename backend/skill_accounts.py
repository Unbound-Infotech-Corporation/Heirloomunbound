"""Tool executors for the connected calendar and mailbox skills.

Every executor returns ``{"summary", "ui"}`` like the rest of ``twin_tools``.
Mail and calendar text is untrusted: ``local_tools`` fences it before the model
reads it, and nothing here acts on what a message says.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

NOT_CONNECTED = (
    "No {what} account is connected. The owner can connect Google or Microsoft in "
    "Settings > Skills (read and draft only)."
)

TokenFn = Callable[[str, str], Any]


async def _account(user_id: str, wanted: str = "", *, token_fn: Optional[TokenFn] = None, store: Any = None) -> tuple[str, str]:
    import account_oauth

    providers = await account_oauth.connected(user_id, store=store)
    if wanted:
        providers = [p for p in providers if p == wanted]
    for provider in providers:
        getter = token_fn or (lambda uid, pid: account_oauth.access_token(uid, pid, store=store))
        token = await getter(user_id, provider)
        if token:
            return provider, token
    return "", ""


def _http(token: str, http_factory: Optional[Callable[[str], Any]]):
    from mail_cloud import _Http

    return (http_factory or _Http)(token)


async def exec_calendar_upcoming(user_id: str, args: dict, *, token_fn=None, http_factory=None, store=None) -> dict:
    from calendar_cloud import CAL_CLASSES

    provider, token = await _account(user_id, str(args.get("account") or ""), token_fn=token_fn, store=store)
    if not provider:
        return {"summary": NOT_CONNECTED.format(what="calendar"), "ui": {"error": "not_connected"}}
    days = int(args.get("days") or 7)
    cal = CAL_CLASSES[provider](_http(token, http_factory))
    events = await asyncio.to_thread(cal.upcoming, days)
    if not events:
        return {"summary": f"No events in the next {days} day(s).", "ui": {"count": 0, "provider": provider}}
    lines = [f"{len(events)} event(s) in the next {days} day(s) (times in UTC unless shown):"]
    lines += [e.line() for e in events]
    return {"summary": "\n".join(lines), "ui": {"count": len(events), "provider": provider}}


async def exec_calendar_draft_event(user_id: str, args: dict, *, store=None, tz_name: str = "") -> dict:
    from calendar_cloud import new_draft, parse_when

    title = str(args.get("title") or "").strip()
    start = parse_when(str(args.get("when") or args.get("start") or ""), tz_name)
    if not title or start is None:
        return {"summary": "Need a title and a clear time to draft an event.", "ui": {"created": False}}
    draft = new_draft(user_id, title=title, start=start, minutes=int(args.get("minutes") or 60),
                      location=str(args.get("location") or ""))
    if store is None:
        from deps import db as store
    await store.calendar_drafts.insert_one(dict(draft))
    return {
        "summary": (
            f"Drafted '{draft['title']}' for {draft['start']} (not on the calendar yet). "
            "The owner can open the draft in Today or Settings > Skills to add it."
        ),
        "ui": {"created": True, "draft_id": draft["draft_id"], "ics": f"/api/local-skills/calendar/drafts/{draft['draft_id']}.ics"},
    }


async def exec_email_search(user_id: str, args: dict, *, token_fn=None, http_factory=None, store=None) -> dict:
    from mail_cloud import MAIL_CLASSES

    provider, token = await _account(user_id, str(args.get("account") or ""), token_fn=token_fn, store=store)
    if not provider:
        return {"summary": NOT_CONNECTED.format(what="email"), "ui": {"error": "not_connected"}}
    box = MAIL_CLASSES[provider](token, http=_http(token, http_factory))
    query = str(args.get("query") or "").strip()
    limit = min(10, max(1, int(args.get("limit") or 5)))
    rows = await asyncio.to_thread(box.search, query, limit=limit)
    if not rows:
        return {"summary": f"No email matches '{query}'." if query else "Inbox is empty.", "ui": {"count": 0}}
    lines = [f"{len(rows)} message(s){' for ' + repr(query) if query else ''}:"]
    first_body = ""
    if args.get("read_first", True):
        try:
            msgs = await asyncio.to_thread(box.get_thread, rows[0].thread_id)
            first_body = (msgs[-1].body if msgs else "")[:1500]
        except Exception:  # noqa: BLE001
            first_body = ""
    for r in rows:
        flag = " (unread)" if r.unread else ""
        lines.append(f"- [{r.thread_id}] {r.date} from {r.sender}: {r.subject}{flag}")
    if first_body:
        lines.append(f"\nNewest match, body:\n{first_body}")
    return {"summary": "\n".join(lines), "ui": {"count": len(rows), "provider": provider, "thread_ids": [r.thread_id for r in rows]}}


async def exec_email_draft(user_id: str, args: dict, *, token_fn=None, http_factory=None, store=None) -> dict:
    from mail_cloud import MAIL_CLASSES

    provider, token = await _account(user_id, str(args.get("account") or ""), token_fn=token_fn, store=store)
    if not provider:
        return {"summary": NOT_CONNECTED.format(what="email"), "ui": {"error": "not_connected"}}
    body = str(args.get("body") or "").strip()
    to = str(args.get("to") or "").strip()
    thread_id = str(args.get("thread_id") or "").strip()
    reply_to = str(args.get("reply_to") or "").strip()
    if to and "@" not in to and not reply_to:
        # Small models often put "Karen" in `to`; treat a bare name as the email to answer.
        reply_to, to = to, ""
    box = MAIL_CLASSES[provider](token, http=_http(token, http_factory))
    if body and not thread_id and reply_to:
        rows = await asyncio.to_thread(box.search, reply_to, limit=1)
        if not rows:
            return {"summary": f"No email matches '{reply_to}', so there is nothing to reply to. Ask for the address to start a new email.", "ui": {"created": False}}
        thread_id = rows[0].thread_id
    if not body or not (to or thread_id):
        return {"summary": "A draft needs a body and either a recipient or a thread to reply to.", "ui": {"created": False}}
    draft = await asyncio.to_thread(
        box.create_draft, to=to, subject=str(args.get("subject") or "").strip(), body=body, thread_id=thread_id
    )
    return {
        "summary": "Saved a draft in the owner's Drafts folder. It has NOT been sent; the owner sends it from their mail app.",
        "ui": {"created": True, "draft_id": draft.draft_id, "provider": provider, "sent": False},
    }
