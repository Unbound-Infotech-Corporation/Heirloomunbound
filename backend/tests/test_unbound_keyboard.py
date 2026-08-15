"""Unbound Keyboard — local proofread, Android IME, Windows helper (no Mongo)."""
from __future__ import annotations

import ast
import sys
import zipfile
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
from services.writing_local import format_house_blob, parse_house_blob, SPELLING  # noqa: E402


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
    assert "format_house_blob" in router
    assert "parse_house_blob" in router
    assert 'blob' in router
    assert "/house-key/revoke" in router
    assert "writing.router" in server
    assert "Google" in router
    assert "password" in router.lower()
    # House key is ours — we still never collect third-party passwords.
    assert "NEVER ask" in (ROOT / "abilities.py").read_text(encoding="utf-8") or "never ask" in router.lower()


def test_house_blob_roundtrip():
    blob = format_house_blob("https://example.com/app/", "kb_abc-DEF_123")
    assert blob.startswith("HOUSE\n")
    assert "https://example.com/app" in blob
    parsed = parse_house_blob(blob)
    assert parsed["token"] == "kb_abc-DEF_123"
    assert parsed["house_url"] == "https://example.com/app"
    mixed = parse_house_blob("please use https://house.example/  kb_zz99")
    assert mixed["token"] == "kb_zz99"
    assert mixed["house_url"] == "https://house.example"
    bare = parse_house_blob("kb_onlytoken")
    assert bare["token"] == "kb_onlytoken"


