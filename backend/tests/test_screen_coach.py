"""Screen coaching — when the twin should look, and how (no Mongo)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.screen_coach import (
    LOOK_AT_SCREEN_PHRASE,
    VISION_SYSTEM,
    coach_question_for,
    format_screen_context,
    should_look_at_screen,
)


def test_button_phrase_triggers_a_look():
    assert should_look_at_screen(LOOK_AT_SCREEN_PHRASE)
    assert should_look_at_screen("what's on my screen?")
    assert should_look_at_screen("help me with this boss")
    assert should_look_at_screen("check my grammar")
    assert should_look_at_screen("what movie is this")
    assert should_look_at_screen("look at this")
    assert should_look_at_screen("read this error for me")


def test_pasted_essay_does_not_screenshot():
    pasted = "Please fix this. " + ("The cat sat on the mat. " * 40)
    assert len(pasted) > 500
    assert should_look_at_screen(pasted) is False
    assert should_look_at_screen("") is False
    assert should_look_at_screen("good morning") is False
    assert should_look_at_screen("what's on my plate today?") is False


def test_coach_question_specializes_games_grammar_movies():
    game = coach_question_for("help me with this game")
    assert "game" in game.lower()
    assert "spoil" in game.lower()
    writing = coach_question_for("check my grammar")
    assert "grammar" in writing.lower()
    movie = coach_question_for("what movie is this")
    assert "movie" in movie.lower() or "TV" in movie
    general = coach_question_for(LOOK_AT_SCREEN_PHRASE)
    assert "Identify" in general or "identify" in general.lower()


def test_format_screen_context_tells_model_not_to_look_twice():
    ok = format_screen_context("help", {"summary": "Looking at your screen: a pause menu", "ui": {"ok": True}})
    assert "Do not call see_screen again" in ok
    assert "pause menu" in ok
    bad = format_screen_context("help", {"summary": "no PC", "ui": {"ok": False}})
    assert "couldn't" in bad.lower()
    assert "Heirloom app" in bad


def test_vision_system_is_a_coach_not_a_tab_reader():
    assert "Games" in VISION_SYSTEM
    assert "grammar" in VISION_SYSTEM.lower()
    assert "Movies" in VISION_SYSTEM
    assert "deleted" not in VISION_SYSTEM.lower()  # deletion is a product rule, not vision copy


def test_ability_and_tool_copy_cover_games_grammar_movies():
    abilities = (ROOT / "abilities.py").read_text(encoding="utf-8")
    tools = (ROOT / "twin_tools.py").read_text(encoding="utf-8")
    assert "games, grammar, movies" in abilities.lower() or "game" in abilities.lower()
    assert "grammar" in abilities.lower()
    assert "see_screen" in abilities
    assert "VISION_SYSTEM" in tools
    assert "coach_question_for" in tools


def test_desktop_and_web_share_the_same_look_phrase():
    twin = (ROOT.parent / "frontend" / "src" / "pages" / "Twin.jsx").read_text(encoding="utf-8")
    mini = (ROOT.parent / "frontend" / "src" / "pages" / "TwinMini.jsx").read_text(encoding="utf-8")
    talk = (ROOT / "companion_desktop" / "heirloom" / "ui" / "talk_window.py").read_text(encoding="utf-8")
    conv = (ROOT / "companion_desktop" / "heirloom" / "ui" / "conversation.py").read_text(encoding="utf-8")
    desktop = (ROOT / "routers" / "desktop.py").read_text(encoding="utf-8")
    twin_py = (ROOT / "routers" / "twin.py").read_text(encoding="utf-8")
    for blob in (twin, mini, talk, conv):
        assert LOOK_AT_SCREEN_PHRASE in blob
    assert "complete_twin_turn" in desktop
    assert "complete_twin_turn" in twin_py
    assert "_maybe_screen_prelook" in twin_py
    assert 'data-testid="twin-look-at-screen"' in twin
    # Desktop UI cannot import backend services; phrase is inlined.
    assert "from services.screen_coach" not in talk
    assert "from services.screen_coach" not in conv
    assert "def _needs_screen_look" in conv


def test_screenshot_capture_prefers_primary_monitor():
    screen_py = (ROOT / "companion_desktop" / "heirloom" / "screen.py").read_text(encoding="utf-8")
    companion = (ROOT / "routers" / "companion.py").read_text(encoding="utf-8")
    assert "monitors[1]" in screen_py
    assert "mss" in screen_py
    assert "monitors[1]" in companion
    req = (ROOT / "companion_desktop" / "requirements.txt").read_text(encoding="utf-8")
    assert "Pillow" in req
    assert "mss" in req


def test_screen_helper_and_coach_compile():
    files = [
        ROOT / "services" / "screen_coach.py",
        ROOT / "companion_desktop" / "heirloom" / "screen.py",
        ROOT / "routers" / "twin.py",
        ROOT / "routers" / "desktop.py",
        ROOT / "twin_tools.py",
    ]
    errors = []
    for path in files:
        src = path.read_text(encoding="utf-8")
        try:
            compile(src, str(path), "exec")
            ast.parse(src)
        except SyntaxError as exc:
            errors.append(f"{path}: {exc}")
    assert not errors, "\n".join(errors)
