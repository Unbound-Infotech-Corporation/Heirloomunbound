"""Compact twin talk window — source checks (no Mongo, no Qt)."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "companion_desktop"
COMPANION = ROOT / "routers" / "companion.py"


def test_companion_script_version_for_mini_talk():
    text = COMPANION.read_text(encoding="utf-8")
    assert 'COMPANION_SCRIPT_VERSION = "2026.08.15.8"' in text


def test_mini_talk_window_is_grandmother_simple_not_obs():
    text = (DESKTOP / "heirloom" / "ui" / "talk_window.py").read_text(encoding="utf-8")
    assert "Talk in a small window" not in text  # label lives on the opener
    assert "Just you and your twin" in text
    assert "Tell your twin what to do" in text
    assert "hold to speak" in text
    assert "Full window" in text
    assert 'setWindowTitle("Your twin")' in text
    assert "Heirloom Twin — Broadcast" not in text
    assert "WindowStaysOnTopHint" in text
    assert "Look at my screen" in text
    assert "Look at my screen and help me with whatever is on it." in text


def test_avatar_panel_keeps_obs_and_adds_talk_button():
    text = (DESKTOP / "heirloom" / "ui" / "avatar_panel.py").read_text(encoding="utf-8")
    assert 'QPushButton("Talk in a small window")' in text
    assert "Pop out for OBS" in text
    assert "attach_talk_window" in text
    assert "_BroadcastWindow" in text


def test_main_window_hides_full_app_for_mini_talk():
    text = (DESKTOP / "heirloom" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "def open_mini_talk" in text
    assert "self.hide()" in text
    assert "Talk in a small window" in text
    assert "restore_from_mini_talk" in text
    assert "MiniTalkWindow" in text


def test_conversation_exposes_send_text_for_mini_window():
    text = (DESKTOP / "heirloom" / "ui" / "conversation.py").read_text(encoding="utf-8")
    assert "def send_text" in text
    assert "messages_changed" in text
    assert "def recent_messages" in text
    tree = ast.parse(text)
    names = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    assert "ConversationPanel" in names
    methods = {
        n.name
        for cls in tree.body
        if isinstance(cls, ast.ClassDef) and cls.name == "ConversationPanel"
        for n in cls.body
        if isinstance(n, ast.FunctionDef)
    }
    assert "send_text" in methods
    assert "recent_messages" in methods


def test_settings_remember_mini_talk_geometry():
    text = (DESKTOP / "heirloom" / "config.py").read_text(encoding="utf-8")
    assert '"mini_talk_geometry"' in text


def test_web_mini_route_and_opener_exist():
    app = (ROOT.parent / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    twin = (ROOT.parent / "frontend" / "src" / "pages" / "Twin.jsx").read_text(encoding="utf-8")
    mini = (ROOT.parent / "frontend" / "src" / "pages" / "TwinMini.jsx").read_text(encoding="utf-8")
    assert 'path="/twin/mini"' in app
    assert "TwinMini" in app
    assert "Talk in a small window" in twin
    assert "openTwinMiniWindow" in twin
    assert "twin-mini-root" in mini
    assert "Just you and your twin" in mini
    assert "/twin/message" in mini


def test_mini_talk_python_compiles():
    files = [
        DESKTOP / "heirloom" / "ui" / "talk_window.py",
        DESKTOP / "heirloom" / "ui" / "avatar_panel.py",
        DESKTOP / "heirloom" / "ui" / "conversation.py",
        DESKTOP / "heirloom" / "ui" / "main_window.py",
        DESKTOP / "heirloom" / "config.py",
    ]
    errors = []
    for path in files:
        src = path.read_text(encoding="utf-8")
        try:
            compile(src, str(path), "exec")
        except SyntaxError as exc:
            errors.append(f"{path}: {exc}")
    assert not errors, "Syntax errors:\n" + "\n".join(errors)
