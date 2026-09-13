"""Unit tests for twin_runtime helpers + desktop command hardening (no live HTTP)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from owner_pairing import (
    assist_pairing_block,
    normalize_pairing_prefs,
    twin_owner_pairing_block,
)
from twin_pack import TwinPack, TwinPassage, compile_twin_prompt, miss_reply

try:
    import abilities as ab
    from twin_runtime import (
        PC_ABILITY_IDS,
        build_assistant_system,
        build_twin_system,
        history_turns,
        tools_for_turn,
    )
    from phone_inbound import phone_system_addendum
    _HAS_TWIN_RUNTIME = True
except Exception as _twin_import_exc:  # noqa: BLE001
    _HAS_TWIN_RUNTIME = False
    _TWIN_IMPORT_ERR = _twin_import_exc

_needs_twin = pytest.mark.skipif(
    not _HAS_TWIN_RUNTIME,
    reason=f"twin_runtime import needs app deps: {_TWIN_IMPORT_ERR}" if not _HAS_TWIN_RUNTIME else "",
)


@_needs_twin
def test_history_turns_caps():
    msgs = [{"role": "user", "content": f"u{i}"} for i in range(40)]
    out = history_turns(msgs, limit=10)
    assert len(out) == 10
    assert out[0]["content"] == "u30"
    assert out[-1]["content"] == "u39"


@_needs_twin
def test_build_twin_system_includes_abilities_and_fence():
    system = build_twin_system(
        "Alex",
        "STABLE FACTS\n- Has a son",
        "[MEMORY] Home\nGrew up in Vermont",
        "- lights: turn on living room",
        safe_topics=["politics"],
        abilities_block="Extra abilities:\n- web_search",
    )
    assert "Alex" in system
    assert "SAFE-TOPIC FENCE" in system
    assert "politics" in system
    assert "web_search" in system
    assert "Grew up in Vermont" in system
    assert "HOW WE WORK (owner sitting)" in system
    assert "Assist can Do" in system


@_needs_twin
def test_build_twin_system_heir_skips_owner_pairing():
    system = build_twin_system(
        "Alex",
        "",
        "[MEMORY] Home\nGrew up in Vermont",
        "",
        audience="heir",
        pairing={"pairing_style": "proactive", "act_default": True},
    )
    assert "HOW WE WORK" not in system
    assert "Assist can Do" not in system
    assert "pairing or productivity" in system
    assert "Grew up in Vermont" in system


@_needs_twin
def test_build_assistant_system_encodes_teammate_defaults():
    system = build_assistant_system(
        "Alex",
        "",
        "",
        "",
        pairing={"pairing_style": "teammate", "act_default": True, "close_loop": True},
    )
    assert "Heirloom Assist" in system
    assert "HOW WE WORK (owner pairing)" in system
    assert "Pair like a teammate" in system
    assert "Act by default" in system
    assert "1–3 sentences" in system
    assert "Never speak in first person as Alex" in system
    assert "wait in-document" in system


def test_pairing_prefs_normalize_and_wait_style():
    prefs = normalize_pairing_prefs({"pairing_style": "WAIT", "act_default": "0"})
    assert prefs["pairing_style"] == "wait"
    assert prefs["act_default"] is False
    assert prefs["close_loop"] is True
    assist = assist_pairing_block(prefs)
    assert "Wait for a clear ask" in assist
    assert "Do not change the PC" in assist
    twin = twin_owner_pairing_block({"pairing_style": "bogus"})
    assert "Decide sensible defaults" in twin


@_needs_twin
def test_tool_names_for_abilities():
    names = ab.tool_names_for_abilities({"web", "pc_control"})
    assert "search_archive" in names
    assert "save_memory" in names
    assert "web_search" in names
    assert "open_on_pc" in names
    assert "run_command" not in names  # terminal ability off


@_needs_twin
def test_twin_turn_strips_save_memory():
    names = tools_for_turn("twin", {"web"})
    assert "save_memory" not in names
    assert "search_archive" in names
    packed = tools_for_turn("twin", {"web"}, has_client_pack=True)
    assert "search_archive" not in packed


@_needs_twin
def test_twin_turn_strips_pc_control_tools():
    names = tools_for_turn(
        "twin", {"web", "pc_control", "screen_vision", "terminal", "smart_home"},
    )
    assert "open_on_pc" not in names
    assert "see_screen" not in names
    assert "run_command" not in names
    assert "type_text" not in names
    assert "web_search" in names
    assert "search_archive" in names
    assert "run_skill" in names
    assist = tools_for_turn(
        "assistant", {"web", "pc_control", "screen_vision", "terminal"},
    )
    assert "open_on_pc" in assist
    assert "see_screen" in assist
    assert "run_command" in assist
    assert "save_memory" in assist
    assert PC_ABILITY_IDS == {"pc_control", "screen_vision", "terminal"}


@_needs_twin
def test_phone_turn_strips_pc_and_save_unless_owner():
    names = tools_for_turn("twin", {"web", "smart_home", "pc_control"}, source="phone")
    assert "save_memory" not in names
    assert "open_on_pc" not in names
    assert "run_skill" not in names
    assert "web_search" in names
    assert "search_archive" in names
    owner = tools_for_turn(
        "twin", {"web", "smart_home"}, source="phone", caller_is_owner=True,
    )
    assert "run_skill" in owner
    assist = tools_for_turn("assistant", {"web"})
    assert "save_memory" in assist
    leaked = tools_for_turn(
        "assistant",
        {"web", "pc_control", "screen_vision", "terminal"},
        audience="heir",
    )
    assert "open_on_pc" not in leaked
    assert "see_screen" not in leaked
    assert "run_command" not in leaked
    assert "save_memory" not in leaked
    caller = tools_for_turn("assistant", {"web", "pc_control"}, audience="caller")
    assert "open_on_pc" not in caller
    heir_writes = tools_for_turn(
        "twin", {"web", "smart_home", "music"}, audience="heir"
    )
    assert "set_reminder" not in heir_writes
    assert "save_memory" not in heir_writes
    assert "run_skill" not in heir_writes
    assert "search_archive" in heir_writes


def test_compile_twin_prompt_uses_passages_not_recency_dump():
    pack = TwinPack(
        passages=[TwinPassage(id="12", kind="interview", tag="childhood", text="Grew up in Vermont", score=4)],
        grounded=True,
        audience="heir",
    )
    system = compile_twin_prompt(pack, "Alex")
    assert "Vermont" in system
    assert "PASSAGES" in system
    assert "heir" in system.lower()
    assert "HOW WE WORK" not in system
    assert "Assist can Do" not in system
    assert miss_reply(True).startswith("I don't remember")
    spoken = miss_reply(True, spoken=True)
    assert "Nothing filed matches" not in spoken
    assert spoken.startswith("I don't remember")


def test_compile_twin_prompt_phone_caller_is_grounded():
    pack = TwinPack(
        passages=[TwinPassage(id="1", kind="interview", tag="home", text="The farm was in Vermont", score=3)],
        grounded=True,
        audience="caller",
    )
    system = compile_twin_prompt(pack, "Alex")
    assert "family caller" in system.lower()
    assert "Vermont" in system
    assert "PC actions" in system
    assert "HOW WE WORK" not in system
    assert "Assist can Do" not in system


@_needs_twin
def test_compile_twin_prompt_owner_includes_pairing():
    pack = TwinPack(
        passages=[TwinPassage(id="1", kind="interview", tag="home", text="The farm was in Vermont", score=3)],
        grounded=True,
        audience="owner",
    )
    system = compile_twin_prompt(pack, "Alex")
    assert "HOW WE WORK (owner sitting)" in system
    assert "Assist can Do" in system
    assert "Never invent PC actions" in system
    addendum = phone_system_addendum("Sam")
    assert "speaking with Sam" in addendum
    assert "Never say you are an AI" in addendum


def test_web_twin_uses_shared_builder_as_owner():
    path = Path(__file__).resolve().parents[1] / "routers" / "twin.py"
    src = path.read_text(encoding="utf-8")
    assert "from twin_runtime import PC_ABILITY_IDS, build_twin_system, tools_for_turn" in src
    assert 'audience="owner"' in src
    assert "def _build_twin_system" not in src
    assert "tools_for_turn(\"twin\", twin_ids)" in src
    assert "enabled_tool_names" not in src
    assert "PC_ABILITY_IDS" in src


def test_assist_planner_string_pairs_like_teammate():
    path = (
        Path(__file__).resolve().parents[2]
        / "desktop"
        / "Heirloom"
        / "ViewModels"
        / "AssistantViewModel.cs"
    )
    src = path.read_text(encoding="utf-8")
    assert "Pair like a teammate" in src
    assert "Close the loop in 1–3 sentences" in src
    assert "wait in-document" in src
    assert "Never speak in first person as the owner" in src


def test_heir_portal_uses_pack_not_18k_dump():
    path = Path(__file__).resolve().parents[1] / "routers" / "heir_portal.py"
    src = path.read_text(encoding="utf-8")
    assert "18000" not in src
    assert "compile_twin_prompt" in src
    assert "archive_passages" in src


def test_chat_req_accepts_twin_pack():
    try:
        from routers.desktop import ChatReq
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"desktop ChatReq import needs app deps: {exc}")

    body = ChatReq.model_validate({
        "text": "where did you grow up?",
        "mode": "twin",
        "grounded": True,
        "persona": "family",
        "twin_pack": {
            "passages": [{"id": "1", "kind": "interview", "text": "Vermont"}],
            "grounded": True,
            "audience": "owner",
        },
        "audience": "owner",
    })
    assert body.twin_pack["passages"][0]["kind"] == "interview"
    assert body.grounded is True
    assert body.audience == "owner"


def test_tools_for_turn_source_forces_twin_for_heir_audience():
    src = (Path(__file__).resolve().parents[1] / "twin_runtime.py").read_text(encoding="utf-8")
    assert "if audience is not None and not is_owner_audience(audience):" in src
    assert "if not is_owner_audience(audience_key):" in src or "owner_sitting = is_owner_audience" in src
    assert src.count('role = "twin"') >= 2
    assert "HEIR_FORBIDDEN_TOOLS" in src
    assert "phone or not owner_sitting" in src
    assert "if owner_sitting and ((not phone) or caller_is_owner):" in src
    assert "can_reuse_conversation" in src
    assert "audience=audience_key" in src


def test_winui_assist_fences_heir_mode():
    root = Path(__file__).resolve().parents[2] / "desktop" / "Heirloom"
    assist = (root / "ViewModels" / "AssistantViewModel.cs").read_text(encoding="utf-8")
    assert "if (!_host.CanEdit)" in assist
    assert 'mode = "assistant", audience' in assist or "mode = \"assistant\", audience" in assist
    assert 'var audience = _host.CanEdit ? "owner" : "heir"' in assist
    shell = (root / "ViewModels" / "StudioShellViewModel.cs").read_text(encoding="utf-8")
    assert 'id == "assistant" && !_host.CanEdit' in shell
    assert "Heir mode. Assist stays with the owner." in shell
    poller = (root / "Services" / "CommandPoller.cs").read_text(encoding="utf-8")
    assert 'or "set_volume" or "notify" or "system_status"' in poller
    toolkit = (root / "Services" / "PcToolkit.cs").read_text(encoding="utf-8")
    vol_idx = toolkit.index("public ToolResult SetVolume")
    status_idx = toolkit.index("public ToolResult SystemStatus")
    assert "if (!AllowPc)" in toolkit[vol_idx:vol_idx + 220]
    assert "if (!AllowPc)" in toolkit[status_idx:status_idx + 220]


def test_heir_portal_chat_forces_heir_audience():
    path = Path(__file__).resolve().parents[1] / "routers" / "heir_portal.py"
    src = path.read_text(encoding="utf-8")
    assert 'audience="heir"' in src
    assert "compile_twin_prompt" in src


def test_desktop_commands_has_speak_locally_and_say():
    path = (
        Path(__file__).resolve().parents[1]
        / "companion_desktop"
        / "heirloom"
        / "commands.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    assert "speak_locally" in names
    assert "CommandPoller" in names
    src = path.read_text(encoding="utf-8")
    assert 'kind == "say"' in src
    assert "speak_locally(payload.get(" in src
    assert "account inactive" in src  # poller surfaces 403 account_inactive


def test_desktop_requirements_include_pc_deps():
    req = (
        Path(__file__).resolve().parents[1]
        / "companion_desktop"
        / "requirements.txt"
    ).read_text(encoding="utf-8").lower()
    for dep in ("psutil", "mss", "pillow", "pyside6", "requests"):
        assert dep in req, f"missing {dep} in requirements.txt"


def test_config_handles_empty_bake():
    path = (
        Path(__file__).resolve().parents[1]
        / "companion_desktop"
        / "heirloom"
        / "config.py"
    )
    src = path.read_text(encoding="utf-8")
    assert "not BACKEND_URL" in src or "BACKEND_URL.startswith" in src
    assert 'HEIRLOOM_BACKEND_URL' in src
