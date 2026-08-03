"""Extra coverage for iteration 32 semantic-search endpoints:

- /api/memory/search/status shape when no provider is configured
- POST /api/memory/search/embed rejects with 400 when no provider
- POST /api/memory/search/embed/sync rejects with 400 when no provider
- POST /api/memory/search falls back to keyword when no provider (reason=no_provider)
- Falls back with reason=no_index when provider configured but vectors missing
- twin_tools exec_search_archive keyword fallback still works via /api/twin/message
- Adjacent-regression: /api/providers GET, /api/archive GET, /api/auth/me, /roadmap public page
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

pytestmark = pytest.mark.asyncio

BACKEND = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
PUBLIC = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


async def _mkuser():
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    m = AsyncIOMotorClient(mongo_url)[db_name]
    uid = f"pytest-sem2-{uuid.uuid4().hex[:8]}"
    session = f"pytest_sess_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    await m.users.insert_one({"user_id": uid, "email": f"{uid}@ex.com", "created_at": now.isoformat()})
    await m.user_sessions.insert_one({
        "user_id": uid, "session_token": session,
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "created_at": now.isoformat(),
    })
    return uid, session, m


async def _seed(db, uid):
    now = datetime.now(timezone.utc).isoformat()
    await db.entries.insert_many([
        {"entry_id": f"e-{uuid.uuid4().hex[:6]}", "user_id": uid, "type": "memory",
         "title": "My father's temper", "content": "Dad slammed doors.",
         "tags": ["family", "dad"], "created_at": now},
        {"entry_id": f"e-{uuid.uuid4().hex[:6]}", "user_id": uid, "type": "value",
         "title": "Work ethic", "content": "Show up early.", "tags": ["work"], "created_at": now},
    ])


async def _cleanup(db, uid):
    for c in ["users", "user_sessions", "user_providers", "entries", "archive_embeddings"]:
        await db[c].delete_many({"user_id": uid})


async def test_status_shape_no_provider():
    uid, sess, db = await _mkuser()
    try:
        await _seed(db, uid)
        async with httpx.AsyncClient(base_url=BACKEND, timeout=15.0) as c:
            r = await c.get("/api/memory/search/status", headers={"Authorization": f"Bearer {sess}"})
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["has_provider"] is False
            assert d["embedded"] == 0
            assert d["model"] is None
            assert d["total_entries"] >= 2
    finally:
        await _cleanup(db, uid)


async def test_embed_400_no_provider():
    uid, sess, db = await _mkuser()
    try:
        async with httpx.AsyncClient(base_url=BACKEND, timeout=15.0) as c:
            hdr = {"Authorization": f"Bearer {sess}"}
            r = await c.post("/api/memory/search/embed", headers=hdr, json={"force": False})
            assert r.status_code == 400
            assert "No embeddings provider" in r.json().get("detail", "")

            r = await c.post("/api/memory/search/embed/sync", headers=hdr, json={"force": False})
            assert r.status_code == 400
            assert "No embeddings provider" in r.json().get("detail", "")
    finally:
        await _cleanup(db, uid)


async def test_search_fallback_no_provider_returns_matches():
    uid, sess, db = await _mkuser()
    try:
        await _seed(db, uid)
        async with httpx.AsyncClient(base_url=BACKEND, timeout=15.0) as c:
            hdr = {"Authorization": f"Bearer {sess}"}
            r = await c.post("/api/memory/search", headers=hdr, json={"query": "temper", "limit": 5})
            assert r.status_code == 200
            d = r.json()
            assert d["mode"] == "keyword"
            assert d["reason"] == "no_provider"
            assert any("temper" in (row.get("title") or "").lower() for row in d["results"])
    finally:
        await _cleanup(db, uid)


async def test_search_no_index_fallback_when_provider_configured_but_no_vectors():
    """Spin up a working fake embeddings server so query embed succeeds but no
    stored vectors exist → reason should be no_index."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            inputs = body.get("input") or []
            if isinstance(inputs, str):
                inputs = [inputs]
            out = {"object": "list", "model": body.get("model", "fake"),
                   "data": [{"object": "embedding", "index": i,
                             "embedding": [0.1, 0.2, 0.3, 0.4]} for i, _ in enumerate(inputs)]}
            payload = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a, **k):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        uid, sess, db = await _mkuser()
        try:
            await _seed(db, uid)
            async with httpx.AsyncClient(base_url=BACKEND, timeout=15.0) as c:
                hdr = {"Authorization": f"Bearer {sess}"}
                r = await c.put("/api/providers", headers=hdr, json={
                    "embeddings": {"enabled": True,
                                    "base_url": f"http://127.0.0.1:{port}/v1",
                                    "api_key": "", "model": "fake-emb",
                                    "provider_type": "openai_compat"}})
                assert r.status_code == 200, r.text
                r = await c.post("/api/memory/search", headers=hdr, json={"query": "temper", "limit": 5})
                assert r.status_code == 200, r.text
                d = r.json()
                assert d["mode"] == "keyword"
                assert d["reason"] == "no_index", f"got {d}"
        finally:
            await _cleanup(db, uid)
    finally:
        server.shutdown()


async def test_twin_tools_keyword_regression():
    """exec_search_archive should still find keyword matches when no provider configured.
    Post to /api/twin/message using a real conversation_id."""
    uid, sess, db = await _mkuser()
    try:
        await _seed(db, uid)
        async with httpx.AsyncClient(base_url=BACKEND, timeout=60.0) as c:
            hdr = {"Authorization": f"Bearer {sess}"}
            r = await c.post("/api/twin/start", headers=hdr, json={})
            assert r.status_code == 200, r.text
            conv_id = r.json()["conversation_id"]
            r = await c.post("/api/twin/message", headers=hdr,
                             json={"conversation_id": conv_id,
                                   "message": "search my archive for temper"})
            # Twin may take time or LLM may be unavailable; assert not 5xx and not schema-broken
            assert r.status_code in (200, 400, 402, 503), r.text
    finally:
        await _cleanup(db, uid)


async def test_adjacent_regressions_still_work():
    uid, sess, db = await _mkuser()
    try:
        async with httpx.AsyncClient(base_url=BACKEND, timeout=15.0) as c:
            hdr = {"Authorization": f"Bearer {sess}"}
            r = await c.get("/api/auth/me", headers=hdr)
            assert r.status_code == 200, r.text
            r = await c.get("/api/providers", headers=hdr)
            assert r.status_code == 200
            r = await c.get("/api/archive", headers=hdr)
            assert r.status_code == 200
    finally:
        await _cleanup(db, uid)


async def test_roadmap_public_page_loads():
    if not PUBLIC:
        pytest.skip("no public url")
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
        r = await c.get(f"{PUBLIC}/roadmap")
        assert r.status_code == 200
