"""Unbound Keyboard — local proofread, Android IME, Windows helper (no Mongo)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
FRONT = REPO / "frontend" / "src"
DESKTOP = ROOT / "companion_desktop"
ANDROID = REPO / "android" / "unbound-keyboard"

sys.path.insert(0, str(ROOT))

from services.writing_coach import (  # noqa: E402
    apply_suggestion,
    build_habit_profile,
    looks_secret,
    proofread_local,
)


def test_fixes_spelling_and_should_of():
    out = proofread_local("I recieve the note and should of said thanks.")
    assert out["secret"] is False
    assert "receive" in out["corrected"]
    assert "should have" in out["corrected"]
    kinds = {i["kind"] for i in out["issues"]}
    assert "spelling" in kinds
    assert "grammar" in kinds


def test_its_versus_it_is():
    out = proofread_local("its a quiet morning and it's own porch is sunny.")
    assert "it's a" in out["corrected"].lower()
    assert "its own" in out["corrected"].lower()


def test_repeated_word_and_youre():
    out = proofread_local("the the house is yours because youre home")
    assert out["corrected"].lower().startswith("the house")
    assert "you're" in out["corrected"].lower()


def test_filler_overuse_is_style_not_silent_rewrite():
    text = "I just just just really really really want to go."
    out = proofread_local(text)
    style = [i for i in out["issues"] if i["kind"] == "style"]
    assert style, out["issues"]
    # Style flags are chips, not auto-rewrites of the whole sentence.
    assert "just" in out["corrected"]


def test_habit_overuse_from_archive_profile():
    habits = build_habit_profile(
        ["good " * 20 + "morning to you. good day. good night. good work. " * 4],
        None,
    )
    words = {row["word"] for row in habits["overused"]}
    assert "good" in words
    out = proofread_local("It was a good good picnic.", habits)
    habit = [i for i in out["issues"] if i["kind"] == "habit"]
    assert habit
    assert habit[0]["suggestions"]


def test_secret_text_is_refused():
    card = "Please charge 4111 1111 1111 1111 today"
    assert looks_secret(card)
    out = proofread_local(card)
    assert out["secret"] is True
    assert out["issues"] == []
    assert "password" in out["style_note"].lower() or "private" in out["style_note"].lower()
    pin = "password: hunter2"
    assert looks_secret(pin)
    assert looks_secret("123-45-6789")
    assert not looks_secret("I'll see you at the porch tomorrow.")


def test_apply_suggestion_replaces_span():
    assert apply_suggestion("teh cat", 0, 3, "the") == "the cat"


def test_ability_and_tools_declare_unbound_keyboard():
    abilities = (ROOT / "abilities.py").read_text(encoding="utf-8")
    tools = (ROOT / "twin_tools.py").read_text(encoding="utf-8")
    assert '"id": "unbound_keyboard"' in abilities
    assert "Unbound Keyboard" in abilities
    assert "NEVER ask for a Google" in abilities
    assert "password boxes" in abilities.lower() or "password-box" in abilities.lower()
    for name in ("proofread_text", "polish_wording", "word_habits"):
        assert name in abilities
        assert name in tools
        assert f'"{name}": exec_{name}' in tools
    assert "requires_companion\": False" in abilities.split('"id": "unbound_keyboard"', 1)[1][:800]


def test_writing_api_never_stores_buffer_or_third_party_passwords():
    router = (ROOT / "routers" / "writing.py").read_text(encoding="utf-8")
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    assert 'prefix="/writing"' in router
    assert "proofread_for_user" in router
    assert "keyboard_tokens" in router
    assert "kb_" in router
    assert "writing.router" in server
    assert "Google" in router
    assert "password" in router.lower()
    # House key is ours — we still never collect third-party passwords.
    assert "NEVER ask" in (ROOT / "abilities.py").read_text(encoding="utf-8") or "never ask" in router.lower()


def test_android_ime_is_a_real_keyboard_and_skips_password_fields():
    manifest = (ANDROID / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    ime = (ANDROID / "app" / "src" / "main" / "java" / "com" / "unboundinfotech" / "keyboard" / "UnboundImeService.kt").read_text(encoding="utf-8")
    guard = (ANDROID / "app" / "src" / "main" / "java" / "com" / "unboundinfotech" / "keyboard" / "PasswordGuard.kt").read_text(encoding="utf-8")
    settings = (ANDROID / "app" / "src" / "main" / "java" / "com" / "unboundinfotech" / "keyboard" / "SettingsActivity.kt").read_text(encoding="utf-8")
    method = (ANDROID / "app" / "src" / "main" / "res" / "xml" / "method.xml").read_text(encoding="utf-8")
    readme = (ANDROID / "README.md").read_text(encoding="utf-8")
    assert "BIND_INPUT_METHOD" in manifest
    assert "android.view.InputMethod" in manifest
    assert "UnboundImeService" in manifest
    assert "InputMethodService" in ime
    assert "TYPE_TEXT_VARIATION_PASSWORD" in guard
    assert "TYPE_TEXT_VARIATION_WEB_PASSWORD" in guard
    assert "TYPE_NUMBER_VARIATION_PASSWORD" in guard
    assert "PasswordGuard.isSecretField" in ime
    assert "secretField" in ime
    assert "house_key" in settings
    assert "imeSubtypeMode" in method
    assert "Languages" in readme
    assert "password" in readme.lower()
    assert "house key" in readme.lower()


def test_windows_helper_is_not_a_keylogger():
    window = (DESKTOP / "heirloom" / "ui" / "writing_window.py").read_text(encoding="utf-8")
    main = (DESKTOP / "heirloom" / "ui" / "main_window.py").read_text(encoding="utf-8")
    commands = (DESKTOP / "heirloom" / "commands.py").read_text(encoding="utf-8")
    companion = (ROOT / "routers" / "companion.py").read_text(encoding="utf-8")
    assert "Unbound Keyboard" in window
    assert "not every key on the computer" in window
    assert "Never a password box" in window
    assert "Put this where I was typing" in window
    assert "Make it sound like me" in window
    assert "Check writing" in window
    assert "def open_writing_helper" in main
    assert "Ctrl+Shift+U" in main
    assert 'QAction("Unbound Keyboard"' in main
    assert "kind == \"writing_job\"" in commands
    assert "def run_writing_job" in commands
    assert "def run_writing_job" in companion
    assert 'kind == "writing_job"' in companion
    assert 'COMPANION_SCRIPT_VERSION = "2026.08.15.9"' in companion
    compile(window, str(DESKTOP / "heirloom" / "ui" / "writing_window.py"), "exec")


def test_web_and_phone_surfaces():
    app = (FRONT / "App.js").read_text(encoding="utf-8")
    writing = (FRONT / "pages" / "Writing.jsx").read_text(encoding="utf-8")
    mobile = (FRONT / "pages" / "mobile" / "MobileKeyboard.jsx").read_text(encoding="utf-8")
    shell = (FRONT / "pages" / "mobile" / "MobileShell.jsx").read_text(encoding="utf-8")
    nav = (FRONT / "components" / "AppLayout.jsx").read_text(encoding="utf-8")
    today = (FRONT / "pages" / "Today.jsx").read_text(encoding="utf-8")
    roadmap = (FRONT / "pages" / "Roadmap.jsx").read_text(encoding="utf-8")
    assert 'path="/writing"' in app
    assert 'path="keyboard"' in app
    assert 'data-testid="writing-root"' in writing
    assert "Copy my house key" in writing
    assert "password boxes" in writing.lower()
    assert 'data-testid="mobile-keyboard-root"' in mobile
    assert 'tid: "mobile-tab-keyboard"' in shell
    assert "grid-cols-6" in shell
    assert 'tid: "nav-writing"' in nav
    assert 'playset-knob-write' in today
    assert "Unbound Keyboard" in roadmap


def test_ollama_still_out_of_cloud_providers():
    router_src = (ROOT / "services" / "llm_router.py").read_text(encoding="utf-8")
    assert '"ollama"' not in router_src.split("PROVIDERS", 1)[1].split("TASKS", 1)[0]


def test_writing_coach_module_parses():
    path = ROOT / "services" / "writing_coach.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "proofread_local" in names
    assert "looks_secret" in names
    assert "build_habit_profile" in names
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
