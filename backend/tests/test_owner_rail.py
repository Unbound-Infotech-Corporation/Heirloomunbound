"""Owner rail Slice 1 — heuristics, heir fence, PC tools only on Assist."""
from __future__ import annotations

from pathlib import Path

import pytest

from owner_rail import (
    CHIP_AS_YOU,
    CHIP_BOTH,
    CHIP_DO,
    PC_TOOL_NAMES,
    classify_owner_turn,
    owner_mode_allowed,
    resolve_chat_mode,
)


def test_classify_ask_is_twin():
    for text in (
        "What did I love most about being a father?",
        "Tell me about growing up on the farm.",
        "Remind me to call my son Sunday.",
        "What do I believe about honesty?",
        "File this: the lake house was in Vermont.",
    ):
        d = classify_owner_turn(text)
        assert d.route == "twin", text
        assert d.chip == CHIP_AS_YOU
        assert d.twin and not d.assist


def test_classify_do_is_assist():
    for text in (
        "Open the browser and go to YouTube",
        "Launch Chrome",
        "See what's on my screen",
        "Set the volume to 20",
        "Find the file invoice.pdf",
        "Sleep the PC",
        "Run a command to list Desktop",
        "Type this into notepad",
    ):
        d = classify_owner_turn(text)
        assert d.route == "assist", text
        assert d.chip == CHIP_DO
        assert d.assist and not d.twin


def test_classify_mixed_is_both():
    for text in (
        "Remember the dentist Thursday and open my calendar",
        "What did I say about the printer and then open Chrome",
        "Remember to open the browser",
        "Remind me about dad's story and see my screen",
    ):
        d = classify_owner_turn(text)
        assert d.route == "both", text
        assert d.chip == CHIP_BOTH
        assert d.assist and d.twin


def test_classify_open_up_about_is_not_do():
    d = classify_owner_turn("Open up about dad and how you felt")
    assert d.route == "twin"
    assert not d.assist


def test_classify_empty_defaults_to_twin():
    d = classify_owner_turn("   ")
    assert d.route == "twin"
    assert d.chip == CHIP_AS_YOU


def test_classify_unclear_defaults_to_ask():
    d = classify_owner_turn("Thanks. That helps.")
    assert d.route == "twin"
    assert "default_ask" in d.reasons


def test_owner_mode_refused_for_heir_and_caller():
    assert owner_mode_allowed(audience="owner") is True
    assert owner_mode_allowed(audience="heir") is False
    assert owner_mode_allowed(audience="caller") is False
    assert owner_mode_allowed(audience="owner", heir_surface=True) is False
    assert resolve_chat_mode("owner", audience="owner") == "owner"
    assert resolve_chat_mode("owner", audience="heir") == "twin"
    assert resolve_chat_mode("owner", audience="caller") == "twin"
    assert resolve_chat_mode("owner", audience="owner", heir_surface=True) == "twin"
    assert resolve_chat_mode("bogus", audience="owner") == "twin"
    assert resolve_chat_mode("assistant", audience="owner") == "assistant"
    assert resolve_chat_mode(None) == "twin"


def test_heir_portal_never_accepts_owner_mode():
    path = Path(__file__).resolve().parents[1] / "routers" / "heir_portal.py"
    src = path.read_text(encoding="utf-8")
    assert "mode=owner" not in src
    assert "run_owner_turn" not in src
    assert "classify_owner_turn" not in src
    assert 'audience="heir"' in src
    assert "pc_control" not in src
    portal = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "HeirPortal.jsx"
    ).read_text(encoding="utf-8")
    assert "/owner" not in portal
    assert "/twin/chat" in portal


def test_owner_page_is_one_composer_with_chips():
    src = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "Owner.jsx"
    ).read_text(encoding="utf-8")
    assert "Do + As you" in src
    assert "no mode picker" in src
    assert 'data-testid="owner-input"' in src
    assert "/owner/chat" in src
    assert "mode picker" in src
    assert "select" not in src.lower() or "mode=" not in src
    assert "AssistReceipt" in src
    assert "owner-twin-leg" in src
    assert "owner-assist-leg" in src


def test_web_twin_route_stays_twin_only():
    path = Path(__file__).resolve().parents[1] / "routers" / "twin.py"
    src = path.read_text(encoding="utf-8")
    assert "run_owner_turn" not in src
    assert "tools_for_turn(" in src
    assert '"twin"' in src
    assert "PC_ABILITY_IDS" in src


def test_owner_leg_wrapper_uses_assist_role_only_for_do():
    src = (Path(__file__).resolve().parents[1] / "owner_rail.py").read_text(encoding="utf-8")
    assert 'role = "assistant" if leg == ROUTE_ASSIST else "twin"' in src
    assert "tools_for_turn(role, enabled_ids" in src


def test_desktop_router_calls_owner_rail():
    path = Path(__file__).resolve().parents[1] / "routers" / "desktop.py"
    src = path.read_text(encoding="utf-8")
    assert "resolve_chat_mode" in src
    assert "run_owner_turn" in src
    assert 'kind = "companion_owner"' in src
    assert "owner_response_fields" in src


def test_desktop_chat_req_accepts_owner_mode():
    pydantic = pytest.importorskip("pydantic")
    try:
        from routers.desktop import ChatReq
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"desktop ChatReq import needs app deps: {exc}")
    body = ChatReq.model_validate({"text": "open Chrome", "mode": "owner", "audience": "owner"})
    assert body.mode == "owner"
    assert resolve_chat_mode(body.mode, audience=body.audience) == "owner"
    heir = ChatReq.model_validate({"text": "open Chrome", "mode": "owner", "audience": "heir"})
    assert resolve_chat_mode(heir.mode, audience=heir.audience) == "twin"
    assert pydantic.__name__ == "pydantic"


def test_pc_tools_only_on_assist_leg():
    try:
        from owner_rail import tools_for_owner_leg
        from twin_runtime import PC_ABILITY_IDS, tools_for_turn
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"twin_runtime import needs app deps: {exc}")
    enabled = {"web", "pc_control", "screen_vision", "terminal", "smart_home"}
    twin = tools_for_owner_leg("twin", enabled)
    assist = tools_for_owner_leg("assist", enabled)
    assert PC_TOOL_NAMES.isdisjoint(twin)
    assert "open_on_pc" not in twin
    assert "see_screen" not in twin
    assert "run_command" not in twin
    assert "search_archive" in twin
    assert "open_on_pc" in assist
    assert "see_screen" in assist
    assert "run_command" in assist
    assert "save_memory" in assist
    assert tools_for_turn("twin", enabled) == twin
    assert tools_for_turn("assistant", enabled) == assist
    assert PC_ABILITY_IDS == {"pc_control", "screen_vision", "terminal"}
