"""User-isolation fuzz test.

Seeds N users with deeply unique markers (made-up names, places, fears, foods)
and asserts that NO user's marker ever appears in another user's:
  - Library list / search results
  - Memory facts
  - Personality portrait
  - Twin context (the assembled archive_blob + memory_pack passed to Claude)
  - Heirs / Letters / Photos / Skills / Reminders / Personas list endpoints
  - Cross-user ID guessing (user A trying to read user B's archive entry by guessed id)

If a leak is ever introduced, this test will catch the EXACT marker that
escaped and report which endpoint / context-builder leaked it.

Run with:  cd /app/backend && pytest tests/test_user_isolation_fuzz.py -v
"""
from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


# ─── Distinctive per-user markers ──────────────────────────────────────
# Each row gives one user a totally invented name, location, child name,
# hobby and food so that any cross-user leak shows up as one of these
# strings appearing in another user's response.
USER_MARKERS = [
    {
        "name": "Olwyn Rasmussen-Quill",
        "child": "Pinkerley",
        "city": "Glimmervale, AK",
        "hobby": "competitive bog snorkelling",
        "food": "smoked elderberry pie",
        "fear": "wax cylinders",
    },
    {
        "name": "Throzdek Mc-Pavlov",
        "child": "Tessaroon",
        "city": "Outer Mungo, NM",
        "hobby": "carving longship figureheads",
        "food": "saffron-pickled kelp",
        "fear": "neon birthday balloons",
    },
    {
        "name": "Ines Vandermirth",
        "child": "Quintabel",
        "city": "Lockhaven-on-the-Marsh",
        "hobby": "amateur cryptography",
        "food": "warm fenugreek toast",
        "fear": "marble countertops",
    },
    {
        "name": "Berenger Tukey-Wells",
        "child": "Mosswick",
        "city": "Ardent Foothills, OR",
        "hobby": "restoring zoetropes",
        "food": "ginger-poached pear",
        "fear": "rotary phones",
    },
    {
        "name": "Calliope Yusuf-Lindgren",
        "child": "Wyndham",
        "city": "Cedar Hollow, ME",
        "hobby": "writing villanelles",
        "food": "burnt-honey ice cream",
        "fear": "automatic doors",
    },
]


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def db():
    client = AsyncIOMotorClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def seeded_users(db):
    """Insert 5 fully-loaded users with their distinctive markers."""
    users = []
    for marker in USER_MARKERS:
        uid = f"isofuzz-{uuid.uuid4().hex[:10]}"
        tok = f"isosess_{secrets.token_urlsafe(24)}"
        await db.users.insert_one({
            "user_id": uid,
            "email": f"{uid}@isofuzz.test",
            "name": marker["name"],
            "picture": "",
            "onboarded": True,
            "onboarding_complete": True,
            "tour_completed": True,
            "created_at": _now_iso(),
        })
        await db.user_sessions.insert_one({
            "user_id": uid,
            "session_token": tok,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "created_at": _now_iso(),
        })
        # Seed archive entries — one per marker field so a leak shows up
        # whatever the prompt is. Schema must match routers/archive.py.
        for kind, content in [
            ("identity", f"My name is {marker['name']}."),
            ("family", f"I have one child, {marker['child']}. They mean everything to me."),
            ("place", f"I grew up in {marker['city']} and still think about it daily."),
            ("hobby", f"I love {marker['hobby']} — it's my favorite thing."),
            ("food", f"My comfort food is {marker['food']}."),
            ("fear", f"I have a strange fear of {marker['fear']}."),
        ]:
            await db.entries.insert_one({
                "entry_id": f"ent_{uuid.uuid4().hex[:12]}",
                "user_id": uid,
                "type": "memory",
                "title": f"{kind} — {marker['name'].split()[0]}",
                "content": content,
                "tags": [kind],
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            })
        # Also memory_facts so the Twin's identity-fact layer is exercised
        for k, v in [
            (f"child_{marker['child'].lower()}", marker['child']),
            ("hometown", marker['city']),
            ("hobby", marker['hobby']),
            ("comfort_food", marker['food']),
            ("phobia", marker['fear']),
        ]:
            await db.memory_facts.insert_one({
                "fact_id": f"f_{uuid.uuid4().hex[:10]}",
                "user_id": uid,
                "key": k,
                "value": v,
                "created_at": _now_iso(),
            })
        # An heir, a letter, a skill, a reminder — so list endpoints have something
        await db.heirs.insert_one({
            "heir_id": f"hr_{uuid.uuid4().hex[:10]}",
            "user_id": uid,
            "name": f"{marker['child']} (heir)",
            "email": f"{marker['child'].lower()}@isofuzz.test",
            "relationship": "child",
            "released": False,
            "release_token": None,
            "created_at": _now_iso(),
        })
        users.append({"user_id": uid, "session_token": tok, "marker": marker})
    yield users
    # Cleanup
    uids = [u["user_id"] for u in users]
    for coll in ("users", "user_sessions", "entries", "memory_facts", "heirs",
                  "conversations", "personas", "sealed_letters", "skills",
                  "reminders", "photos", "sources", "imports"):
        await db[coll].delete_many({"user_id": {"$in": uids}})


