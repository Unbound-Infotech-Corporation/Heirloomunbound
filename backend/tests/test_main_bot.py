"""Main-bot routing spine — Twin decides, one Clone or Assist, heir fence."""
from __future__ import annotations

from pathlib import Path

from assistants import (
    ABILITY_IDS,
    PC_ABILITY_IDS,
    clean_abilities,
    clean_autonomy,
    filter_tools_for_specialist,
    public_assistant,
    specialist_prompt_block,
)
from main_bot import (
    HANDLER_ASSIST,
    HANDLER_CLONE,
    HANDLER_TWIN,
    HeuristicMainBotClassifier,
    LlmMainBotClassifier,
    compose_routed_reply,
    handoff_payload,
    leg_allows_pc_tools,
    parse_classifier_json,
    route_main_bot,
    stamp_persisted_turn,
    twin_self_voice_note,
)
from owner_rail import CHIP_AS_YOU, OwnerTurnResult, PC_TOOL_NAMES, owner_response_fields

ROOT = Path(__file__).resolve().parents[2]


def _clones():
    return [
        {
            "clone_id": "cln_research",
            "assistant_id": "cln_research",
            "slug": "research",
            "name": "Research",
            "enabled": True,
            "speak_as": "specialist",
            "role": "Look things up. Web, weather, and public pages — never invent biography.",
            "tools_allowlist": ["web_search", "web_fetch", "get_weather"],
            "abilities": ["web"],
            "autonomy": "ask",
        },
        {
            "clone_id": "cln_archive",
            "assistant_id": "cln_archive",
            "slug": "archive",
            "name": "Archive",
            "enabled": True,
            "speak_as": "specialist",
            "role": "Search what is already filed. Reminders. No PC control.",
            "tools_allowlist": ["search_archive", "set_reminder", "list_recent_memories"],
            "abilities": [],
            "autonomy": "ask",
        },
        {
            "clone_id": "cln_letters",
            "assistant_id": "cln_letters",
            "slug": "letters",
            "name": "Letters",
            "enabled": True,
            "speak_as": "specialist",
            "role": "Help draft and think about sealed letters. No PC tools. The twin stays the person.",
            "tools_allowlist": ["search_archive", "list_recent_memories"],
            "abilities": [],
            "autonomy": "ask",
        },
        {
            "clone_id": "cln_pc",
            "assistant_id": "cln_pc",
            "slug": "pc",
            "name": "PC",
            "enabled": True,
            "speak_as": "assist",
            "role": "Do work on this computer. This is Assist — never first-person as the owner.",
            "tools_allowlist": ["open_on_pc", "see_screen", "run_command"],
            "abilities": ["pc_control", "screen_vision", "terminal"],
            "autonomy": "ask",
        },
        {
            "clone_id": "cln_off",
            "assistant_id": "cln_off",
            "slug": "quiet",
            "name": "Quiet",
            "enabled": False,
            "speak_as": "specialist",
            "role": "Look things up. Web and weather.",
            "tools_allowlist": ["web_search"],
            "abilities": ["web"],
            "autonomy": "ask",
        },
    ]


class _Boom:
    def classify(self, text, clones):  # noqa: ANN001
        raise AssertionError(f"classifier should not run for {text!r}")


def test_explicit_mention_wins_over_pc_phrase():
    decision = route_main_bot(
        "@Research open Chrome and look around",
        _clones(),
        classifier=_Boom(),
    )
    assert decision.explicit
    assert decision.handler == HANDLER_CLONE
    assert decision.clone_name == "Research"
    assert decision.chip == "Clone: Research"
    assert decision.execution == "twin"
    assert decision.rail == "twin"
    assert not decision.message.startswith("@")
    assert "open Chrome" in decision.message
    assert decision.close_loop.startswith("I'll hand this to Research")
    assert not leg_allows_pc_tools(decision, "assist")
    assert not leg_allows_pc_tools(decision, "twin")


def test_explicit_clone_id_wins_over_pc_phrase():
    decision = route_main_bot(
        "Open the browser and go to YouTube",
        _clones(),
        clone_id="cln_letters",
        classifier=_Boom(),
    )
    assert decision.handler == HANDLER_CLONE
    assert decision.clone_id == "cln_letters"
    assert decision.clone_name == "Letters"
    assert decision.execution == "twin"


