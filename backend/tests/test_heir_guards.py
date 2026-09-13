"""Heir portal session + release PATCH hygiene."""
from __future__ import annotations

from pathlib import Path

from heir_guards import can_reuse_conversation, portal_conversation_id, sanitize_heir_patch

ROOT = Path(__file__).resolve().parents[2]


def test_portal_session_ignores_owner_conversation_ids():
    hid = "hr_abc123"
    expected = "heir_hr_abc123"
    assert portal_conversation_id(hid) == expected
    assert portal_conversation_id(hid, None) == expected
    assert portal_conversation_id(hid, "") == expected
    assert portal_conversation_id(hid, expected) == expected
    for stolen in (
        "comp_ownerthread",
        "twin_abc",
        "assist_abc",
        "owner_abc",
        "heir_hr_other",
        "heir_hr_abc123_extra",
        "../twin",
    ):
        assert portal_conversation_id(hid, stolen) == expected


def test_can_reuse_conversation_rejects_cross_rail_ids():
    assert can_reuse_conversation(
        requested_kind="companion_twin",
        existing_kind="companion_twin",
        conversation_id="comp_abc",
    )
    assert can_reuse_conversation(
        requested_kind="heir_portal",
        existing_kind="heir_portal",
        conversation_id="heir_hr_abc",
    )
    assert not can_reuse_conversation(
        requested_kind="companion_twin",
        existing_kind="companion_owner",
        conversation_id="owner_abc",
    )
    assert not can_reuse_conversation(
        requested_kind="companion_twin",
        existing_kind="companion_assistant",
        conversation_id="assist_abc",
    )
    assert not can_reuse_conversation(
        requested_kind="companion_twin",
        existing_kind="companion_twin",
        conversation_id="heir_hr_abc",
    )
    assert not can_reuse_conversation(
        requested_kind="companion_twin",
        existing_kind=None,
        conversation_id="heir_hr_stolen",
    )


def test_sanitize_heir_patch_drops_release_fields():
    assert sanitize_heir_patch({
        "name": "Sam",
        "released": True,
        "released_at": "2026-01-01",
        "release_token": "hr_tok_old",
        "note": "keep",
    }) == {"name": "Sam", "note": "keep"}
    assert sanitize_heir_patch({"released": False}) == {}
    assert sanitize_heir_patch(None) == {}


def test_portal_router_uses_guarded_session_and_quiet_errors():
    src = (ROOT / "backend" / "routers" / "heir_portal.py").read_text(encoding="utf-8")
    assert "portal_conversation_id" in src
    assert "_persist_portal_turn" in src
    assert "kind not in (None, \"heir_portal\")" in src or 'kind not in (None, "heir_portal")' in src
    assert "Twin reply failed. Try again." in src
    assert "Twin reply failed: {exc" not in src
    assert 'f"heir_{heir' not in src or "portal_conversation_id" in src


def test_heirs_patch_uses_sanitize():
    src = (ROOT / "backend" / "routers" / "heirs.py").read_text(encoding="utf-8")
    assert "sanitize_heir_patch" in src
    assert "payload.model_dump()" in src


def test_companion_voice_stt_only_and_transcript_alias():
    src = (ROOT / "backend" / "routers" / "companion.py").read_text(encoding="utf-8")
    assert "stt_only: bool = Form(False)" in src
    assert 'audience: str = Form("owner")' in src
    assert "if stt_only or not owner_sitting:" in src
    assert '"transcript": spoken' in src
    assert "save_to_archive and owner_sitting" in src


def test_desktop_chat_ignores_pack_audience():
    src = (ROOT / "backend" / "routers" / "desktop.py").read_text(encoding="utf-8")
    assert "pack_audience" not in src
    assert 'audience = (body.audience or "owner")' in src
    assert "Capture stays with the owner" in src
    assert "can_reuse_conversation" in (ROOT / "backend" / "twin_runtime.py").read_text(
        encoding="utf-8"
    )


def test_vault_ingest_refuses_heir_audience():
    src = (ROOT / "backend" / "routers" / "vault.py").read_text(encoding="utf-8")
    assert "Memory ingest stays with the owner" in src
    assert "is_owner_audience(body.audience or \"owner\")" in src


def test_execute_tool_blocks_heir_writes():
    src = (ROOT / "backend" / "twin_tools.py").read_text(encoding="utf-8")
    assert "OWNER_ONLY_TOOLS" in src
    assert "heir_forbidden" in src
    assert "is_owner_audience" in src


def test_winui_ptt_sends_stt_only():
    root = ROOT / "desktop" / "Heirloom"
    assist = (root / "ViewModels" / "AssistantViewModel.cs").read_text(encoding="utf-8")
    twin = (root / "ViewModels" / "TwinViewModel.cs").read_text(encoding="utf-8")
    api = (root / "Services" / "HeirloomApiClient.cs").read_text(encoding="utf-8")
    assert '["stt_only"] = "true"' in assist
    assert '["stt_only"] = "true"' in twin
    assert '["audience"] = _host.CanEdit ? "owner" : "heir"' in assist
    assert '["audience"] = CanEdit ? "owner" : "heir"' in twin
    assert "IReadOnlyDictionary<string, string>? fields" in api


def test_auth_skips_owner_session_on_heir_portal():
    auth = (ROOT / "frontend" / "src" / "lib" / "auth.jsx").read_text(encoding="utf-8")
    assert 'pathname.startsWith("/heir/")' in auth
    assert "onHeirPortal" in auth
    assert "applyUser(null)" in auth
    app = (ROOT / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    assert 'path="/heir/:token"' in app
    assert "AuthProvider" in app