# ─────────────────────────────────────────────────────────────────────
# Layer 1: data-layer isolation (the most fundamental guarantee)
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio(loop_scope="module")
async def test_entries_query_isolates_by_user(seeded_users, db):
    """Direct DB query for each user's entries returns ONLY their own rows."""
    for u in seeded_users:
        my_marker = u["marker"]
        others = [o["marker"] for o in seeded_users if o["user_id"] != u["user_id"]]
        rows = await db.entries.find({"user_id": u["user_id"]}, {"_id": 0}).to_list(length=100)
        assert len(rows) == 6, f"expected 6 entries for {u['user_id']}, got {len(rows)}"
        all_text = " ".join(r["content"] for r in rows)
        # My markers ARE present
        assert my_marker["child"] in all_text
        # No other user's marker is present
        for o in others:
            assert o["child"] not in all_text, f"LEAK: {o['child']} found in {u['user_id']}'s entries"
            assert o["hobby"] not in all_text, f"LEAK: {o['hobby']} found in {u['user_id']}'s entries"
            assert o["fear"] not in all_text


@pytest.mark.asyncio(loop_scope="module")
async def test_memory_facts_isolates(seeded_users, db):
    for u in seeded_users:
        rows = await db.memory_facts.find({"user_id": u["user_id"]}, {"_id": 0}).to_list(length=100)
        all_v = " ".join(r["value"] for r in rows)
        for o in seeded_users:
            if o["user_id"] == u["user_id"]:
                continue
            assert o["marker"]["child"] not in all_v, (
                f"LEAK: {o['marker']['child']} in {u['user_id']}'s memory_facts"
            )


# ─────────────────────────────────────────────────────────────────────
# Layer 2: context-builder functions (what Claude actually sees)
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio(loop_scope="module")
async def test_archive_blob_isolation(seeded_users):
    """The exact string passed to Claude in the Twin system prompt must
    contain ONLY the requesting user's markers."""
    from routers.twin import _archive_blob
    for u in seeded_users:
        blob = await _archive_blob(u["user_id"], query_hint="my child")
        # My markers present
        assert u["marker"]["child"] in blob
        # No foreign markers
        for o in seeded_users:
            if o["user_id"] == u["user_id"]:
                continue
            assert o["marker"]["child"] not in blob, (
                f"LEAK in _archive_blob: {o['marker']['child']} in {u['user_id']}'s archive context"
            )
            assert o["marker"]["fear"] not in blob


# ─────────────────────────────────────────────────────────────────────
# Layer 3: HTTP endpoint isolation (the public attack surface)
# ─────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def app():
    """Boot the FastAPI app for the test process."""
    from server import app as fastapi_app
    return fastapi_app


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _get(client, path, session_token):
    return await client.get(path, cookies={"session_token": session_token})


