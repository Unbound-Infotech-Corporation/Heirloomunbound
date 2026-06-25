"""Phase 6 — onboarding, sources, dashboard_extra, widgets."""
import io
import os
import time
import zipfile
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path("/app/frontend/.env"))

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or os.environ.get("PUBLIC_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

# Seeded via mongosh at start of iteration_6 run
TOKEN_A = "p6_onb_1782382675611"  # has >=3 entries → auto-onboard
USER_A  = "p6-onb-1782382675611"
TOKEN_B = "p6_newer_1782382832969"  # zero entries → onboarded=false
USER_B  = "p6-newer-1782382832969"
TOKEN_C = "p6_iso_1782382675611"  # for cross-user source isolation
USER_C  = "p6-iso-1782382675611"


def _h(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- ONBOARDING STATE ----------
class TestOnboardingState:
    def test_auto_onboard_for_legacy_user(self):
        r = requests.get(f"{API}/onboarding/state", headers=_h(TOKEN_A))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["onboarded"] is True
        assert "preferred_name" in data
        assert "dashboard_widgets" in data and isinstance(data["dashboard_widgets"], dict)
        # known widget keys exist
        assert "reflection" in data["dashboard_widgets"]

    def test_new_user_not_onboarded(self):
        r = requests.get(f"{API}/onboarding/state", headers=_h(TOKEN_B))
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["onboarded"] is False

    def test_state_requires_auth(self):
        r = requests.get(f"{API}/onboarding/state")
        assert r.status_code in (401, 403)


# ---------- ONBOARDING COMPLETE ----------
class TestOnboardingComplete:
    def test_complete_seeds_archive(self):
        payload = {
            "preferred_name": "Phase6 NewUser",
            "chapter": "Career builder",
            "key_people": "My wife Anna and my brother Sam",
            "guiding_values": ["honesty", "curiosity", "patience"],
            "favorite_saying": "Measure twice, cut once.",
            "one_thing_to_remember": "Always make time for the people who show up.",
            "daily_routine": "Coffee, walk, code",
        }
        r = requests.post(f"{API}/onboarding/complete", headers=_h(TOKEN_B), json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["count"] >= 4
        assert isinstance(data["seeded"], list)

        # Verify state flipped to onboarded
        s = requests.get(f"{API}/onboarding/state", headers=_h(TOKEN_B)).json()
        assert s["onboarded"] is True
        assert s["preferred_name"] == "Phase6 NewUser"

        # Verify archive has the seeded entries with source='onboarding' and 'onboarding' tag
        a = requests.get(f"{API}/archive", headers=_h(TOKEN_B))
        assert a.status_code == 200
        entries = a.json()
        entries_list = entries if isinstance(entries, list) else entries.get("entries", [])
        onboarding_entries = [e for e in entries_list if e.get("source") == "onboarding"]
        assert len(onboarding_entries) >= 4, f"got {len(onboarding_entries)} entries"
        # tag check
        for e in onboarding_entries:
            assert "onboarding" in (e.get("tags") or [])
        # Types should include value, advice, quote, memory
        types = {e["type"] for e in onboarding_entries}
        assert {"value", "advice", "quote", "memory"}.issubset(types)


# ---------- WIDGETS ----------
class TestWidgets:
    def test_update_widgets_filters_unknown(self):
        payload = {"widgets": {
            "reflection": False,
            "on_this_day": True,
            "malicious_key": True,        # should be filtered
            "recent_journals": "yes",     # bool coerced from truthy string → True
            "photo_of_day": 0,            # bool coerced → False
        }}
        r = requests.put(f"{API}/onboarding/widgets", headers=_h(TOKEN_A), json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        widgets = data["widgets"]
        assert "malicious_key" not in widgets
        assert widgets["reflection"] is False
        assert widgets["on_this_day"] is True
        assert widgets["recent_journals"] is True   # bool coercion
        assert widgets["photo_of_day"] is False
        for v in widgets.values():
            assert isinstance(v, bool)

        # state reflects update
        s = requests.get(f"{API}/onboarding/state", headers=_h(TOKEN_A)).json()
        assert s["dashboard_widgets"]["reflection"] is False
        assert s["dashboard_widgets"]["on_this_day"] is True

    def test_update_widgets_empty_rejected(self):
        r = requests.put(f"{API}/onboarding/widgets", headers=_h(TOKEN_A),
                         json={"widgets": {"bogus_only": True}})
        assert r.status_code == 400


# ---------- SOURCES ----------
class TestSources:
    @classmethod
    def setup_class(cls):
        cls.local_src_id = None
        cls.upload_src_id = None

    def test_01_create_local_folder_source(self):
        r = requests.post(f"{API}/sources", headers=_h(TOKEN_A),
                          json={"kind": "local_folder", "label": "My Journal",
                                "config": {"path": "/Users/me/Journal"}})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["kind"] == "local_folder"
        assert d["config"]["path"] == "/Users/me/Journal"
        assert d["source_id"].startswith("src_")
        TestSources.local_src_id = d["source_id"]

    def test_02_list_sources(self):
        r = requests.get(f"{API}/sources", headers=_h(TOKEN_A))
        assert r.status_code == 200
        ids = [s["source_id"] for s in r.json()]
        assert TestSources.local_src_id in ids

    def test_03_invalid_kind_rejected(self):
        r = requests.post(f"{API}/sources", headers=_h(TOKEN_A),
                          json={"kind": "bogus", "label": "x", "config": {}})
        assert r.status_code == 400

    def test_04_sync_local_enqueues_command(self):
        sid = TestSources.local_src_id
        assert sid
        r = requests.post(f"{API}/sources/{sid}/sync-local", headers=_h(TOKEN_A))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["cmd_id"].startswith("cmd_")

    def test_05_local_source_rejects_upload(self):
        sid = TestSources.local_src_id
        files = {"file": ("small.txt", b"hi there friend, just a tiny note", "text/plain")}
        r = requests.post(f"{API}/sources/{sid}/upload", headers=_h(TOKEN_A), files=files)
        assert r.status_code == 400

    def test_06_create_generic_upload_source(self):
        r = requests.post(f"{API}/sources", headers=_h(TOKEN_A),
                          json={"kind": "generic_upload", "label": "My Notes", "config": {}})
        assert r.status_code == 200
        TestSources.upload_src_id = r.json()["source_id"]

    def test_07_upload_text_extracts(self):
        sid = TestSources.upload_src_id
        assert sid
        text = (
            "I grew up in Buffalo. My father taught me to fish at Lake Erie before "
            "I could ride a bike. He always said 'you don't catch fish by complaining about the weather' "
            "and I still think about that whenever life feels unfair. I want my kids to "
            "remember that I tried, even on the hard days. We used to camp at Allegany in "
            "the summer, three brothers in one tent, eating too many marshmallows."
        )
        files = {"file": ("memoir.txt", text.encode("utf-8"), "text/plain")}
        r = requests.post(f"{API}/sources/{sid}/upload", headers=_h(TOKEN_A), files=files, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["chunks_processed"] == 1
        # LLM extraction can return 0-N; we require >=1 per spec but tolerate 0 with a soft warning
        assert d["extracted"] >= 1, f"Claude returned 0 fragments: {d}"
        # Confirm in archive
        a = requests.get(f"{API}/archive", headers=_h(TOKEN_A)).json()
        items = a if isinstance(a, list) else a.get("entries", [])
        src_tag = f"source:{sid}"
        matches = [e for e in items if e.get("source") == src_tag]
        assert len(matches) >= 1

    def test_08_empty_upload_400(self):
        sid = TestSources.upload_src_id
        files = {"file": ("empty.txt", b"", "text/plain")}
        r = requests.post(f"{API}/sources/{sid}/upload", headers=_h(TOKEN_A), files=files)
        assert r.status_code == 400

    def test_09_exe_upload_400(self):
        sid = TestSources.upload_src_id
        files = {"file": ("evil.exe", b"MZ\x90\x00" + b"\x00" * 200, "application/octet-stream")}
        r = requests.post(f"{API}/sources/{sid}/upload", headers=_h(TOKEN_A), files=files)
        assert r.status_code == 400

    def test_10_zip_upload_extracts(self):
        sid = TestSources.upload_src_id
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("note1.txt",
                "I remember the first time I held my daughter — I was terrified and grateful "
                "at the same time. The hospital was quiet at 3am and I told her I would always "
                "try to be honest with her, even when it was hard.")
            zf.writestr("note2.md",
                "# Rules I live by\n- Show up.\n- Tell the truth.\n- Never let pride keep you from apologizing.\n")
        files = {"file": ("notes.zip", buf.getvalue(), "application/zip")}
        r = requests.post(f"{API}/sources/{sid}/upload", headers=_h(TOKEN_A), files=files, timeout=180)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["chunks_processed"] >= 1

    def test_11_user_isolation(self):
        # User C cannot see User A's sources
        r = requests.get(f"{API}/sources", headers=_h(TOKEN_C))
        assert r.status_code == 200
        ids = [s["source_id"] for s in r.json()]
        assert TestSources.local_src_id not in ids
        assert TestSources.upload_src_id not in ids
        # delete attempt → 404
        r2 = requests.delete(f"{API}/sources/{TestSources.local_src_id}", headers=_h(TOKEN_C))
        assert r2.status_code == 404

    def test_12_delete_source(self):
        sid = TestSources.upload_src_id
        r = requests.delete(f"{API}/sources/{sid}", headers=_h(TOKEN_A))
        assert r.status_code == 200
        # idempotent — second delete → 404
        r2 = requests.delete(f"{API}/sources/{sid}", headers=_h(TOKEN_A))
        assert r2.status_code == 404


# ---------- DASHBOARD EXTRAS ----------
class TestDashboardExtras:
    def test_on_this_day_shape(self):
        r = requests.get(f"{API}/dashboard/on-this-day", headers=_h(TOKEN_A))
        assert r.status_code == 200, r.text
        d = r.json()
        assert "date" in d and len(d["date"]) == 5  # MM-DD
        assert "entries" in d and isinstance(d["entries"], list)

    def test_on_this_day_picks_up_today_entry(self):
        # Seed entry via API (will have today's created_at)
        r = requests.post(f"{API}/archive", headers=_h(TOKEN_A), json={
            "type": "memory", "title": "Today seed for on-this-day",
            "content": "Just a marker created today.", "tags": ["p6-otd"]
        })
        assert r.status_code in (200, 201), r.text
        time.sleep(0.5)
        r2 = requests.get(f"{API}/dashboard/on-this-day", headers=_h(TOKEN_A))
        assert r2.status_code == 200
        titles = [e.get("title", "") for e in r2.json()["entries"]]
        assert any("Today seed for on-this-day" in t for t in titles)

    def test_recent_journals_shape(self):
        r = requests.get(f"{API}/dashboard/recent-journals", headers=_h(TOKEN_A))
        assert r.status_code == 200
        d = r.json()
        assert "entries" in d and isinstance(d["entries"], list)
        assert len(d["entries"]) <= 5

    def test_last_twin_chat_null_when_none(self):
        # User C has no twin conversations
        r = requests.get(f"{API}/dashboard/last-twin-chat", headers=_h(TOKEN_C))
        assert r.status_code == 200
        d = r.json()
        # spec says {conversation: null} OR null tail — accept either
        assert d.get("conversation") is None or d.get("tail") in (None, [])


# ---------- REGRESSION sanity (lightweight) ----------
class TestRegression:
    def test_auth_me(self):
        r = requests.get(f"{API}/auth/me", headers=_h(TOKEN_A))
        assert r.status_code == 200
        assert r.json()["user_id"] == USER_A

    def test_archive_crud_roundtrip(self):
        # CREATE
        r = requests.post(f"{API}/archive", headers=_h(TOKEN_A), json={
            "type": "memory", "title": "p6-reg", "content": "regression", "tags": ["p6"]
        })
        assert r.status_code in (200, 201)
        eid = r.json().get("entry_id") or r.json().get("id")
        assert eid
        # GET list
        lst = requests.get(f"{API}/archive", headers=_h(TOKEN_A)).json()
        items = lst if isinstance(lst, list) else lst.get("entries", [])
        assert any((e.get("entry_id") or e.get("id")) == eid for e in items)
        # DELETE
        d = requests.delete(f"{API}/archive/{eid}", headers=_h(TOKEN_A))
        assert d.status_code in (200, 204)

    def test_dashboard_streak(self):
        r = requests.get(f"{API}/dashboard", headers=_h(TOKEN_A))
        assert r.status_code == 200
        assert "streak_days" in r.json()

    def test_reminders_list(self):
        r = requests.get(f"{API}/reminders", headers=_h(TOKEN_A))
        assert r.status_code == 200

    def test_skills_list(self):
        # No /skills/scrape endpoint; verify list works
        r = requests.get(f"{API}/skills", headers=_h(TOKEN_A))
        assert r.status_code == 200
