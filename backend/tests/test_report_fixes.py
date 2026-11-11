"""Regressions from the local end-to-end report.

These stay import-light so the Windows and Linux CI subset can run them
without Mongo, Emergent, or a live model.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from capture_text import (
    canonical_text,
    grounded_cleanup,
    grounded_title,
    owner_timezone,
    resolve_due_at,
)
from code_workspace import CodePrivacyError, assert_project
from heir_guards import heir_archive_query, portal_turn_update
from llm_errors import llm_error
from local_workstation import (
    PathRefused,
    WorkstationOnly,
    assert_restore_path,
    confine_restore_paths,
    require_workstation,
)
from memory_guard import matches_document
from ollama_status import describe_ollama
from pricing import LOCAL_EDITION_PRICE
from product_info import PRODUCT_VERSION, git_sha, product_version

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = "I always said: measure twice, cut once. My favorite place is the lake cabin at Tahoe."
INVENTED = (
    "I once said that every measurement should be repeated twice to get a more accurate result. "
    "Tahoe is a perfect destination for a peaceful getaway."
)


def test_heir_archive_query_hides_private_and_owner_rows():
    query = heir_archive_query("owner-1")
    gift = {"user_id": "owner-1", "visibility": "heir", "content": "the lake"}
    unmarked = {"user_id": "owner-1", "content": "an old story"}
    private = {"user_id": "owner-1", "visibility": "private", "content": "a private worry"}
    owner_only = {"user_id": "owner-1", "visibility": "owner", "content": "owner note"}
    assert matches_document(query, gift)
    assert matches_document(query, unmarked)
    assert not matches_document(query, private)
    assert not matches_document(query, owner_only)
    portal = (ROOT / "backend" / "routers" / "heir_portal.py").read_text(encoding="utf-8")
    assert "heir_archive_query" in portal
    assert portal.count("heir_archive_query(") >= 2


def test_portal_turn_update_does_not_write_kind_twice():
    update = portal_turn_update(
        owner_id="owner-1",
        heir_id="hr_1",
        session_id="heir_hr_1",
        user_text="hello",
        reply_text="I remember the lake.",
        now_iso="2026-11-11T18:00:00+00:00",
    )
    assert set(update["$set"]).isdisjoint(update["$setOnInsert"])
    assert "kind" not in update["$setOnInsert"]
    assert update["$set"]["kind"] == "heir_portal"
    assert update["$set"]["heir_id"] == "hr_1"
    portal = (ROOT / "backend" / "routers" / "heir_portal.py").read_text(encoding="utf-8")
    assert "portal_turn_update(" in portal


def test_capture_keeps_the_owners_words_and_drops_inventions():
    assert canonical_text({"content": ORIGINAL, "cleanup": INVENTED}) == ORIGINAL
    assert grounded_cleanup(ORIGINAL, INVENTED) is None
    assert "peaceful" not in (grounded_cleanup(ORIGINAL, INVENTED) or "")
    kept = grounded_cleanup(ORIGINAL, "I always said measure twice, cut once.")
    assert kept is not None
    assert "getaway" not in kept
    assert grounded_title(ORIGINAL, "A peaceful Tahoe getaway") == " ".join(ORIGINAL.split())[:80]
    capture = (ROOT / "backend" / "routers" / "capture.py").read_text(encoding="utf-8")
    assert '"content": text' in capture
    assert '"content": cleaned' not in capture
    memory = (ROOT / "backend" / "routers" / "memory.py").read_text(encoding="utf-8")
    portrait = (ROOT / "backend" / "routers" / "personality.py").read_text(encoding="utf-8")
    assert "canonical_text(" in memory
    assert "canonical_text(" in portrait


def test_thursday_at_3pm_uses_the_owner_zone_not_utc():
    now = datetime(2026, 11, 11, 18, 0, tzinfo=timezone.utc)
    iso = resolve_due_at(
        "Remind me to call the dentist Thursday at 3pm",
        "2026-11-12T13:00:00+00:00",
        "America/Los_Angeles",
        now,
    )
    local = datetime.fromisoformat(iso).astimezone(ZoneInfo("America/Los_Angeles"))
    assert local.weekday() == 3
    assert (local.hour, local.minute) == (15, 0)
    assert local.isoformat().startswith("2026-11-12T15:00")
    tomorrow = resolve_due_at(
        "Remind me tomorrow at 3pm",
        "2026-11-11T15:00:00+00:00",
        "America/Los_Angeles",
        now,
    )
    tomorrow_local = datetime.fromisoformat(tomorrow).astimezone(ZoneInfo("America/Los_Angeles"))
    assert tomorrow_local.date().isoformat() == "2026-11-12"
    assert (tomorrow_local.hour, tomorrow_local.minute) == (15, 0)
    new_year = resolve_due_at(
        "January 1st at 12pm",
        "2026-11-12T12:00:00+00:00",
        "America/Los_Angeles",
        now,
    )
    new_year_local = datetime.fromisoformat(new_year).astimezone(ZoneInfo("America/Los_Angeles"))
    assert new_year_local.date().isoformat() == "2027-01-01"
    assert (new_year_local.hour, new_year_local.minute) == (12, 0)
    story = resolve_due_at(
        "Remind me tomorrow at 3pm about the note dated January 5, 1998",
        "1998-01-05T15:00:00+00:00",
        "America/Los_Angeles",
        now,
    )
    story_local = datetime.fromisoformat(story).astimezone(ZoneInfo("America/Los_Angeles"))
    assert story_local.date().isoformat() == "2026-11-12"
    assert (story_local.hour, story_local.minute) == (15, 0)
    born = resolve_due_at(
        "I was born in 1980. Remind me January 1st at 12pm",
        "1980-01-01T12:00:00+00:00",
        "America/Los_Angeles",
        now,
    )
    born_local = datetime.fromisoformat(born).astimezone(ZoneInfo("America/Los_Angeles"))
    assert born_local.date().isoformat() == "2027-01-01"
    assert (born_local.hour, born_local.minute) == (12, 0)
    about = resolve_due_at(
        "tomorrow at 3pm about January 5",
        "2027-01-05T15:00:00+00:00",
        "America/Los_Angeles",
        now,
    )
    about_local = datetime.fromisoformat(about).astimezone(ZoneInfo("America/Los_Angeles"))
    assert about_local.date().isoformat() == "2026-11-12"
    labeled = resolve_due_at(
        "January 5, Thursday at 3pm",
        "2026-11-12T15:00:00+00:00",
        "America/Los_Angeles",
        now,
    )
    labeled_local = datetime.fromisoformat(labeled).astimezone(ZoneInfo("America/Los_Angeles"))
    assert labeled_local.date().isoformat() == "2027-01-05"
    assert (labeled_local.hour, labeled_local.minute) == (15, 0)
    later = resolve_due_at(
        "in 2 weeks on Thursday at 3pm",
        "2026-11-12T15:00:00+00:00",
        "America/Los_Angeles",
        now,
    )
    later_local = datetime.fromisoformat(later).astimezone(ZoneInfo("America/Los_Angeles"))
    assert later_local.date().isoformat() == "2026-11-26"
    assert (later_local.hour, later_local.minute) == (15, 0)
    assert owner_timezone({"timezone": "America/Los_Angeles"}) == "America/Los_Angeles"
    assert owner_timezone({}, "America/Chicago") == "America/Chicago"
    assert owner_timezone({"timezone": "America/Los_Angeles"}, "America/Chicago") == "America/Chicago"
    assert owner_timezone({"phone_settings": {"timezone": "America/Chicago"}}) == "America/Chicago"
    assert owner_timezone({}, "Not/AZone") == "UTC"


def test_hosted_filesystem_routes_stay_hidden_and_box_paths_stay_inside(tmp_path, monkeypatch):
    monkeypatch.delenv("HEIRLOOM_BOX", raising=False)
    monkeypatch.delenv("HEIRLOOM_DESKTOP", raising=False)
    with pytest.raises(WorkstationOnly):
        require_workstation()
    monkeypatch.setenv("HEIRLOOM_BOX", "1")
    require_workstation()
    monkeypatch.delenv("HEIRLOOM_BOX", raising=False)
    monkeypatch.setenv("HEIRLOOM_DESKTOP", "1")
    require_workstation()

    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("HEIRLOOM_CODE_ROOTS", str(workspace))
    assert assert_project(workspace) == workspace.resolve()
    with pytest.raises(CodePrivacyError):
        assert_project(outside)

    monkeypatch.setenv("HEIRLOOM_RESTORE_ROOTS", str(workspace))
    monkeypatch.delenv("HEIRLOOM_DATA_ROOT", raising=False)
    assert assert_restore_path(str(workspace)) == workspace.resolve()
    with pytest.raises(PathRefused):
        assert_restore_path(str(outside))
    with pytest.raises(PathRefused):
        confine_restore_paths("")
    with pytest.raises(PathRefused):
        confine_restore_paths("  ", str(workspace))
    confine_restore_paths(None, str(workspace))

    router = (ROOT / "backend" / "routers" / "big_update.py").read_text(encoding="utf-8")
    assert router.count("_local_owner(user)") >= 6
    assert "confine_restore_paths" in router


def test_owner_sit_routes_require_the_owner():
    owner = (ROOT / "backend" / "routers" / "owner.py").read_text(encoding="utf-8")
    assert owner.count("_owner_only(user)") >= 2
    assert "require_owner" in owner


def test_llm_timeouts_are_a_retry_not_a_bare_error():
    class ReadTimeout(Exception):
        pass

    status, detail = llm_error(ReadTimeout(""), what="Writing help")
    assert status == 503
    assert detail == "Writing help took too long. Try again in a moment."
    assert "ReadTimeout" not in detail
    status, detail = llm_error(Exception(""), what="Rebuilding memories")
    assert status == 502
    assert detail == "Rebuilding memories didn't finish. Try again."
    assert "failed:" not in detail
    letters = (ROOT / "backend" / "routers" / "letters.py").read_text(encoding="utf-8")
    memory = (ROOT / "backend" / "routers" / "memory.py").read_text(encoding="utf-8")
    assert "llm_error(" in letters
    assert "llm_error(" in memory
    assert "LLM fact extraction failed" not in memory


def test_ollama_probe_trusts_a_live_answer():
    answering = describe_ollama(
        {},
        {},
        live_ready=lambda: True,
        live_url="http://127.0.0.1:11434",
    )
    assert answering["ready"] is True
    assert "Start Ollama" not in answering["detail"]
    assert "answering" in answering["detail"].lower()
    quiet = describe_ollama({}, {}, live_ready=lambda: False, live_url="http://127.0.0.1:11434")
    assert quiet["ready"] is False
    assert "Start Ollama" in quiet["detail"]
    studio = (ROOT / "backend" / "routers" / "studio.py").read_text(encoding="utf-8")
    assert "_ollama_status(" in studio


def test_build_sha_and_version_are_not_hard_coded():
    assert product_version() == PRODUCT_VERSION == "0.5.1"
    assert git_sha()
    server = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    health = (ROOT / "backend" / "box_health.py").read_text(encoding="utf-8")
    assert "git_sha()" in server
    assert "product_version()" in server
    assert "DESKTOP_BUILD" not in server
    assert "146de72" not in server
    assert "from product_info import PRODUCT_VERSION" in health
    assert 'PRODUCT_VERSION = "0.5.1"' not in health


def test_git_sha_uses_env_then_unknown(monkeypatch):
    monkeypatch.setenv("HEIRLOOM_GIT_SHA", "abc123def456999")
    assert git_sha() == "abc123def456"
    for key in ("HEIRLOOM_GIT_SHA", "GIT_COMMIT", "SOURCE_VERSION", "GITHUB_SHA"):
        monkeypatch.delenv(key, raising=False)

    class _Proc:
        returncode = 1
        stdout = ""

    monkeypatch.setattr("product_info.subprocess.run", lambda *args, **kwargs: _Proc())
    assert git_sha() == "unknown"


def test_price_and_owner_name_are_not_hard_coded_in_the_ui():
    assert LOCAL_EDITION_PRICE == 79.99
    pages = [
        ROOT / "frontend" / "src" / "pages" / "Landing.jsx",
        ROOT / "frontend" / "src" / "pages" / "Buy.jsx",
        ROOT / "frontend" / "src" / "pages" / "Terms.jsx",
        ROOT / "frontend" / "src" / "pages" / "TwinLive.jsx",
    ]
    for path in pages:
        text = path.read_text(encoding="utf-8")
        assert "LOCAL_EDITION" in text
        assert "$79 lifetime" not in text
        assert "$79 —" not in text
        assert "$79," not in text
    ui = [
        ROOT / "frontend" / "src" / "components" / "AppLayout.jsx",
        ROOT / "frontend" / "src" / "components" / "studio" / "menuDefinitions.js",
        ROOT / "frontend" / "src" / "pages" / "WouldSay.jsx",
    ]
    for path in ui:
        assert "Would C L say that?" not in path.read_text(encoding="utf-8")
    billing = (ROOT / "backend" / "routers" / "billing.py").read_text(encoding="utf-8")
    assert "LOCAL_EDITION_PRICE" in billing
    capture = (ROOT / "frontend" / "src" / "components" / "QuickCapture.jsx").read_text(encoding="utf-8")
    assert "browserTimeZone" in capture
