"""Calendar + day-briefing helpers. No passwords. Tokens stay in oauth_connections.

Google Calendar and Microsoft Graph share the same OAuth tap as Gmail/Outlook.
Writes (create event) always go through a draft the owner must confirm.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import requests

MAX_EVENTS = 12
CALENDAR_RECONNECT = (
    "Calendar isn't shared yet. Tap Connect Gmail (or Outlook) again — "
    "Google or Microsoft will ask for calendar this time. We never see your password."
)
CALENDAR_EXPIRED = (
    "Calendar sign-in expired. Tap Connect Gmail again. Never ask for their password."
)


def scope_has_calendar(scope: str) -> bool:
    return "calendar" in (scope or "").lower()


def window_utc(*, days: int = 1) -> tuple[datetime, datetime]:
    span = max(1, min(int(days or 1), 14))
    start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end = start + timedelta(days=span)
    return start, end


def public_event(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": ev.get("title") or "(no title)",
        "start": ev.get("start") or "",
        "end": ev.get("end") or "",
        "where": ev.get("where") or "",
        "all_day": bool(ev.get("all_day")),
    }


def event_preview(title: str, start: str, end: str, where: str = "", notes: str = "") -> str:
    where_bit = f"\nWhere: {where}" if where else ""
    notes_bit = f"\nNotes: {notes[:240]}" if notes else ""
    return (
        "I drafted this calendar event. Ask them to confirm, then call create_event again with confirmed=true.\n"
        f"Title: {title}\nWhen: {start} → {end}{where_bit}{notes_bit}"
    )


def _google_when(block: Optional[dict]) -> tuple[str, bool]:
    if not isinstance(block, dict):
        return "", False
    if block.get("dateTime"):
        return str(block["dateTime"]), False
    if block.get("date"):
        return str(block["date"]), True
    return "", False


def list_google_events(access_token: str, *, days: int = 1) -> list[dict[str, Any]]:
    start, end = window_utc(days=days)
    r = requests.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "timeMin": start.isoformat().replace("+00:00", "Z"),
            "timeMax": end.isoformat().replace("+00:00", "Z"),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": str(MAX_EVENTS),
        },
        timeout=20,
    )
    if r.status_code == 401:
        raise RuntimeError(CALENDAR_EXPIRED)
    if r.status_code == 403:
        raise RuntimeError(CALENDAR_RECONNECT)
    if r.status_code >= 400:
        raise RuntimeError(f"Google Calendar said no ({r.status_code}).")
    out: list[dict[str, Any]] = []
    for item in (r.json() or {}).get("items") or []:
        start_s, all_day = _google_when(item.get("start"))
        end_s, _ = _google_when(item.get("end"))
        loc = item.get("location") or ""
        out.append({
            "title": item.get("summary") or "(no title)",
            "start": start_s,
            "end": end_s,
            "where": loc if _safe_place(loc) else "",
            "all_day": all_day,
        })
    return out


def create_google_event(access_token: str, title: str, start_iso: str, end_iso: str, *, where: str = "", notes: str = "") -> None:
    body: dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": start_iso, "timeZone": "UTC"},
        "end": {"dateTime": end_iso, "timeZone": "UTC"},
    }
    if where:
        body["location"] = where[:200]
    if notes:
        body["description"] = notes[:800]
    r = requests.post(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=body,
        timeout=20,
    )
    if r.status_code == 401:
        raise RuntimeError(CALENDAR_EXPIRED)
    if r.status_code == 403:
        raise RuntimeError(CALENDAR_RECONNECT)
    if r.status_code >= 400:
        raise RuntimeError(f"Couldn't add that to Google Calendar ({r.status_code}).")


def _graph_when(block: Optional[dict]) -> str:
    if not isinstance(block, dict):
        return ""
    return str(block.get("dateTime") or block.get("date") or "")


def list_graph_events(access_token: str, *, days: int = 1) -> list[dict[str, Any]]:
    start, end = window_utc(days=days)
    r = requests.get(
        "https://graph.microsoft.com/v1.0/me/calendarView",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Prefer": 'outlook.timezone="UTC"',
        },
        params={
            "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "$select": "subject,start,end,location,isAllDay",
            "$orderby": "start/dateTime",
            "$top": str(MAX_EVENTS),
        },
        timeout=20,
    )
    if r.status_code == 401:
        raise RuntimeError(CALENDAR_EXPIRED)
    if r.status_code == 403:
        raise RuntimeError(CALENDAR_RECONNECT)
    if r.status_code >= 400:
        raise RuntimeError(f"Outlook calendar said no ({r.status_code}).")
    out: list[dict[str, Any]] = []
    for item in (r.json() or {}).get("value") or []:
        loc = ((item.get("location") or {}).get("displayName") or "")
        out.append({
            "title": item.get("subject") or "(no title)",
            "start": _graph_when(item.get("start")),
            "end": _graph_when(item.get("end")),
            "where": loc if _safe_place(loc) else "",
            "all_day": bool(item.get("isAllDay")),
        })
    return out


def create_graph_event(access_token: str, title: str, start_iso: str, end_iso: str, *, where: str = "", notes: str = "") -> None:
    body: dict[str, Any] = {
        "subject": title,
        "start": {"dateTime": start_iso, "timeZone": "UTC"},
        "end": {"dateTime": end_iso, "timeZone": "UTC"},
    }
    if notes:
        body["body"] = {"contentType": "Text", "content": notes[:800]}
    if where:
        body["location"] = {"displayName": where[:200]}
    r = requests.post(
        "https://graph.microsoft.com/v1.0/me/events",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=body,
        timeout=20,
    )
    if r.status_code == 401:
        raise RuntimeError(CALENDAR_EXPIRED)
    if r.status_code == 403:
        raise RuntimeError(CALENDAR_RECONNECT)
    if r.status_code >= 400:
        raise RuntimeError(f"Couldn't add that to Outlook calendar ({r.status_code}).")


def _safe_place(text: str) -> bool:
    """Drop javascript: and huge blobs; keep ordinary addresses and Meet links."""
    raw = (text or "").strip()
    if not raw or len(raw) > 240:
        return False
    lower = raw.lower()
    if lower.startswith("javascript:"):
        return False
    if lower.startswith("http://") or lower.startswith("https://"):
        host = (urlparse(raw).hostname or "").lower()
        return bool(host) and host not in ("localhost", "127.0.0.1")
    return True


def format_events(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    lines = []
    for ev in rows:
        row = public_event(ev)
        where = f" @ {row['where']}" if row["where"] else ""
        lines.append(f"- {row['start'][:16]} {row['title']}{where}")
    return "\n".join(lines)
