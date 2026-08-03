"""End-to-end test for semantic memory search.

Spins up a fake OpenAI-embeddings server in-process, registers it as the
user's `embeddings` provider, seeds archive entries, embeds them, and then
verifies that a semantic query returns the right entries in the right order.

Run:
    cd /app/backend && pytest tests/test_iteration32_semantic.py -v
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

pytestmark = pytest.mark.asyncio

BACKEND = os.environ.get("BACKEND_URL_INTERNAL", "http://localhost:8001")
FAKE_EMB_DIMS = 16  # small vector — plenty for a 3-entry test


def _deterministic_vec(text: str, dims: int = FAKE_EMB_DIMS) -> list[float]:
    """Deterministic pseudo-embedding: derive from SHA-256 so semantically-
    close text (sharing substrings) shares more entropy than unrelated text.

    We use a simple bag-of-words scheme: each 3-gram maps to a bucket in the
    vector. Cosine similarity between text sharing tokens > text that doesn't.
    """
    v = [0.0] * dims
    tokens = text.lower().split()
    for tok in tokens:
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
        v[h % dims] += 1.0
    # normalise
    import math
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class _FakeEmbHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        import json
        try:
            body = json.loads(raw)
        except Exception:
            self.send_response(400); self.end_headers(); return
        inputs = body.get("input") or []
        if isinstance(inputs, str):
            inputs = [inputs]
        data = [
            {"object": "embedding", "index": i, "embedding": _deterministic_vec(t)}
            for i, t in enumerate(inputs)
        ]
        out = {"object": "list", "data": data, "model": body.get("model", "fake")}
        payload = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):  # silence
        pass


@pytest.fixture(scope="module")
def fake_emb_server():
    server = HTTPServer(("127.0.0.1", 0), _FakeEmbHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}/v1"
    server.shutdown()


async def _fixture_user():
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    m = AsyncIOMotorClient(mongo_url)[db_name]
    uid = f"pytest-sem-{uuid.uuid4().hex[:8]}"
    session = f"pytest_sess_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    await m.users.insert_one({"user_id": uid, "email": f"{uid}@ex.com", "created_at": now.isoformat()})
    await m.user_sessions.insert_one({
        "user_id": uid, "session_token": session,
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "created_at": now.isoformat(),
    })
    return uid, session, m


async def _seed_entries(db, uid: str):
    now = datetime.now(timezone.utc).isoformat()
    entries = [
        {"entry_id": "e-dad", "user_id": uid, "type": "memory",
         "title": "My father's temper", "content": "Dad would slam doors when he was angry.",
         "tags": ["family", "dad"], "created_at": now},
        {"entry_id": "e-mom", "user_id": uid, "type": "memory",
         "title": "Mom's kitchen", "content": "Mom baked cinnamon rolls every Sunday morning.",
         "tags": ["family", "mom"], "created_at": now},
        {"entry_id": "e-work", "user_id": uid, "type": "value",
         "title": "My work ethic", "content": "I believe in showing up early and staying focused.",
         "tags": ["work"], "created_at": now},
    ]
    for e in entries:
        await db.entries.insert_one(e)


async def test_semantic_full_flow(fake_emb_server):
    async with httpx.AsyncClient(base_url=BACKEND, timeout=30.0) as client:
        uid, session, db = await _fixture_user()
        try:
            hdr = {"Authorization": f"Bearer {session}"}

            # Configure provider to point at the fake server
            r = await client.put("/api/providers", headers=hdr, json={
                "embeddings": {
                    "enabled": True,
                    "base_url": fake_emb_server,
                    "api_key": "",
                    "model": "fake-emb",
                    "provider_type": "openai_compat",
                },
            })
            assert r.status_code == 200, r.text

            await _seed_entries(db, uid)

            # Status should show 3 total, 0 embedded
            r = await client.get("/api/memory/search/status", headers=hdr)
            assert r.status_code == 200
            s = r.json()
            assert s["has_provider"] is True
            assert s["total_entries"] == 3
            assert s["embedded"] == 0

            # Trigger sync embed
            r = await client.post("/api/memory/search/embed/sync", headers=hdr, json={"force": False})
            assert r.status_code == 200, r.text
            assert r.json()["embedded"] == 3

            # Status now: all 3 embedded
            r = await client.get("/api/memory/search/status", headers=hdr)
            assert r.json()["embedded"] == 3

            # Semantic query — "dad" should surface e-dad first
            r = await client.post("/api/memory/search", headers=hdr,
                                  json={"query": "father angry temper", "limit": 3})
            assert r.status_code == 200
            data = r.json()
            assert data["mode"] == "semantic"
            top = data["results"][0]
            assert top["entry_id"] == "e-dad", f"expected e-dad, got {top}"

            # Query about baking should surface mom
            r = await client.post("/api/memory/search", headers=hdr,
                                  json={"query": "cinnamon Sunday baking", "limit": 3})
            top = r.json()["results"][0]
            assert top["entry_id"] == "e-mom"

            # Query about focus should surface e-work
            r = await client.post("/api/memory/search", headers=hdr,
                                  json={"query": "focused staying disciplined", "limit": 3})
            top = r.json()["results"][0]
            assert top["entry_id"] == "e-work"

            # Idempotency: second sync run embeds 0 (all shas match)
            r = await client.post("/api/memory/search/embed/sync", headers=hdr, json={"force": False})
            assert r.json()["embedded"] == 0

        finally:
            await db.users.delete_many({"user_id": uid})
            await db.user_sessions.delete_many({"user_id": uid})
            await db.user_providers.delete_many({"user_id": uid})
            await db.entries.delete_many({"user_id": uid})
            await db.archive_embeddings.delete_many({"user_id": uid})


async def test_search_falls_back_when_no_provider():
    async with httpx.AsyncClient(base_url=BACKEND, timeout=15.0) as client:
        uid, session, db = await _fixture_user()
        try:
            hdr = {"Authorization": f"Bearer {session}"}
            await _seed_entries(db, uid)

            # No provider configured — should keyword-fallback
            r = await client.post("/api/memory/search", headers=hdr,
                                  json={"query": "temper", "limit": 5})
            assert r.status_code == 200
            data = r.json()
            assert data["mode"] == "keyword"
            assert data.get("reason") == "no_provider"
            assert any(e["entry_id"] == "e-dad" for e in data["results"])
        finally:
            await db.users.delete_many({"user_id": uid})
            await db.user_sessions.delete_many({"user_id": uid})
            await db.entries.delete_many({"user_id": uid})
