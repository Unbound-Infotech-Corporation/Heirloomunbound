"""Unit tests for twin_runtime helpers + desktop command hardening (no live HTTP)."""
from __future__ import annotations

import ast
from pathlib import Path

import abilities as ab
from twin_runtime import build_twin_system, history_turns


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
    assert "web_search" in names
    assert "open_on_pc" in names
    assert "run_command" not in names  # terminal ability off


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