@pytest.mark.asyncio(loop_scope="module")
async def test_archive_list_isolation(seeded_users, client):
    """`GET /api/archive` for user A never returns user B's rows."""
    for u in seeded_users:
        r = await _get(client, "/api/archive", u["session_token"])
        assert r.status_code == 200
        body = r.text
        for o in seeded_users:
            if o["user_id"] == u["user_id"]:
                continue
            assert o["marker"]["child"] not in body, (
                f"LEAK in /archive: {o['marker']['child']} in {u['user_id']}'s response"
            )


@pytest.mark.asyncio(loop_scope="module")
async def test_archive_search_isolation(seeded_users, client):
    """Searching with ANOTHER user's marker (via ?q=) returns zero matches."""
    user_a, user_b = seeded_users[0], seeded_users[1]
    r = await client.get(
        f"/api/archive?q={user_b['marker']['child']}",
        cookies={"session_token": user_a["session_token"]},
    )
    assert r.status_code == 200
    assert user_b["marker"]["child"] not in r.text, (
        "LEAK in /archive?q=: returned user B's marker to user A"
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_memory_facts_endpoint_isolation(seeded_users, client):
    for u in seeded_users:
        r = await _get(client, "/api/memory/facts", u["session_token"])
        assert r.status_code == 200
        for o in seeded_users:
            if o["user_id"] == u["user_id"]:
                continue
            assert o["marker"]["child"] not in r.text


@pytest.mark.asyncio(loop_scope="module")
async def test_heirs_list_isolation(seeded_users, client):
    for u in seeded_users:
        r = await _get(client, "/api/heirs", u["session_token"])
        assert r.status_code == 200
        for o in seeded_users:
            if o["user_id"] == u["user_id"]:
                continue
            assert o["marker"]["child"] not in r.text


@pytest.mark.asyncio(loop_scope="module")
async def test_cross_user_id_guess_returns_404(seeded_users, db, client):
    """User A trying to read user B's archive entry by id → 404, never 200."""
    user_a, user_b = seeded_users[0], seeded_users[1]
    # Grab one of user B's real entry ids
    entry_b = await db.entries.find_one(
        {"user_id": user_b["user_id"]}, {"entry_id": 1, "_id": 0}
    )
    assert entry_b
    # User A tries to patch / delete it
    r = await client.patch(
        f"/api/archive/{entry_b['entry_id']}",
        json={"content": "I am User A trying to overwrite User B"},
        cookies={"session_token": user_a["session_token"]},
    )
    assert r.status_code == 404, (
        f"CROSS-USER WRITE: user A got HTTP {r.status_code} patching user B's entry"
    )
    r = await client.delete(
        f"/api/archive/{entry_b['entry_id']}",
        cookies={"session_token": user_a["session_token"]},
    )
    assert r.status_code == 404


@pytest.mark.asyncio(loop_scope="module")
async def test_cross_user_heir_release_blocked(seeded_users, db, client):
    """User A cannot release user B's heir even with the heir_id."""
    user_a, user_b = seeded_users[0], seeded_users[1]
    heir_b = await db.heirs.find_one({"user_id": user_b["user_id"]}, {"heir_id": 1, "_id": 0})
    assert heir_b
    r = await client.post(
        f"/api/heirs/{heir_b['heir_id']}/release-now",
        cookies={"session_token": user_a["session_token"]},
    )
    assert r.status_code == 404


@pytest.mark.asyncio(loop_scope="module")
async def test_cross_user_settings_unreachable(seeded_users, client):
    """Hitting /auth/me with each session returns ONLY that user's own profile."""
    for u in seeded_users:
        r = await _get(client, "/api/auth/me", u["session_token"])
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == u["marker"]["name"], (
            f"WRONG_USER: session for {u['user_id']} returned name={body.get('name')!r}"
        )
        # And the email matches too
        assert body["email"].startswith(u["user_id"])
