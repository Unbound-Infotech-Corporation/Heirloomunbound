"""Calendar / briefing helpers — no Mongo, no live Google."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.day_assist import (
    CALENDAR_RECONNECT,
    event_preview,
    format_events,
    public_event,
    scope_has_calendar,
    window_utc,
)


def test_scope_has_calendar_google_and_microsoft():
    assert scope_has_calendar("https://www.googleapis.com/auth/calendar.events")
    assert scope_has_calendar("Mail.Read Calendars.ReadWrite")
    assert not scope_has_calendar("gmail.readonly gmail.send")
    assert not scope_has_calendar("")


def test_window_utc_clamps_days():
    start, end = window_utc(days=1)
    assert (end - start).days == 1
    start2, end2 = window_utc(days=99)
    assert (end2 - start2).days == 14
    start3, end3 = window_utc(days=0)
    assert (end3 - start3).days == 1


def test_event_preview_asks_for_confirm():
    text = event_preview("Dentist", "2026-08-16T15:00:00+00:00", "2026-08-16T16:00:00+00:00", "Clinic")
    assert "confirmed=true" in text
    assert "Dentist" in text
    assert "Clinic" in text


def test_format_events_and_public_row():
    rows = [
        {"title": "Walk", "start": "2026-08-16T09:00:00Z", "end": "2026-08-16T10:00:00Z", "where": "Park", "all_day": False},
    ]
    pub = public_event(rows[0])
    assert pub["title"] == "Walk"
    assert "Park" in format_events(rows)
    assert format_events([]) == ""
    assert "calendar" in CALENDAR_RECONNECT.lower()


def test_catalog_declares_calendar_people_and_briefing():
    root = Path(__file__).resolve().parents[1]
    abilities = (root / "abilities.py").read_text()
    tools = (root / "twin_tools.py").read_text()
    assert '"id": "calendar"' in abilities
    assert '"id": "people"' in abilities
    for name in ("whats_on_my_plate", "list_events", "create_event", "find_contact", "call_contact", "list_reminders", "complete_reminder"):
        assert name in tools
        assert f'"{name}": exec_{name}' in tools
    assert "whats_on_my_plate" in abilities or "whats_on_my_plate" in (root / "routers" / "twin.py").read_text()
