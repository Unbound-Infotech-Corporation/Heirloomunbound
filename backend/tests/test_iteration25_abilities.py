"""Iteration 25 — Abilities framework.

Tests the abilities catalog endpoint, enable/disable + permission gating,
and that ability toggles actually filter the twin's tool schemas + short-circuits.

Uses fork23 persistent test session.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
SESSION_TOKEN = "test_session_fork23"
USER_ID = "test-user-fork23"

ALL_IDS = {"web", "email", "calendar", "people", "music", "smart_home", "pc_control", "screen_vision", "business", "terminal"}
DEFAULT_ENABLED = {"web", "email", "calendar", "people", "music", "smart_home", "pc_control", "screen_vision", "business"}


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SESSION_TOKEN}",
    })
    return s


# ---------------------------------------------------------------- Catalog / API
class TestAbilitiesCatalog:
    def test_list_abilities_shape(self, api):
        r = api.get(f"{BASE_URL}/api/abilities")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "abilities" in data and "companion_connected" in data
        assert isinstance(data["companion_connected"], bool)
        items = {a["id"]: a for a in data["abilities"]}
        assert set(items.keys()) == ALL_IDS
        required_keys = {
            "id", "name", "tagline", "icon", "category",
            "requires_companion", "permissions", "tool_count",
            "enabled", "granted_permissions",
        }
        for a in data["abilities"]:
            assert required_keys.issubset(a.keys()), a

    def test_terminal_disable_first_then_defaults_hold(self, api):
        # Force fork23 to defaults before checking (in case previous tests left junk)
        for aid in ["web", "email", "calendar", "people", "music", "smart_home", "pc_control", "screen_vision", "business"]:
            perms = _perms_for(api, aid)
            api.post(f"{BASE_URL}/api/abilities/{aid}/enable", json={"granted_permissions": perms})
        api.post(f"{BASE_URL}/api/abilities/terminal/disable")

        r = api.get(f"{BASE_URL}/api/abilities")
        items = {a["id"]: a for a in r.json()["abilities"]}
        for aid in DEFAULT_ENABLED:
            assert items[aid]["enabled"] is True, aid
        assert items["terminal"]["enabled"] is False


def _perms_for(api, ability_id: str) -> list[str]:
    r = api.get(f"{BASE_URL}/api/abilities")
    for a in r.json()["abilities"]:
        if a["id"] == ability_id:
            return [p["id"] for p in a["permissions"]]
    return []


class TestEnableDisable:
    def test_enable_missing_permission_400(self, api):
        # ensure terminal off
        api.post(f"{BASE_URL}/api/abilities/terminal/disable")
        r = api.post(f"{BASE_URL}/api/abilities/terminal/enable", json={"granted_permissions": []})
        assert r.status_code == 400, r.text
        assert "Missing permission" in r.text

    def test_enable_success_then_disable(self, api):
        r = api.post(
            f"{BASE_URL}/api/abilities/terminal/enable",
            json={"granted_permissions": ["run_shell"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is True
        assert "run_shell" in r.json()["granted_permissions"]

        # verify via GET
        items = {a["id"]: a for a in api.get(f"{BASE_URL}/api/abilities").json()["abilities"]}
        assert items["terminal"]["enabled"] is True

        r2 = api.post(f"{BASE_URL}/api/abilities/terminal/disable")
        assert r2.status_code == 200
        assert r2.json()["enabled"] is False

        items = {a["id"]: a for a in api.get(f"{BASE_URL}/api/abilities").json()["abilities"]}
        assert items["terminal"]["enabled"] is False

    def test_unknown_ability_404(self, api):
        r = api.post(f"{BASE_URL}/api/abilities/nope/disable")
        assert r.status_code == 404
        r2 = api.post(f"{BASE_URL}/api/abilities/nope/enable", json={"granted_permissions": []})
        assert r2.status_code == 404


# --------------------------------------------------------------- Tool gating (in-process)
class TestToolGating:
    """Verifies abilities.enabled_tool_names + build_abilities_prompt directly."""

    def test_gating_core_and_toggle(self):
        import sys
        sys.path.insert(0, "/app/backend")
        import abilities as ab  # noqa

        async def _run():
            uid = USER_ID
            # baseline: enable defaults, terminal off
            for aid in ["web", "email", "calendar", "people", "music", "smart_home", "pc_control", "screen_vision", "business"]:
                perms = [p["id"] for p in ab.ABILITY_BY_ID[aid]["permissions"]]
                await ab.set_state(uid, aid, True, perms)
            await ab.set_state(uid, "terminal", False, [])

            tools = await ab.enabled_tool_names(uid)
            # core always present
            for t in ab.CORE_TOOLS:
                assert t in tools
            # web tools present
            assert {"web_search", "web_fetch", "get_weather"}.issubset(tools)
            # business tools present (default on)
            assert {"write_google_doc", "write_google_sheet", "research_seo", "post_to_social"}.issubset(tools)
            # terminal absent
            assert "run_command" not in tools
            # prompt block only includes enabled abilities
            enabled_ids = await ab.enabled_ability_ids(uid)
            prompt = ab.build_abilities_prompt(enabled_ids)
            assert "Web & weather (enabled)" in prompt
            assert "Terminal (enabled)" not in prompt

            # disable web -> web tools gone, core still present
            await ab.set_state(uid, "web", False, [])
            tools2 = await ab.enabled_tool_names(uid)
            for t in ab.CORE_TOOLS:
                assert t in tools2
            assert "web_search" not in tools2
            assert "web_fetch" not in tools2
            assert "get_weather" not in tools2

            # disable pc_control -> pc tools gone
            await ab.set_state(uid, "pc_control", False, [])
            tools3 = await ab.enabled_tool_names(uid)
            assert "open_on_pc" not in tools3
            assert "control_media" not in tools3
            assert "power_action" not in tools3

            # enable terminal -> run_command present
            await ab.set_state(uid, "terminal", True, ["run_shell"])
            tools4 = await ab.enabled_tool_names(uid)
            assert "run_command" in tools4

            # restore defaults + terminal off
            for aid in ["web", "email", "calendar", "people", "music", "smart_home", "pc_control", "screen_vision", "business"]:
                perms = [p["id"] for p in ab.ABILITY_BY_ID[aid]["permissions"]]
                await ab.set_state(uid, aid, True, perms)
            await ab.set_state(uid, "terminal", False, [])

        asyncio.get_event_loop().run_until_complete(_run())


# --------------------------------------------------------------- Twin gating (SSE)
def _create_conversation(api) -> str:
    r = api.post(f"{BASE_URL}/api/twin/start", json={})
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


def _stream(api, conv_id: str, msg: str, timeout: int = 60) -> str:
    with api.post(
        f"{BASE_URL}/api/twin/message",
        json={"conversation_id": conv_id, "message": msg},
        stream=True,
        timeout=timeout,
    ) as r:
        assert r.status_code == 200, r.text
        chunks = []
        for line in r.iter_lines(decode_unicode=True):
            if line is None:
                continue
            chunks.append(line)
            if line == "event: done" or line.startswith("data: {}") and "done" in "\n".join(chunks[-3:]):
                # keep going until we see the terminating "event: done"
                pass
        return "\n".join(chunks)


class TestTwinGating:
    def test_music_short_circuit_gated(self, api):
        # Disable music, ensure no music action
        r = api.post(f"{BASE_URL}/api/abilities/music/disable")
        assert r.status_code == 200
        conv = _create_conversation(api)
        raw = _stream(api, conv, "play some Pink Floyd")
        assert "event: done" in raw
        # No music action event
        assert '"kind": "music"' not in raw and '"kind":"music"' not in raw

        # Re-enable music and confirm short-circuit fires
        perms = _perms_for(api, "music")
        api.post(f"{BASE_URL}/api/abilities/music/enable", json={"granted_permissions": perms})
        conv2 = _create_conversation(api)
        raw2 = _stream(api, conv2, "play some Pink Floyd")
        assert "event: action" in raw2
        assert '"kind": "music"' in raw2 or '"kind":"music"' in raw2

    def test_web_tool_gated(self, api):
        # Disable web ability -> twin cannot call web_search
        r = api.post(f"{BASE_URL}/api/abilities/web/disable")
        assert r.status_code == 200
        conv = _create_conversation(api)
        raw = _stream(api, conv, "search the web for today's news headlines please", timeout=90)
        assert "event: done" in raw
        # No web_search tool event should appear
        assert "web_search" not in raw

        # Restore
        perms = _perms_for(api, "web")
        api.post(f"{BASE_URL}/api/abilities/web/enable", json={"granted_permissions": perms})


# ------------------------------------------------------------------- Teardown restore
def teardown_module(module):
    """Restore fork23 to defaults so future runs are clean."""
    import requests as _r
    s = _r.Session()
    s.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SESSION_TOKEN}",
    })
    catalog = s.get(f"{BASE_URL}/api/abilities").json()
    perms_by_id = {a["id"]: [p["id"] for p in a["permissions"]] for a in catalog["abilities"]}
    for aid in ["web", "email", "calendar", "people", "music", "smart_home", "pc_control", "screen_vision", "business"]:
        s.post(f"{BASE_URL}/api/abilities/{aid}/enable", json={"granted_permissions": perms_by_id[aid]})
    s.post(f"{BASE_URL}/api/abilities/terminal/disable")
