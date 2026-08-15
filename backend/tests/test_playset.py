"""Play desk — child's-toy daily surfaces (no Mongo, no Qt)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
FRONT = REPO / "frontend" / "src"
DESKTOP = ROOT / "companion_desktop"


def test_toy_css_is_scoped_to_playset_not_the_whole_app():
    css = (FRONT / "index.css").read_text(encoding="utf-8")
    assert "family=Fredoka" in css
    assert "--font-toy" in css
    for name in (
        ".toy-desk",
        ".toy-knob",
        ".toy-porthole",
        ".toy-light",
        ".toy-screw",
        ".toy-face-paint",
        "--toy-tomato",
        "--toy-sunflower",
    ):
        assert name in css
    # Archive / library type stays Cormorant — Fredoka is the toy overlay.
    assert 'Cormorant Garamond' in css
    assert ".toy-desk h1" in css


def test_today_leads_with_playset_knobs():
    today = (FRONT / "pages" / "Today.jsx").read_text(encoding="utf-8")
    assert 'data-testid="today-root"' in today
    assert 'data-testid="today-greeting"' in today
    assert 'testid="today-playset"' in today
    for knob in ("talk", "look", "mail", "safety", "make", "pc"):
        assert f'playset-knob-{knob}' in today
    assert "Press a button" in today
    assert "not another inbox" in today.lower()
    assert "Look at my screen and help me with whatever is on it." in today
    assert 'to="/safety"' in today
    assert 'to="/twin"' in today


def test_safety_page_is_a_toy_panel_not_a_password_form():
    safety = (FRONT / "pages" / "Safety.jsx").read_text(encoding="utf-8")
    assert 'data-testid="safety-root"' in safety
    assert "safety-look" in safety
    assert "safety-open" in safety
    assert "safety-scan" in safety
    assert "security_job" in safety
    assert "Should I ask Windows to look?" in safety
    assert "never ask for your windows password" in safety.lower()
    assert "never turn protection off" in safety.lower()
    assert "Open the Heirloom app on the home computer" in safety
    assert "Turn off" not in safety
    assert "disable realtime" not in safety.lower()
    assert "BitLocker" not in safety
    assert "queueJob(\"status\")" in safety
    assert "queueJob(\"open\")" in safety
    assert "queueJob(\"scan\")" in safety
    assert 'kind: "security_job"' in safety


def test_safety_route_and_nav():
    app = (FRONT / "App.js").read_text(encoding="utf-8")
    nav = (FRONT / "components" / "AppLayout.jsx").read_text(encoding="utf-8")
    assert 'path="/safety"' in app
    assert "Safety" in app
    assert 'to: "/safety"' in nav
    assert 'tid: "nav-safety"' in nav
    assert 'tid: "nav-today"' in nav
    assert "Play desk" in nav


def test_twin_keeps_required_strings_on_toy_knobs():
    twin = (FRONT / "pages" / "Twin.jsx").read_text(encoding="utf-8")
    mini = (FRONT / "pages" / "TwinMini.jsx").read_text(encoding="utf-8")
    assert "Talk in a small window" in twin
    assert "Look at my screen" in twin
    assert "Look at my screen and help me with whatever is on it." in twin
    assert "toy-knob" in twin
    assert "toy-porthole" in twin or "ToyPorthole" in twin
    assert "Just you and your twin" in mini
    assert "Tell your twin what to do" in mini
    assert "Look at my screen" in mini


def test_desktop_mini_talk_is_a_round_toy_and_keeps_strings():
    text = (DESKTOP / "heirloom" / "ui" / "talk_window.py").read_text(encoding="utf-8")
    assert "Talk in a small window" not in text
    assert "Just you and your twin" in text
    assert "Tell your twin what to do" in text
    assert "hold to speak" in text
    assert "Look at my screen" in text
    assert "Look at my screen and help me with whatever is on it." in text
    assert "setFixedSize(112, 112)" in text
    assert "border-radius: 56px" in text
    assert "QRegion.Ellipse" in text
    compile(text, str(DESKTOP / "heirloom" / "ui" / "talk_window.py"), "exec")


def test_playroom_theme_is_cream_wood_not_a_new_saas_skin():
    theme = (DESKTOP / "heirloom" / "ui" / "theme.py").read_text(encoding="utf-8")
    assert '"playroom"' in theme
    assert "Playroom" in theme
    assert "#f4e8c8" in theme
    assert "#e24a3a" in theme
    assert "amber_library" in theme
    compile(theme, str(DESKTOP / "heirloom" / "ui" / "theme.py"), "exec")


def test_ollama_still_out_of_cloud_providers():
    router_src = (ROOT / "services" / "llm_router.py").read_text(encoding="utf-8")
    assert '"ollama"' not in router_src.split("PROVIDERS", 1)[1].split("TASKS", 1)[0]


def test_companion_script_version_unchanged_for_ui_only_playset():
    companion = (ROOT / "routers" / "companion.py").read_text(encoding="utf-8")
    assert 'COMPANION_SCRIPT_VERSION = "2026.08.15.8"' in companion
