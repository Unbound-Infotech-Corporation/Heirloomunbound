"""Unit tests for twin_runtime helpers + desktop command hardening (no live HTTP)."""
from __future__ import annotations

import ast
from pathlib import Path

import abilities as ab
from twin_runtime import build_twin_system, history_turns, tools_for_turn
from twin_pack import TwinPack, TwinPassage, compile_twin_prompt, miss_reply
from phone_inbound import phone_system_addendum


def test_history_turns_caps():
    msgs = [{"role": "user", "content": f"u{i}"} for i in range(40)]
    out = history_turns(msgs, limit=10)
    assert len(out) == 10
    assert out[0]["content"] == "u30"
    assert out[-1]["content"] == "u39"


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


def test_tool_names_for_abilities():
    names = ab.tool_names_for_abilities({"web", "pc_control"})
    assert "search_archive" in names
    assert "save_memory" in names
    assert "web_search" in names
    assert "open_on_pc" in names
    assert "run_command" not in names  # terminal ability off


def test_twin_turn_strips_save_memory():
    names = tools_for_turn("twin", {"web"})
    assert "save_memory" not in names
    assert "search_archive" in names
    packed = tools_for_turn("twin", {"web"}, has_client_pack=True)
    assert "search_archive" not in packed


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
    addendum = phone_system_addendum("Sam")
    assert "speaking with Sam" in addendum
    assert "Never say you are an AI" in addendum


def test_heir_portal_uses_pack_not_18k_dump():
    path = Path(__file__).resolve().parents[1] / "routers" / "heir_portal.py"
    src = path.read_text(encoding="utf-8")
    assert "18000" not in src
    assert "compile_twin_prompt" in src
    assert "archive_passages" in src


def test_chat_req_accepts_twin_pack():
    from routers.desktop import ChatReq

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
    })
    assert body.twin_pack["passages"][0]["kind"] == "interview"
    assert body.grounded is True


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
