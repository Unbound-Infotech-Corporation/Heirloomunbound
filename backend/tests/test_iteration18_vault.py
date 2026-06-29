"""Iteration 18: Local Vault (desktop daily compaction) backend tests.

Covers:
- POST /api/vault/compact — Claude extraction (ONE live LLM call permitted)
- POST /api/vault/compact — empty turns short-circuit (no LLM)
- POST /api/vault/compact — auth (missing / invalid token => 401)
- POST /api/vault/facts/ingest — insert + idempotent dedupe
- POST /api/vault/facts/ingest — cross-user isolation
- GET  /api/vault/status — counters & last compaction fields
- Local SQLite Vault unit (subprocess, no Qt): append_turn (text+audio),
  turns_for_day ordering, record_compaction + journal markdown, tier policies.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent.parent.parent / "frontend" / ".env")

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("PUBLIC_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"

_MONGO = MongoClient(os.environ.get("MONGO_URL"))
_DB = _MONGO[os.environ.get("DB_NAME")]

# Track for teardown
_CREATED_USERS: list[str] = []


def _mk_user_and_device(prefix: str = "u_vault") -> tuple[str, str]:
    rand = uuid.uuid4().hex[:10]
    user_id = f"{prefix}_{rand}"
    device_token = f"comp_vault_{secrets.token_urlsafe(20)}"
    now = datetime.now(timezone.utc).isoformat()
    _DB.users.insert_one({
        "user_id": user_id,
        "email": f"{prefix}_{rand}@example.com",
        "name": "Vault Test",
        "purchased_lifetime": True,
        "account_status": "active",
        "created_at": now,
    })
    _DB.companion_devices.insert_one({
        "device_id": f"dev_{rand}",
        "user_id": user_id,
        "name": "Test Vault PC",
        "device_token": device_token,
        "revoked": False,
        "created_at": now,
        "last_seen": None,
    })
    _CREATED_USERS.append(user_id)
    return user_id, device_token


@pytest.fixture(scope="module")
def user_a():
    return _mk_user_and_device("u_vault_a")


@pytest.fixture(scope="module")
def user_b():
    return _mk_user_and_device("u_vault_b")


def _bearer(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ============== /api/vault/compact ==============
class TestVaultCompact:
    """ONE live Claude call permitted in this class."""

    def test_compact_live_extracts_facts(self, user_a):
        _, tok = user_a
        body = {
            "date": "2026-06-29",
            "turns": [
                {"role": "user",
                 "text": "I just moved to Vermont last month and my son Elias is 12.",
                 "kind": "chat"},
                {"role": "assistant", "text": "Big move.", "kind": "chat"},
            ],
        }
        r = requests.post(f"{API}/vault/compact", json=body,
                          headers=_bearer(tok), timeout=90)
        assert r.status_code == 200, r.text[:500]
        data = r.json()
        assert data["turns_seen"] == 2
        assert isinstance(data["summary"], str) and data["summary"].strip(), \
            "summary must be non-empty"
        assert isinstance(data["facts"], list)
        assert isinstance(data["themes"], list)
        assert len(data["facts"]) >= 1, f"expected >=1 fact, got {data['facts']}"
        allowed_kinds = {"family", "place", "career", "belief", "milestone",
                         "phrase", "interest", "skill", "relationship",
                         "story", "other"}
        for f in data["facts"]:
            assert isinstance(f.get("fact"), str) and f["fact"].strip(), \
                f"empty fact: {f}"
            assert f.get("kind") in allowed_kinds, f"bad kind: {f}"

    def test_compact_empty_short_circuit(self, user_a):
        _, tok = user_a
        r = requests.post(f"{API}/vault/compact",
                          json={"date": "2026-06-29", "turns": []},
                          headers=_bearer(tok), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["facts"] == []
        assert d["turns_seen"] == 0
        assert d["summary"] == "(no conversation today)"

    def test_compact_missing_auth(self):
        r = requests.post(f"{API}/vault/compact",
                          json={"date": "2026-06-29", "turns": []}, timeout=10)
        assert r.status_code == 401

    def test_compact_invalid_token(self):
        r = requests.post(f"{API}/vault/compact",
                          json={"date": "2026-06-29", "turns": []},
                          headers=_bearer("comp_invalid_xxx"), timeout=10)
        assert r.status_code == 401


# ============== /api/vault/facts/ingest ==============
class TestVaultIngest:
    def test_ingest_insert_then_idempotent(self, user_a):
        uid, tok = user_a
        # Clean any prior desktop_compaction facts for a deterministic count
        _DB.memory_facts.delete_many(
            {"user_id": uid, "source": "desktop_compaction"}
        )

        payload = {
            "facts": [
                {"fact": "Lives in Vermont as of 2026", "kind": "place"},
                {"fact": "Has a 12 year old son named Elias", "kind": "family"},
            ],
            "date": "2026-06-29",
        }
        r1 = requests.post(f"{API}/vault/facts/ingest", json=payload,
                           headers=_bearer(tok), timeout=15)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1 == {"inserted": 2, "skipped": 0}, d1

        # Verify persisted with right metadata
        docs = list(_DB.memory_facts.find(
            {"user_id": uid, "source": "desktop_compaction"},
            {"_id": 0},
        ))
        assert len(docs) == 2
        for d in docs:
            assert d["source"] == "desktop_compaction"
            assert d["source_date"] == "2026-06-29"
            assert d["fact"]
            assert d["kind"] in {"place", "family"}

        # Idempotent: re-ingest same facts => skipped=2, inserted=0
        r2 = requests.post(f"{API}/vault/facts/ingest", json=payload,
                           headers=_bearer(tok), timeout=15)
        assert r2.status_code == 200
        assert r2.json() == {"inserted": 0, "skipped": 2}

        # Case-insensitive dedupe sanity
        payload2 = {
            "facts": [{"fact": "lives in vermont AS OF 2026", "kind": "place"}],
            "date": "2026-06-29",
        }
        r3 = requests.post(f"{API}/vault/facts/ingest", json=payload2,
                           headers=_bearer(tok), timeout=15)
        assert r3.status_code == 200
        assert r3.json()["inserted"] == 0

    def test_ingest_does_not_leak_across_users(self, user_a, user_b):
        uid_a, _ = user_a
        uid_b, tok_b = user_b
        # Pre-state: user B has zero desktop_compaction facts
        n_before = _DB.memory_facts.count_documents(
            {"user_id": uid_b, "source": "desktop_compaction"})
        assert n_before == 0

        # After test_ingest_insert_then_idempotent above, A has facts.
        a_count = _DB.memory_facts.count_documents(
            {"user_id": uid_a, "source": "desktop_compaction"})
        assert a_count >= 2, "precondition: user_a should have ingested facts"

        # B should still see zero desktop_compaction facts
        n_after = _DB.memory_facts.count_documents(
            {"user_id": uid_b, "source": "desktop_compaction"})
        assert n_after == 0, "cross-user leak!"

        # And B can ingest independently
        r = requests.post(f"{API}/vault/facts/ingest",
                          json={"facts": [{"fact": "User B unique fact alpha",
                                           "kind": "other"}],
                                "date": "2026-06-30"},
                          headers=_bearer(tok_b), timeout=15)
        assert r.status_code == 200
        assert r.json() == {"inserted": 1, "skipped": 0}
        # A's count unchanged
        a_count2 = _DB.memory_facts.count_documents(
            {"user_id": uid_a, "source": "desktop_compaction"})
        assert a_count2 == a_count


# ============== /api/vault/status ==============
class TestVaultStatus:
    def test_status_shape_and_counts(self, user_a):
        uid, tok = user_a
        r = requests.get(f"{API}/vault/status",
                         headers=_bearer(tok), timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("total_facts", "facts_from_vault",
                    "total_archive_entries", "last_compaction_at",
                    "last_compaction_date"):
            assert key in d, f"missing key: {key}"
        # Verify facts_from_vault counts ONLY desktop_compaction source
        expected_vault = _DB.memory_facts.count_documents(
            {"user_id": uid, "source": "desktop_compaction"})
        assert d["facts_from_vault"] == expected_vault
        # total_facts >= vault facts
        assert d["total_facts"] >= d["facts_from_vault"]
        # Last compaction date matches our ingest
        assert d["last_compaction_date"] == "2026-06-29"
        assert d["last_compaction_at"]

    def test_status_missing_auth(self):
        r = requests.get(f"{API}/vault/status", timeout=10)
        assert r.status_code == 401


# ============== Local Vault SQLite unit (subprocess, no Qt) ==============
class TestLocalVaultSQLite:
    def test_sqlite_vault_lifecycle(self, tmp_path):
        """Drive vault.py through append/read/compact/tier policies."""
        script = textwrap.dedent(f"""
            import json, os, sys, sqlite3, time
            from pathlib import Path
            from datetime import datetime, timedelta

            sys.path.insert(0, '/app/companion_desktop')
            # Stub config so vault_root() resolves to our tempdir without
            # importing real config-file persistence machinery.
            import types
            cfg = types.ModuleType('heirloom.config')
            ROOT = Path({str(tmp_path)!r})
            cfg.load_settings = lambda: {{"vault_folder": str(ROOT)}}
            cfg.save_settings = lambda d: None
            sys.modules['heirloom.config'] = cfg

            # Build a minimal heirloom package shim if not yet imported
            import importlib
            from heirloom import vault as V

            v = V.Vault(root=ROOT)
            today = datetime.now().strftime("%Y-%m-%d")

            # (a) three turns, one with audio bytes
            t1 = v.append_turn('conv1', 'user', 'first thing', kind='chat')
            t2 = v.append_turn('conv1', 'assistant', 'reply 1', kind='chat')
            t3 = v.append_turn('conv1', 'user', 'with voice', kind='voice',
                               audio_bytes=b'RIFFxxxxWAVEfmt ')

            # Verify audio file exists under raw/<today>/audio/<turn_id>.wav
            audio_file = ROOT / 'raw' / today / 'audio' / f'{{t3}}.wav'
            assert audio_file.exists(), f"audio file missing: {{audio_file}}"

            # (b) turns_for_day returns 3 ordered rows
            rows = v.turns_for_day(today)
            assert len(rows) == 3, f"expected 3 turns got {{len(rows)}}"
            assert [r.turn_id for r in rows] == [t1, t2, t3], "order broken"

            # (c) record_compaction writes compactions row + journal markdown
            v.record_compaction(today,
                                turns_seen=3, facts_extracted=2,
                                summary='A test day.',
                                themes=['moving','family'])
            journal = ROOT / 'journals' / f'{{today}}.md'
            assert journal.exists(), 'journal markdown not written'
            content = journal.read_text(encoding='utf-8')
            assert 'A test day.' in content
            assert '- moving' in content
            # Verify compactions row exists
            con = sqlite3.connect(str(v.db_path))
            row = con.execute(
                "SELECT date,turns_seen,facts_extracted FROM compactions WHERE date=?",
                (today,)).fetchone()
            con.close()
            assert row == (today, 3, 2), f"bad compactions row: {{row}}"

            # ---- separate clean vault for the 'lite' tier scenario ----
            lite_root = ROOT / 'lite_test'
            lite_root.mkdir()
            cfg.load_settings = lambda: {{"vault_folder": str(lite_root)}}
            v_lite = V.Vault(root=lite_root)
            # Backdate a "yesterday" compacted day with one audio turn
            yest = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
            yt = v_lite.append_turn('cY', 'user', 'old day', kind='chat',
                                     audio_bytes=b'oldaudio')
            # Force its 'day' column to yest
            con = sqlite3.connect(str(v_lite.db_path))
            new_audio = lite_root / 'raw' / yest / 'audio' / f'{{yt}}.wav'
            new_audio.parent.mkdir(parents=True, exist_ok=True)
            # move audio file
            old_path = con.execute(
                "SELECT audio_path FROM turns WHERE turn_id=?", (yt,)
            ).fetchone()[0]
            Path(old_path).rename(new_audio)
            con.execute("UPDATE turns SET day=?, audio_path=? WHERE turn_id=?",
                        (yest, str(new_audio), yt))
            con.commit()
            con.close()
            v_lite.record_compaction(yest, turns_seen=1, facts_extracted=0,
                                     summary='old', themes=[])
            # Apply 'lite' policy
            res = v_lite.apply_tier_policy('lite')
            assert res['deleted_turns'] >= 1, f"lite did not delete turns: {{res}}"
            assert res['deleted_files'] >= 1, f"lite did not delete audio: {{res}}"
            assert not new_audio.exists(), "audio file not removed by lite"
            # Row should be gone
            con = sqlite3.connect(str(v_lite.db_path))
            n = con.execute("SELECT COUNT(*) FROM turns WHERE day=?",
                            (yest,)).fetchone()[0]
            con.close()
            assert n == 0, "turn rows for compacted day still present after lite"

            # ---- partial tier: row >30 days old should keep row, drop audio ----
            part_root = ROOT / 'partial_test'
            part_root.mkdir()
            cfg.load_settings = lambda: {{"vault_folder": str(part_root)}}
            v_part = V.Vault(root=part_root)
            old_day = (datetime.now() - timedelta(days=31)).strftime('%Y-%m-%d')
            pt = v_part.append_turn('cP', 'user', 'ancient', kind='voice',
                                    audio_bytes=b'ancient')
            con = sqlite3.connect(str(v_part.db_path))
            ancient_audio = (part_root / 'raw' / old_day / 'audio' / f'{{pt}}.wav')
            ancient_audio.parent.mkdir(parents=True, exist_ok=True)
            cur_audio = con.execute(
                "SELECT audio_path FROM turns WHERE turn_id=?", (pt,)
            ).fetchone()[0]
            Path(cur_audio).rename(ancient_audio)
            con.execute("UPDATE turns SET day=?, audio_path=? WHERE turn_id=?",
                        (old_day, str(ancient_audio), pt))
            con.commit()
            con.close()
            res2 = v_part.apply_tier_policy('partial')
            assert res2['deleted_files'] >= 1, f"partial did not delete audio: {{res2}}"
            assert not ancient_audio.exists(), "ancient audio still on disk"
            con = sqlite3.connect(str(v_part.db_path))
            r = con.execute(
                "SELECT audio_path FROM turns WHERE turn_id=?", (pt,)
            ).fetchone()
            con.close()
            assert r is not None, "partial deleted the row (it should keep it)"
            assert r[0] is None, f"audio_path should be NULL, got {{r[0]}}"

            print("LOCAL_VAULT_OK")
        """)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, timeout=60,
        )
        out = proc.stdout.decode() + "\n" + proc.stderr.decode()
        assert proc.returncode == 0, f"subprocess failed:\n{out}"
        assert "LOCAL_VAULT_OK" in proc.stdout.decode(), out


def teardown_module(module):  # noqa: D401
    if _CREATED_USERS:
        _DB.users.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.companion_devices.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.memory_facts.delete_many({"user_id": {"$in": _CREATED_USERS}})