def test_android_ime_is_a_real_keyboard_and_skips_password_fields():
    kt = ANDROID / "app" / "src" / "main" / "java" / "com" / "unboundinfotech" / "keyboard"
    manifest = (ANDROID / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
    ime = (kt / "UnboundImeService.kt").read_text(encoding="utf-8")
    guard = (kt / "PasswordGuard.kt").read_text(encoding="utf-8")
    settings = (kt / "SettingsActivity.kt").read_text(encoding="utf-8")
    local = (kt / "LocalProofread.kt").read_text(encoding="utf-8")
    house = (kt / "HouseKey.kt").read_text(encoding="utf-8")
    qwerty = (ANDROID / "app" / "src" / "main" / "res" / "xml" / "qwerty.xml").read_text(encoding="utf-8")
    numbers = (ANDROID / "app" / "src" / "main" / "res" / "xml" / "numbers.xml").read_text(encoding="utf-8")
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
    assert "house_blob" in settings
    assert "HouseKey.parse" in settings
    assert "KEYCODE_MODE_CHANGE" in ime
    assert "KEYCODE_GLOBE = -10" in ime
    assert "LocalProofread.proofread" in ime
    assert "Fix spelling" in ime
    assert "Leave it" in ime
    assert 'android:codes="-2"' in qwerty
    assert 'android:codes="-10"' in qwerty
    assert 'android:codes="-2"' in numbers
    assert "imeSubtypeMode" in method
    assert "Languages" in readme
    assert "password" in readme.lower()
    assert "house key" in readme.lower()
    assert "assembleDebug" in readme
    assert "iPhone" in readme
    assert "kb_" in house
    for key in SPELLING:
        assert f'"{key}"' in local, key
    wrapper = ANDROID / "gradle" / "wrapper" / "gradle-wrapper.properties"
    assert wrapper.is_file()
    assert "distributionUrl" in wrapper.read_text(encoding="utf-8")


def test_windows_helper_is_not_a_keylogger():
    window = (DESKTOP / "heirloom" / "ui" / "writing_window.py").read_text(encoding="utf-8")
    main = (DESKTOP / "heirloom" / "ui" / "main_window.py").read_text(encoding="utf-8")
    commands = (DESKTOP / "heirloom" / "commands.py").read_text(encoding="utf-8")
    companion = (ROOT / "routers" / "companion.py").read_text(encoding="utf-8")
    boot = (DESKTOP / "heirloom" / "__main__.py").read_text(encoding="utf-8")
    assert "Unbound Keyboard" in window
    assert "not every key on the computer" in window
    assert "Never a password box" in window
    assert "Put this where I was typing" in window
    assert "Make it sound like me" in window
    assert "Check writing" in window
    assert "Fix spelling" in window
    assert "Leave it" in window
    assert "Sign in" in window
    assert "Send a sign-in note" in window
    assert "drag here" in window
    assert "Stay in front" in window
    assert "WRITING_QSS" in window
    assert 'setObjectName("chip")' in window
    assert "#3a2418" in window
    assert "#f0c040" in window
    assert "self.setStyleSheet(QSS)" not in window
    assert "from . import QSS" not in window
    assert "desktop-login" in (ROOT / "routers" / "auth.py").read_text(encoding="utf-8")
    assert "send_desktop_sign_in_email" in (ROOT / "email_service.py").read_text(encoding="utf-8")
    assert "persist_login" in (DESKTOP / "heirloom" / "config.py").read_text(encoding="utf-8")
    assert "proofread_local" in window
    assert "_house_is_paired" in window
    assert "def open_writing_helper" in main
    assert "Ctrl+Shift+U" in main
    assert 'QAction("Unbound Keyboard"' in main
    assert "kind == \"writing_job\"" in commands
    assert "def run_writing_job" in commands
    assert "def run_writing_job" in companion
    assert 'kind == "writing_job"' in companion
    assert 'COMPANION_SCRIPT_VERSION = "2026.08.15.9"' in companion
    assert "open_writing_helper" in boot
    assert "HEIRLOOM_TRY_KEYBOARD" in boot
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
    assert "Fix spelling" in writing
    assert "Leave it" in writing
    assert "Stop this phone key" in writing
    assert "data.blob" in writing
    assert "/house-key/revoke" in writing
    assert "password boxes" in writing.lower()
    assert 'data-testid="mobile-keyboard-root"' in mobile
    assert "Fix spelling" in mobile
    assert "Leave it" in mobile
    assert "data.blob" in mobile
    assert 'tid: "mobile-tab-keyboard"' in shell
    assert "grid-cols-6" in shell
    assert 'tid: "nav-writing"' in nav
    assert 'playset-knob-write' in today
    assert "Unbound Keyboard" in roadmap


def test_ollama_still_out_of_cloud_providers():
    router_src = (ROOT / "services" / "llm_router.py").read_text(encoding="utf-8")
    assert '"ollama"' not in router_src.split("PROVIDERS", 1)[1].split("TASKS", 1)[0]


def test_writing_coach_module_parses():
    local_path = ROOT / "services" / "writing_local.py"
    tree = ast.parse(local_path.read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "proofread_local" in names
    assert "looks_secret" in names
    assert "format_house_blob" in names
    assert "parse_house_blob" in names
    compile(local_path.read_text(encoding="utf-8"), str(local_path), "exec")
    coach = ROOT / "services" / "writing_coach.py"
    coach_tree = ast.parse(coach.read_text(encoding="utf-8"))
    coach_names = {
        n.name
        for n in coach_tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "build_habit_profile" in coach_names
    assert "polish_for_user" in coach_names
    compile(coach.read_text(encoding="utf-8"), str(coach), "exec")


def test_desktop_writing_brain_matches_cloud():
    cloud = (ROOT / "services" / "writing_local.py").read_bytes()
    desk = (DESKTOP / "heirloom" / "writing_local.py").read_bytes()
    assert cloud == desk
    start = (DESKTOP / "START HERE.txt").read_text(encoding="utf-8")
    try_bat = (DESKTOP / "Try-Unbound-Keyboard.bat").read_text(encoding="utf-8", errors="replace")
    assert "Try-Unbound-Keyboard.bat" in start
    assert "I recieve this" in start
    assert "Fix spelling" in start
    assert "Sign in" in start
    assert "iPhone" in start or "IPHONE" in start
    assert "password" in start.lower()
    assert "HEIRLOOM_TRY_KEYBOARD" in try_bat
    assert "Heirloom.bat" in try_bat


def test_try_it_zip_is_double_click_installable():
    sys.path.insert(0, str(ROOT))
    from pack_try_it_zip import build_try_it_zip

    dest = ROOT.parent / "tmp-Heirloom-Unbound-Keyboard-test.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    build_try_it_zip(dest)
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        start = zf.read("Heirloom-Unbound-Keyboard/START HERE.txt").decode("utf-8")
    assert "Heirloom-Unbound-Keyboard/Windows/Heirloom.bat" in names
    assert "Heirloom-Unbound-Keyboard/Windows/Try-Unbound-Keyboard.bat" in names
    assert "Heirloom-Unbound-Keyboard/Windows/run.sh" in names
    assert "Heirloom-Unbound-Keyboard/Windows/heirloom/writing_local.py" in names
    assert "Heirloom-Unbound-Keyboard/Windows/heirloom/ui/writing_window.py" in names
    assert "Heirloom-Unbound-Keyboard/Windows/START HERE.txt" in names
    assert any(n.endswith("AndroidManifest.xml") for n in names)
    assert any(n.endswith("UnboundImeService.kt") for n in names)
    assert any(n.endswith("LocalProofread.kt") for n in names)
    assert any(n.endswith("numbers.xml") for n in names)
    assert any(n.endswith("gradle-wrapper.properties") for n in names)
    debug_apk = ANDROID / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if debug_apk.is_file():
        assert "Heirloom-Unbound-Keyboard/Android/UnboundKeyboard.apk" in names
    assert "BIND_INPUT_METHOD" in zipfile.ZipFile(dest).read(
        next(n for n in names if n.endswith("AndroidManifest.xml"))
    ).decode("utf-8")
    assert "Try-Unbound-Keyboard.bat" in start
    dest.unlink(missing_ok=True)


def test_windows_zip_has_the_bat_right_there():
    sys.path.insert(0, str(ROOT))
    from pack_try_it_zip import build_windows_zip

    dest = ROOT.parent / "tmp-Unbound-Keyboard-for-Windows-test.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    build_windows_zip(dest)
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
    assert "Unbound-Keyboard-for-Windows/Try-Unbound-Keyboard.bat" in names
    assert "Unbound-Keyboard-for-Windows/Heirloom.bat" in names
    assert "Unbound-Keyboard-for-Windows/START HERE.txt" in names
    assert "Unbound-Keyboard-for-Windows/heirloom/ui/writing_window.py" in names
    assert not any("/Windows/Try-Unbound-Keyboard.bat" in n for n in names)
    dest.unlink(missing_ok=True)
