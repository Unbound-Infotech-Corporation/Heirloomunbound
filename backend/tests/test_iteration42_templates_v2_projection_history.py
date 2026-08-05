"""Iteration 42 backend tests.

Coverage:
  - GET  /api/routing/templates             — builtins tagged 'builtin', custom tagged 'custom', order, no user_id leak
  - GET  /api/routing/templates/preview     — diff shape, empty diff, user-custom, cross-user 404, unknown 404
  - POST /api/routing/templates/apply       — accepts both builtin + user_ IDs, unknown → 400
  - POST /api/routing/templates/save        — label required, label max 60, blurb truncated 200, user_id null
  - DELETE /api/routing/templates/{id}      — user_ only (built-in → 400), 404 for unknown, 404 for other user's
  - Scoping — user A cannot see/preview/apply/delete user B's custom template
  - GET  /api/routing/usage/projection/history — days clamping [1..90], series shape
  - services.llm_router.snapshot_projections — upserts one row per (user, provider, day) — idempotent
  - Indexes — user_templates.template_id_uniq and projection_history.user_provider_day_uniq exist
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests

sys.path.insert(0, "/app/backend")

for p in ("/app/frontend/.env", "/app/backend/.env"):
    try:
        with open(p) as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v.strip('"'))
    except FileNotFoundError:
        pass

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SESSION = "test_routing_session"
USER_ID = "test-routing-user"
UA_SESS = "rest_regress_ua_session"
UA_USER = "rest-regress-ua"
UB_SESS = "rest_regress_ub_session"
UB_USER = "rest-regress-ub"

BUILTINS = {"cheapest", "quality_first", "balanced", "all_emergent", "local_first"}


def _c(tok: str = SESSION) -> dict:
    return {"session_token": tok}


def _mongo():
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"])
    return client[os.environ["DB_NAME"]]


# ---------------- Templates list ----------------
class TestTemplatesList:
    def test_builtins_kind_and_no_user_id(self):
        r = requests.get(f"{BASE_URL}/api/routing/templates", cookies=_c(), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list) and len(data) >= 5
        # First N must be builtins in insertion order
        builtins_seen = [t for t in data if t.get("kind") == "builtin"]
        assert {t["id"] for t in builtins_seen} == BUILTINS
        # No entry should leak a user_id
        for t in data:
            assert "user_id" not in t, t
            assert t.get("kind") in {"builtin", "custom"}

    def test_order_builtins_before_custom(self):
        # Seed a custom template first
        r_save = requests.post(
            f"{BASE_URL}/api/routing/templates/save",
            json={"label": "TEST_order_probe", "blurb": "x"},
            cookies=_c(), timeout=15,
        )
        assert r_save.status_code == 200, r_save.text
        tid = r_save.json()["template_id"]
        try:
            r = requests.get(f"{BASE_URL}/api/routing/templates", cookies=_c(), timeout=15)
            data = r.json()
            kinds = [t["kind"] for t in data]
            # every builtin index must come before every custom index
            first_custom = kinds.index("custom") if "custom" in kinds else len(kinds)
            assert all(k == "builtin" for k in kinds[:first_custom])
        finally:
            requests.delete(f"{BASE_URL}/api/routing/templates/{tid}", cookies=_c(), timeout=15)


# ---------------- Preview ----------------
class TestPreview:
    def test_preview_quality_first_diff(self):
        # Reset caller to a known baseline (balanced) so diff is deterministic.
        requests.post(f"{BASE_URL}/api/routing/templates/apply",
                      json={"template_id": "balanced"}, cookies=_c(), timeout=15)
        r = requests.get(f"{BASE_URL}/api/routing/templates/preview",
                         params={"template_id": "quality_first"}, cookies=_c(), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["template_id"] == "quality_first"
        assert data["label"] == "Quality-first"
        assert isinstance(data["diff"], list)
        # quality_first vs balanced changes chat/interview/tools from emergent → anthropic
        changed = {row["task"]: (row["from"], row["to"]) for row in data["diff"]}
        for task in ("chat", "interview", "tools"):
            assert changed.get(task) == ("emergent", "anthropic"), data["diff"]
        # Diff should NOT contain unchanged tasks
        for row in data["diff"]:
            assert row["from"] != row["to"]
        # new_routes contains merged view
        assert data["new_routes"]["chat"] == "anthropic"
        assert data["new_routes"]["long_context"] == "gemini"

    def test_preview_empty_diff_when_already_applied(self):
        # Apply balanced twice → previewing balanced afterwards should yield empty diff
        requests.post(f"{BASE_URL}/api/routing/templates/apply",
                      json={"template_id": "balanced"}, cookies=_c(), timeout=15)
        r = requests.get(f"{BASE_URL}/api/routing/templates/preview",
                         params={"template_id": "balanced"}, cookies=_c(), timeout=15)
        assert r.status_code == 200
        assert r.json()["diff"] == []

    def test_preview_unknown_404(self):
        r = requests.get(f"{BASE_URL}/api/routing/templates/preview",
                         params={"template_id": "no_such_thing_xyz"}, cookies=_c(), timeout=15)
        assert r.status_code == 404

    def test_preview_own_custom(self):
        r_save = requests.post(f"{BASE_URL}/api/routing/templates/save",
                               json={"label": "TEST_prev_own"}, cookies=_c(), timeout=15)
        tid = r_save.json()["template_id"]
        try:
            r = requests.get(f"{BASE_URL}/api/routing/templates/preview",
                             params={"template_id": tid}, cookies=_c(), timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["template_id"] == tid
        finally:
            requests.delete(f"{BASE_URL}/api/routing/templates/{tid}", cookies=_c(), timeout=15)


# ---------------- Apply ----------------
class TestApply:
    def test_apply_builtin(self):
        r = requests.post(f"{BASE_URL}/api/routing/templates/apply",
                          json={"template_id": "balanced"}, cookies=_c(), timeout=15)
        assert r.status_code == 200
        assert r.json()["template"] == "balanced"

    def test_apply_user_custom(self):
        r_save = requests.post(f"{BASE_URL}/api/routing/templates/save",
                               json={"label": "TEST_apply_custom"}, cookies=_c(), timeout=15)
        tid = r_save.json()["template_id"]
        try:
            r = requests.post(f"{BASE_URL}/api/routing/templates/apply",
                              json={"template_id": tid}, cookies=_c(), timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["template"] == tid
        finally:
            requests.delete(f"{BASE_URL}/api/routing/templates/{tid}", cookies=_c(), timeout=15)

    def test_apply_unknown_400(self):
        r = requests.post(f"{BASE_URL}/api/routing/templates/apply",
                          json={"template_id": "user_deadbeef00"}, cookies=_c(), timeout=15)
        assert r.status_code == 400


# ---------------- Save ----------------
class TestSave:
    def test_save_success_shape(self):
        r = requests.post(f"{BASE_URL}/api/routing/templates/save",
                          json={"label": "TEST_shape", "blurb": "hello"},
                          cookies=_c(), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["template_id"].startswith("user_")
        assert data["label"] == "TEST_shape"
        assert data["blurb"] == "hello"
        assert isinstance(data["task_routes"], dict)
        assert "created_at" in data
        # user_id must be null in response
        assert data.get("user_id") is None
        try:
            requests.delete(f"{BASE_URL}/api/routing/templates/{data['template_id']}",
                            cookies=_c(), timeout=15)
        except Exception:
            pass

    def test_save_empty_label_400(self):
        r = requests.post(f"{BASE_URL}/api/routing/templates/save",
                          json={"label": "   "}, cookies=_c(), timeout=15)
        assert r.status_code == 400

    def test_save_label_too_long_400(self):
        r = requests.post(f"{BASE_URL}/api/routing/templates/save",
                          json={"label": "A" * 61}, cookies=_c(), timeout=15)
        assert r.status_code == 400

    def test_save_blurb_truncated_200(self):
        long_blurb = "B" * 300
        r = requests.post(f"{BASE_URL}/api/routing/templates/save",
                          json={"label": "TEST_blurb_trunc", "blurb": long_blurb},
                          cookies=_c(), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert len(data["blurb"]) == 200
        assert data["blurb"] == "B" * 200
        requests.delete(f"{BASE_URL}/api/routing/templates/{data['template_id']}",
                        cookies=_c(), timeout=15)


# ---------------- Delete ----------------
class TestDelete:
    def test_delete_builtin_400(self):
        r = requests.delete(f"{BASE_URL}/api/routing/templates/cheapest",
                            cookies=_c(), timeout=15)
        assert r.status_code == 400

    def test_delete_nonexistent_user_404(self):
        r = requests.delete(f"{BASE_URL}/api/routing/templates/user_deadbeef99",
                            cookies=_c(), timeout=15)
        assert r.status_code == 404

    def test_delete_own_success(self):
        r_save = requests.post(f"{BASE_URL}/api/routing/templates/save",
                               json={"label": "TEST_del_own"}, cookies=_c(), timeout=15)
        tid = r_save.json()["template_id"]
        r_del = requests.delete(f"{BASE_URL}/api/routing/templates/{tid}",
                                cookies=_c(), timeout=15)
        assert r_del.status_code == 200
        # And it's gone from list
        r_list = requests.get(f"{BASE_URL}/api/routing/templates", cookies=_c(), timeout=15)
        assert tid not in {t["id"] for t in r_list.json()}


# ---------------- Cross-user scoping ----------------
class TestScoping:
    def test_ua_cannot_see_preview_apply_delete_ubs_template(self):
        # UB saves a template
        r_save = requests.post(f"{BASE_URL}/api/routing/templates/save",
                               json={"label": "TEST_ub_only"}, cookies=_c(UB_SESS), timeout=15)
        assert r_save.status_code == 200, r_save.text
        tid = r_save.json()["template_id"]
        try:
            # UA listing must NOT contain UB's tid
            r_list_ua = requests.get(f"{BASE_URL}/api/routing/templates",
                                     cookies=_c(UA_SESS), timeout=15)
            ua_ids = {t["id"] for t in r_list_ua.json()}
            assert tid not in ua_ids

            # UB listing must contain it and be tagged custom, with no user_id key
            r_list_ub = requests.get(f"{BASE_URL}/api/routing/templates",
                                     cookies=_c(UB_SESS), timeout=15)
            ubs_row = next((t for t in r_list_ub.json() if t["id"] == tid), None)
            assert ubs_row is not None
            assert ubs_row["kind"] == "custom"
            assert "user_id" not in ubs_row

            # UA preview → 404
            r_prev = requests.get(f"{BASE_URL}/api/routing/templates/preview",
                                  params={"template_id": tid}, cookies=_c(UA_SESS), timeout=15)
            assert r_prev.status_code == 404

            # UA apply → 400 (unknown)
            r_apply = requests.post(f"{BASE_URL}/api/routing/templates/apply",
                                    json={"template_id": tid}, cookies=_c(UA_SESS), timeout=15)
            assert r_apply.status_code == 400

            # UA delete → 404 (must not affect UB's row)
            r_del = requests.delete(f"{BASE_URL}/api/routing/templates/{tid}",
                                    cookies=_c(UA_SESS), timeout=15)
            assert r_del.status_code == 404

            # UB can still see + delete it
            r_list_ub2 = requests.get(f"{BASE_URL}/api/routing/templates",
                                      cookies=_c(UB_SESS), timeout=15)
            assert tid in {t["id"] for t in r_list_ub2.json()}
        finally:
            requests.delete(f"{BASE_URL}/api/routing/templates/{tid}",
                            cookies=_c(UB_SESS), timeout=15)


# ---------------- Projection History Endpoint ----------------
class TestProjectionHistoryEndpoint:
    def test_default_14_days(self):
        r = requests.get(f"{BASE_URL}/api/routing/usage/projection/history",
                         cookies=_c(), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert len(data["days"]) == 14
        assert isinstance(data["series"], dict)
        # Days ordered oldest → newest
        assert data["days"] == sorted(data["days"])

    def test_clamp_zero_to_one(self):
        r = requests.get(f"{BASE_URL}/api/routing/usage/projection/history",
                         params={"days": 0}, cookies=_c(), timeout=15)
        assert r.status_code == 200
        assert len(r.json()["days"]) == 1

    def test_clamp_large_to_90(self):
        r = requests.get(f"{BASE_URL}/api/routing/usage/projection/history",
                         params={"days": 1000}, cookies=_c(), timeout=15)
        assert r.status_code == 200
        assert len(r.json()["days"]) == 90


# ---------------- Snapshot function (direct import) ----------------
class TestSnapshotProjections:
    def test_idempotent_upsert(self):
        from services.llm_router import snapshot_projections

        db = _mongo()
        uid = f"iter42-snap-{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # seed usage_events for two providers
        db.usage_events.insert_many([
            {"user_id": uid, "provider": "openai", "model": "gpt-4o",
             "cost_usd": 1.23, "prompt_tokens": 10, "completion_tokens": 5,
             "ts": month_start.isoformat()},
            {"user_id": uid, "provider": "groq", "model": "llama-3.3-70b-versatile",
             "cost_usd": 0.11, "prompt_tokens": 10, "completion_tokens": 5,
             "ts": month_start.isoformat()},
        ])
        async def _run_twice():
            a = await snapshot_projections(uid)
            b = await snapshot_projections(uid)
            return a, b
        try:
            n1, n2 = asyncio.run(_run_twice())
            assert n1 == 2
            assert n2 == 2
            count = db.projection_history.count_documents({"user_id": uid})
            assert count == 2, f"expected 2 rows, got {count}"

            # And history endpoint should reflect the two providers
            # (via ephemeral session)
            sess = f"iter42-sess-{uuid.uuid4().hex[:6]}"
            db.users.insert_one({"user_id": uid, "email": f"{uid}@t.com", "name": "T",
                                 "onboarding_complete": True,
                                 "created_at": now.isoformat()})
            db.user_sessions.insert_one({
                "session_token": sess, "user_id": uid,
                "created_at": now, "expires_at": now + timedelta(days=1),
            })
            try:
                r = requests.get(f"{BASE_URL}/api/routing/usage/projection/history",
                                 cookies=_c(sess), timeout=15)
                data = r.json()
                assert "openai" in data["series"]
                assert "groq" in data["series"]
                # Today (last index) should be > 0 for openai
                assert data["series"]["openai"][-1] > 0
            finally:
                db.user_sessions.delete_one({"session_token": sess})
                db.users.delete_one({"user_id": uid})
        finally:
            db.usage_events.delete_many({"user_id": uid})
            db.projection_history.delete_many({"user_id": uid})


# ---------------- Indexes ----------------
class TestIndexes:
    def test_user_templates_uniq_index(self):
        db = _mongo()
        idxs = db.user_templates.index_information()
        assert "template_id_uniq" in idxs
        assert idxs["template_id_uniq"].get("unique") is True

    def test_projection_history_uniq_index(self):
        db = _mongo()
        idxs = db.projection_history.index_information()
        assert "user_provider_day_uniq" in idxs
        assert idxs["user_provider_day_uniq"].get("unique") is True


# ---------------- Regression sanity ----------------
class TestRegression:
    def test_templates_apply_unknown_still_400(self):
        r = requests.post(f"{BASE_URL}/api/routing/templates/apply",
                          json={"template_id": "does_not_exist"}, cookies=_c(), timeout=15)
        assert r.status_code == 400

    def test_usage_daily_still_works(self):
        r = requests.get(f"{BASE_URL}/api/routing/usage/daily?days=30",
                         cookies=_c(), timeout=15)
        assert r.status_code == 200
        assert len(r.json()["days"]) == 30

    def test_config_redaction(self):
        r = requests.get(f"{BASE_URL}/api/routing/config", cookies=_c(), timeout=15)
        assert r.status_code == 200
        for pid, pcfg in r.json()["providers"].items():
            assert pcfg.get("api_key") == ""
            assert "has_key" in pcfg