def test_role_and_ability_match_hands_off_to_research():
    decision = route_main_bot("look up the weather in Austin", _clones())
    assert decision.handler == HANDLER_CLONE
    assert decision.clone_name == "Research"
    assert decision.chip == "Clone: Research"
    assert "weather" in decision.reason.lower() or "Research" in decision.reason
    assert decision.execution == "twin"
    payload = handoff_payload(decision)
    assert payload["handler"] == "clone"
    assert payload["reason"]
    assert payload["close_loop"].startswith("I'll ")
    assert payload["chip"] == "Clone: Research"
    assert payload["clone_id"] == "cln_research"


def test_letters_role_match():
    decision = route_main_bot("help me draft a sealed letter for the grandchildren", _clones())
    assert decision.handler == HANDLER_CLONE
    assert decision.clone_name == "Letters"


def test_archive_name_and_role_match():
    decision = route_main_bot("Search the archive for the lake house story", _clones())
    assert decision.handler == HANDLER_CLONE
    assert decision.clone_name == "Archive"
    assert decision.chip == "Clone: Archive"


def test_pc_intent_is_assist_not_a_clone():
    decision = route_main_bot("Open the browser and go to YouTube", _clones())
    assert decision.handler == HANDLER_ASSIST
    assert decision.clone_id is None
    assert decision.chip == "Do"
    assert decision.execution == "assist"
    assert decision.rail == "assist"
    assert leg_allows_pc_tools(decision, "assist")
    assert not leg_allows_pc_tools(decision, "twin")
    assert decision.close_loop.startswith("I'll ")


def test_mixed_pc_and_vault_keeps_both_legs():
    decision = route_main_bot("Remember to open the browser", _clones())
    assert decision.handler == HANDLER_ASSIST
    assert decision.rail == "both"
    assert decision.execution == "both"
    assert decision.chip == "Do + As you"
    assert decision.clone_id is None
    assert leg_allows_pc_tools(decision, "assist")


def test_unclear_stays_with_the_twin():
    decision = route_main_bot("Thanks. That helps.", _clones())
    assert decision.handler == HANDLER_TWIN
    assert decision.chip == "Twin"
    assert decision.clone_id is None
    assert decision.execution == "twin"
    assert "clear match" in decision.reason.lower()
    reply = compose_routed_reply("Glad it helped.", decision)
    assert reply == "Glad it helped."
    assert decision.close_loop == "I'll answer this myself."


def test_personal_question_stays_with_the_twin():
    decision = route_main_bot("What did I love most about being a father?", _clones())
    assert decision.handler == HANDLER_TWIN
    assert decision.chip == "Twin"
    assert "mine" in decision.reason.lower()


def test_close_scores_stay_with_the_twin():
    clones = [
        {
            "clone_id": "cln_research",
            "slug": "research",
            "name": "Research",
            "enabled": True,
            "speak_as": "specialist",
            "role": "Look things up. Web, weather, and public pages.",
            "abilities": ["web"],
            "tools_allowlist": ["web_search"],
        },
        {
            "clone_id": "cln_lookup",
            "slug": "lookup",
            "name": "Lookup",
            "enabled": True,
            "speak_as": "specialist",
            "role": "Look things up online. Web and weather.",
            "abilities": ["web"],
            "tools_allowlist": ["web_search"],
        },
    ]
    decision = route_main_bot("look up the weather", clones)
    assert decision.handler == HANDLER_TWIN
    assert decision.clone_id is None


def test_heir_caller_and_surface_never_route():
    text = "Open Chrome @Research"
    for kwargs in (
        {"audience": "heir", "clone_id": "cln_pc"},
        {"audience": "caller", "clone_id": "cln_research"},
        {"audience": "owner", "heir_surface": True, "clone_id": "cln_pc"},
    ):
        decision = route_main_bot(text, _clones(), classifier=_Boom(), **kwargs)
        assert decision.fenced, kwargs
        assert decision.handler == HANDLER_TWIN
        assert decision.clone_id is None
        assert decision.execution == "twin"
        assert decision.rail == "twin"
        assert not leg_allows_pc_tools(decision, "assist")
        payload = handoff_payload(decision)
        assert payload["handler"] == "twin"
        assert "clone_id" not in payload


