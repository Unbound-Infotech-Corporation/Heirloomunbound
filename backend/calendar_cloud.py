"""Google Calendar and Outlook calendar, read-only, plus local event drafts.

The calendars are read with read-only grants. "Put lunch with Sam on my
calendar" makes a draft on the box (``calendar_drafts``) with an .ics file the
owner can open to add it; nothing is written to their calendar by Heirloom.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

GCAL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GRAPH_VIEW = "https://graph.microsoft.com/v1.0/me/calendarView"


@dataclass
class CalEvent:
    title: str
    start: str
    end: str
    location: str = ""
    all_day: bool = False

    def line(self) -> str:
        where = f" at {self.location}" if self.location else ""
        when = self.start[:10] + " (all day)" if self.all_day else f"{self.start} to {self.end}"
        return f"- {self.title or '(no title)'}: {when}{where}"


def window(days: int, now: Optional[datetime] = None) -> tuple[str, str]:
    start = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    end = start + timedelta(days=max(1, min(days, 31)))
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


class GoogleCalendar:
    def __init__(self, http: Any):
        self.http = http

    def upcoming(self, days: int = 7, *, now: Optional[datetime] = None, limit: int = 20) -> list[CalEvent]:
        lo, hi = window(days, now)
        data = self.http.get(GCAL, params={
            "timeMin": lo, "timeMax": hi, "singleEvents": "true", "orderBy": "startTime", "maxResults": limit,
        })
        out = []
        for e in data.get("items") or []:
            start = e.get("start") or {}
            end = e.get("end") or {}
            out.append(CalEvent(
                title=str(e.get("summary") or ""),
                start=str(start.get("dateTime") or start.get("date") or ""),
                end=str(end.get("dateTime") or end.get("date") or ""),
                location=str(e.get("location") or ""),
                all_day="date" in start and "dateTime" not in start,
            ))
        return out


class OutlookCalendar:
    def __init__(self, http: Any):
        self.http = http

    def upcoming(self, days: int = 7, *, now: Optional[datetime] = None, limit: int = 20) -> list[CalEvent]:
        lo, hi = window(days, now)
        data = self.http.get(GRAPH_VIEW, params={
            "startDateTime": lo, "endDateTime": hi, "$top": limit, "$orderby": "start/dateTime",
            "$select": "subject,start,end,location,isAllDay",
        }, headers={"Prefer": 'outlook.timezone="UTC"'})
        return [
            CalEvent(
                title=str(e.get("subject") or ""),
                start=str((e.get("start") or {}).get("dateTime") or "")[:19] + "Z",
                end=str((e.get("end") or {}).get("dateTime") or "")[:19] + "Z",
                location=str((e.get("location") or {}).get("displayName") or ""),
                all_day=bool(e.get("isAllDay")),
            )
            for e in data.get("value") or []
        ]


CAL_CLASSES = {"google": GoogleCalendar, "microsoft": OutlookCalendar}


def _ics_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_for(draft: dict) -> str:
    start = datetime.fromisoformat(draft["start"])
    end = datetime.fromisoformat(draft["end"])
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Heirloom//Draft//EN", "BEGIN:VEVENT",
        f"UID:{draft['draft_id']}@heirloom",
        f"DTSTAMP:{_ics_time(datetime.now(timezone.utc))}",
        f"DTSTART:{_ics_time(start)}",
        f"DTEND:{_ics_time(end)}",
        f"SUMMARY:{_ics_escape(draft.get('title') or 'Event')}",
    ]
    if draft.get("location"):
        lines.append(f"LOCATION:{_ics_escape(draft['location'])}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def parse_when(when: str, tz_name: str = "") -> Optional[datetime]:
    if not (when or "").strip():
        return None
    try:
        dt = datetime.fromisoformat(when.strip().replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is None:
        try:
            import dateparser

            settings = {"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": True}
            if tz_name:
                settings["TIMEZONE"] = tz_name
            dt = dateparser.parse(when, settings=settings)
        except Exception:  # noqa: BLE001
            dt = None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def new_draft(user_id: str, *, title: str, start: datetime, minutes: int = 60, location: str = "") -> dict:
    minutes = max(5, min(int(minutes or 60), 24 * 60))
    return {
        "draft_id": f"cal_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "title": (title or "Event").strip()[:200],
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=minutes)).isoformat(),
        "location": (location or "").strip()[:200],
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
