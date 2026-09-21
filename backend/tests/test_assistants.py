"""Phase 1 multi-assistant specialists under the twin."""
from pathlib import Path

from assistants import (
    DEFAULT_ASSISTANTS,
    chat_role_for_specialist,
    filter_tools_for_specialist,
    mention_from_text,
    resolve_specialist_turn,
    specialist_prompt_block,
    speak_as_for_tools,
)
from owner_rail import PC_TOOL_NAMES, ROUTE_ASSIST, ROUTE_TWIN

ROOT = Path(__file__).resolve().parents[2]


def _assistants():
    return [
        {
            "assistant_id": "ast_research",
            "slug": "research",
            "name": "Research",
            "enabled": True,
            "speak_as": "specialist",
            "tools_allowlist": ["web_search", "web_fetch", "get_weather"],
            "role": "Look things up.",
        },
        {
            "assistant_id": "ast_pc",
            "slug": "pc",
            "name": "PC",
            "enabled": True,
            "speak_as": "assist",
            "tools_allowlist": ["open_on_pc", "see_screen", "run_command"],
            "role": "Do work on this computer.",
        },
        {
            "assistant_id": "ast_off",
            "slug": "quiet",
            "name": "Quiet",
            "enabled": False,
            "speak_as": "specialist",
            "tools_allowlist": ["web_search"],
        },
    ]


def test_defaults_cover_specialists_not_a_second_twin():
    slugs = {a["slug"] for a in DEFAULT_ASSISTANTS}
    assert {"research", "archive", "letters", "pc"} <= slugs
    pc = next(a for a in DEFAULT_ASSISTANTS if a["slug"] == "pc")
    assert pc["speak_as"] == "assist"
    assert "open_on_pc" in pc["tools_allowlist"]


def test_mention_parse_and_pick():
    mention, rest = mention_from_text("@Research look up the weather in Austin")
    assert mention.lower() == "research"
    assert rest.startswith("look up")
    turn = resolve_specialist_turn("@Research look up the weather", _assistants())
    assert turn["assistant"]["slug"] == "research"
    assert turn["role"] == "twin"
    assert turn["route"] == ROUTE_TWIN
    assert "look up the weather" in turn["message"]


def test_picker_id_beats_no_mention():
    turn = resolve_specialist_turn("hello", _assistants(), assistant_id="ast_pc")
    assert turn["assistant"]["slug"] == "pc"
    assert turn["role"] == "assistant"
    assert turn["route"] == ROUTE_ASSIST


def test_disabled_assistant_is_ignored():
    turn = resolve_specialist_turn("@Quiet hi", _assistants())
    assert turn["assistant"] is None


def test_pc_tools_never_on_twin_specialist():
    research = _assistants()[0]
    twin_tools = {"web_search", "web_fetch", "get_weather", "search_archive"} | set(PC_TOOL_NAMES)
    filtered = filter_tools_for_specialist(twin_tools, research)
    assert "web_search" in filtered
    assert not (filtered & PC_TOOL_NAMES)
    pc = _assistants()[1]
    assist_tools = set(PC_TOOL_NAMES) | {"search_archive"}
    pc_filtered = filter_tools_for_specialist(assist_tools, pc)
    assert "open_on_pc" in pc_filtered
    assert "see_screen" in pc_filtered


def test_speak_as_pc_tools_force_assist():
    assert speak_as_for_tools(["web_search"]) == "specialist"
    assert speak_as_for_tools(["open_on_pc"]) == "assist"
    assert chat_role_for_specialist({"speak_as": "assist", "tools_allowlist": []}) == "assistant"


def test_specialist_prompt_never_first_person_as_owner():
    block = specialist_prompt_block(_assistants()[0], "C L")
    assert "C L" in block
    assert "not them" in block.lower() or "not their twin" in block.lower()
    assert "SPECIALIST THIS TURN: Research" in block


def test_heir_portal_does_not_link_rooms_or_assistants():
    portal = (ROOT / "frontend" / "src" / "pages" / "HeirPortal.jsx").read_text(encoding="utf-8")
    assert "/rooms" not in portal
    assert "/assistants" not in portal
    assert "AssistantPicker" not in portal
    src = (ROOT / "backend" / "routers" / "heir_portal.py").read_text(encoding="utf-8")
    assert "/rooms" not in src
    assert "twin_assistants" not in src