def test_disabled_and_unknown_clone_do_not_guess():
    off = route_main_bot("@Quiet look up the weather", _clones(), classifier=_Boom())
    assert off.handler == HANDLER_TWIN
    assert "off" in off.reason.lower()
    missing = route_main_bot("open chrome", _clones(), clone_id="cln_missing", classifier=_Boom())
    assert missing.handler == HANDLER_TWIN
    assert missing.execution == "twin"


def test_explicit_pc_clone_uses_the_assist_leg():
    decision = route_main_bot("@PC open notepad", _clones(), classifier=_Boom())
    assert decision.handler == HANDLER_CLONE
    assert decision.clone_name == "PC"
    assert decision.chip == "Clone: PC"
    assert decision.execution == "assist"
    assert leg_allows_pc_tools(decision, "assist")
    enabled = set(PC_TOOL_NAMES) | {"web_search", "search_archive"}
    pc = _clones()[3]
    filtered = filter_tools_for_specialist(enabled, pc)
    assert "open_on_pc" in filtered
    assert "see_screen" in filtered
    research = _clones()[0]
    twin_side = filter_tools_for_specialist(enabled, research)
    assert PC_TOOL_NAMES.isdisjoint(twin_side)
    assert "web_search" in twin_side


def test_pc_ability_does_not_open_the_whole_toolkit():
    clone = {
        "name": "Ops",
        "speak_as": "specialist",
        "abilities": ["pc_control"],
        "tools_allowlist": [],
    }
    enabled = set(PC_TOOL_NAMES) | {"web_search", "search_archive"}
    filtered = filter_tools_for_specialist(enabled, clone)
    assert "open_on_pc" in filtered
    assert "run_command" not in filtered
    assert "web_search" not in filtered
    twin_enabled = enabled - set(PC_TOOL_NAMES)
    assert PC_TOOL_NAMES.isdisjoint(filter_tools_for_specialist(twin_enabled, clone))


def test_clone_prompt_is_not_the_owner_and_twin_note_is_not_a_clone():
    block = specialist_prompt_block(_clones()[0], "C L")
    assert "Do not speak" in block
    assert "C L" in block
    note = twin_self_voice_note()
    assert "clone did not take this turn" in note.lower()
    assert "first person" in note.lower()
    assist = (ROOT / "backend" / "twin_runtime.py").read_text(encoding="utf-8")
    assert "Never speak in first person" in assist


def test_compose_appends_close_loop_for_clone_and_assist():
    clone = route_main_bot("look up the weather in Austin", _clones())
    text = compose_routed_reply("Austin is clear.", clone)
    assert text.startswith("Austin is clear.")
    assert "I'll hand this to Research." in text
    assist = route_main_bot("Set the volume to 20", _clones())
    assert assist.handler == HANDLER_ASSIST
    closed = compose_routed_reply("Volume is at 20.", assist)
    assert "I'll have Assist do that on this PC." in closed


def test_response_fields_and_persisted_turn_carry_the_receipt():
    decision = route_main_bot("look up the weather in Austin", _clones())
    payload = handoff_payload(decision)
    turn = {"role": "assistant", "content": "Austin is clear."}
    stamp_persisted_turn(turn, payload)
    assert turn["handoff"]["handler"] == "clone"
    assert turn["handoff"]["reason"]
    assert turn["handoff"]["close_loop"]
    assert turn["handoff_chip"] == "Clone: Research"
    result = OwnerTurnResult(
        reply="Austin is clear.\n\nI'll hand this to Research.",
        rail="twin",
        rail_chip=CHIP_AS_YOU,
        rail_legs=["twin"],
        handoff=payload,
        specialist_id="cln_research",
        specialist_name="Research",
    )
    fields = owner_response_fields(result)
    assert fields["handoff"]["handler"] == "clone"
    assert fields["handoff_chip"] == "Clone: Research"
    assert fields["clone_id"] == "cln_research"
    assert fields["rail_chip"] == CHIP_AS_YOU


