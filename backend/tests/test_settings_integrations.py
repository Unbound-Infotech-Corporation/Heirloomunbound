"""Settings / integrations wiring checks."""
from __future__ import annotations

import asyncio
import os


def test_user_keys_oauth_reads_connections(monkeypatch):
    from routers import user_keys as uk

    class FakeDB:
        class oauth_connections:
            @staticmethod
            async def find_one(query, *a, **k):
                if query.get("provider") == "spotify":
                    return {"access_token": "tok_spotify"}
                return None

    monkeypatch.setattr(uk, "db", FakeDB())
    monkeypatch.setenv("EMERGENT_LLM_KEY", "test-key")

    async def _run():
        # Call the route function with a fake user
        from fastapi import Depends
        user = {"user_id": "u1", "elevenlabs_api_key": "", "d_id_api_key": "", "fal_api_key": ""}
        # Directly invoke get_status's body by reusing logic
        out = {}
        for svc, field in uk.USER_FIELDS.items():
            has_user = bool((user.get(field) or "").strip())
            has_admin = bool(uk.ADMIN_KEYS.get(svc))
            out[svc] = {
                "configured": has_user or has_admin,
                "source": "you" if has_user else ("admin" if has_admin else "none"),
            }
        for svc in uk.OAUTH_SERVICES:
            conn = await FakeDB.oauth_connections.find_one({"user_id": "u1", "provider": svc})
            has_oauth = bool(conn and (conn.get("access_token") or "").strip())
            out[svc] = {
                "configured": has_oauth,
                "source": "you" if has_oauth else "none",
                "oauth": True,
            }
        assert out["spotify"]["configured"] is True
        assert out["github"]["configured"] is False

        # Also hit the real endpoint function with monkeypatched db
        class UserDep:
            pass

        status = await uk.get_status(user)
        assert status["spotify"]["source"] == "you"
        assert status["github"]["source"] == "none"
        assert status["llm"]["configured"] is True

    asyncio.get_event_loop().run_until_complete(_run())


def test_avatar_prefers_user_elevenlabs_voice_id():
    """Regression: talking-head should prefer users.elevenlabs_voice_id."""
    # Static check of source — the create_talk path was updated to read user field first
    from pathlib import Path
    src = Path("routers/avatar.py").read_text()
    assert 'user.get("elevenlabs_voice_id")' in src
    assert "elevenlabs_settings" in src


def test_easy_setup_and_death_governance_still_import():
    import death_governance as dg
    from routers import easy_setup, executor_lock, export
    assert dg.MODE_DEATH_GOVERNANCE == "death_governance"
    assert easy_setup.router.prefix == "/easy-setup"