def test_persist_pair_stamps_handoff():
    src = (ROOT / "backend" / "twin_runtime.py").read_text(encoding="utf-8")
    assert "stamp_persisted_turn" in src
    assert "handoff" in src
    owner = (ROOT / "backend" / "owner_rail.py").read_text(encoding="utf-8")
    assert "route_main_bot" in owner
    assert "handoff=handoff" in owner
    assert "extra_system=voice_note" in owner
    assert 'role="assistant"' in owner
    portal = (ROOT / "backend" / "routers" / "heir_portal.py").read_text(encoding="utf-8")
    assert "route_main_bot" not in portal
    assert "run_owner_turn" not in portal


def test_llm_classifier_is_optional_and_cannot_grant_assist():
    calls = []

    def complete(prompt):
        calls.append(prompt)
        return '{"handler":"clone","clone":"letters","reason":"Letters should draft this."}'

    decision = route_main_bot(
        "Thanks. That helps.",
        _clones(),
        classifier=LlmMainBotClassifier(complete=complete),
    )
    assert decision.handler == HANDLER_CLONE
    assert decision.clone_name == "Letters"
    assert calls and "Research" in calls[0]
    assert "Quiet" not in calls[0]

    def boom(_prompt):
        raise RuntimeError("down")

    fallback = route_main_bot(
        "Thanks. That helps.",
        _clones(),
        classifier=LlmMainBotClassifier(complete=boom),
    )
    assert fallback.handler == HANDLER_TWIN

    def sneak(_prompt):
        return '{"handler":"assist","clone":"pc","reason":"do it"}'

    refused = route_main_bot(
        "Thanks. That helps.",
        _clones(),
        classifier=LlmMainBotClassifier(complete=sneak),
    )
    assert refused.handler == HANDLER_TWIN
    assert refused.execution == "twin"

    pc = route_main_bot(
        "Open the browser and go to YouTube",
        _clones(),
        classifier=LlmMainBotClassifier(complete=complete),
    )
    assert pc.handler == HANDLER_ASSIST
    assert len(calls) == 1

    plain = HeuristicMainBotClassifier()
    assert plain.classify("Thanks. That helps.", _clones()).handler == HANDLER_TWIN
    assert parse_classifier_json("nope") is None
    assert LlmMainBotClassifier(complete=None).classify("Thanks.", _clones()).handler == HANDLER_TWIN


def test_clone_shape_defaults_are_nonbreaking():
    out = public_assistant({
        "assistant_id": "cln_old",
        "name": "Research",
        "tools_allowlist": ["web_search", "get_weather", "open_on_pc"],
    })
    assert out["abilities"] == ["web", "pc_control"]
    assert out["autonomy"] == "ask"
    assert out["role"] == ""
    assert clean_autonomy("act") == "act"
    assert clean_autonomy("later") == "ask"
    assert clean_abilities(["web", "not-real", "web_search", "run_command"]) == ["web", "terminal"]
    assert clean_abilities([]) == []
    assert set(ABILITY_IDS) >= {"web", "pc_control", "screen_vision", "terminal"}
    catalog = (ROOT / "backend" / "abilities.py").read_text(encoding="utf-8")
    for ability_id in ABILITY_IDS:
        assert f'"id": "{ability_id}"' in catalog
    assert PC_ABILITY_IDS <= set(ABILITY_IDS)


def test_owner_page_shows_handoff_chip():
    src = (ROOT / "frontend" / "src" / "pages" / "Owner.jsx").read_text(encoding="utf-8")
    assert "handoffChip" in src
    assert "Do + As you" in src
    assert 'data-testid="owner-input"' in src
    panel = (ROOT / "frontend" / "src" / "components" / "studio" / "AssistantsPanel.jsx").read_text(encoding="utf-8")
    assert "clone-role-" in panel
    assert "autonomy" in panel
    rail = (ROOT / "OWNER_RAIL.md").read_text(encoding="utf-8")
    assert "Main bot routing" in rail
    assert "not built" in rail
    assert "Clone-to-Clone" in rail
