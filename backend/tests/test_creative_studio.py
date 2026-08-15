"""Creative twin — local art / video / music catalog (no Mongo)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from services.creative_studio import (
    JOB_KINDS,
    MODELS,
    SECRET_KEYS,
    STUDIOS,
    confirm_preview,
    howto_text,
    job_payload,
    normalize_studio,
    public_catalog,
    recipe_for,
    reject_secrets,
)


def test_catalog_covers_art_video_music_and_studios():
    kinds = {m["kind"] for m in MODELS}
    assert kinds == {"art", "video", "music"}
    assert set(JOB_KINDS) == {"art", "video", "music", "open"}
    assert recipe_for("art")["id"] == "fooocus"
    assert recipe_for("video")["id"] == "wan-video"
    assert recipe_for("music")["id"] == "ace-step"
    assert "pinokio.co/item" in recipe_for("art")["pinokio_url"]
    studio_kinds = {s["kind"] for s in STUDIOS}
    assert studio_kinds == {"art", "video", "music"}
    ids = {s["id"] for s in STUDIOS}
    for needed in (
        "photoshop", "photopea", "capcut", "premiere", "davinci",
        "youtube_studio", "tiktok", "ableton", "flstudio", "logic",
        "garageband", "reaper", "bandlab",
    ):
        assert needed in ids, needed
    cat = public_catalog()
    assert "cannot click every" in cat["honest"].lower()
    assert "password" in cat["honest"].lower()


def test_studio_aliases_and_defaults():
    assert normalize_studio("", "art")["id"] == "photoshop"
    assert normalize_studio("", "video")["id"] == "capcut"
    assert normalize_studio("", "music")["id"] == "ableton"
    assert normalize_studio("Photoshop")["id"] == "photoshop"
    assert normalize_studio("adobe photoshop 2024")["id"] == "photoshop"
    assert normalize_studio("CapCut", "video")["id"] == "capcut"
    assert normalize_studio("premiere pro")["id"] == "premiere"
    assert normalize_studio("YouTube Studio")["id"] == "youtube_studio"
    assert normalize_studio("FL Studio")["id"] == "flstudio"
    assert normalize_studio("Logic Pro")["id"] == "logic"
    assert not normalize_studio("youtube_studio")["can_edit_timeline"]
    assert normalize_studio("capcut")["can_edit_timeline"]
    # Unknown name with a kind still picks the default studio.
    assert normalize_studio("not-a-real-daw", "music")["id"] == "ableton"
    assert normalize_studio("") is None


def test_confirm_and_howto_are_grandmother_honest():
    ps = normalize_studio("photoshop")
    preview = confirm_preview("art", "a red barn at dusk", ps["label"])
    assert "confirmed=true" in preview
    assert "red barn" in preview
    assert "password" in preview.lower()
    assert "cannot click every button" in preview.lower()
    howto = howto_text("art", ps, "a red barn")
    assert "prompt.txt" in howto
    assert "Firefly" in howto or "clipboard" in howto.lower()
    yt = normalize_studio("youtube")
    vprev = confirm_preview("video", "grandma's garden", yt["label"])
    assert "cannot edit" in vprev.lower() or "YouTube" in vprev
    vhow = howto_text("video", yt, "grandma's garden", source="clip.mp4")
    assert "cannot edit" in vhow.lower() or "timeline" in vhow.lower()
    daw = normalize_studio("ableton")
    mhow = howto_text("music", daw, "gentle piano")
    assert "ACE-Step" in mhow or "DAW" in mhow


def test_payload_has_no_secrets_and_rejects_password_fields():
    studio = normalize_studio("photoshop")
    payload = job_payload("art", "oil painting of a pear", studio, title="Pear")
    blob = str(payload).lower()
    assert "adobe_password" not in blob
    assert payload.get("password") is None
    assert "never need" in payload["howto"].lower() or "do not need" in payload["howto"].lower()
    assert payload["kind"] == "art"
    assert payload["pinokio_url"]
    assert payload["windows_globs"]
    assert "HOW_TO" in payload["howto"] or "prompt.txt" in payload["howto"]
    assert reject_secrets({"password": "secret"}) 
    assert "never need" in reject_secrets({"password": "x"}).lower()
    assert reject_secrets({"prompt": "a cat"}) is None
    assert "password" in SECRET_KEYS


def test_ability_and_tools_declare_creative():
    abilities = (ROOT / "abilities.py").read_text(encoding="utf-8")
    tools = (ROOT / "twin_tools.py").read_text(encoding="utf-8")
    companion = (ROOT / "routers" / "companion.py").read_text(encoding="utf-8")
    commands = (ROOT / "companion_desktop" / "heirloom" / "commands.py").read_text(encoding="utf-8")
    assert '"id": "creative"' in abilities
    assert "requires_companion" in abilities
    for name in ("create_artwork", "edit_video", "make_music", "open_studio"):
        assert name in abilities
        assert name in tools
        assert f'"{name}": exec_{name}' in tools
    assert "confirmed=true" in abilities
    assert "NEVER ask for a" in abilities and "password" in abilities
    assert 'COMPANION_SCRIPT_VERSION = "2026.08.15.8"' in companion
    assert "def run_creative_job" in companion
    assert 'kind == "creative_job"' in companion
    assert "studio_label" in companion
    assert "from .creative_local import run_creative_job" in commands
    router_src = (ROOT / "services" / "llm_router.py").read_text(encoding="utf-8")
    assert '"ollama"' not in router_src.split("PROVIDERS", 1)[1].split("TASKS", 1)[0]


def test_ui_copy_is_grandmother_simple():
    abilities_ui = (REPO / "frontend" / "src" / "pages" / "Abilities.jsx").read_text(encoding="utf-8")
    twin = (REPO / "frontend" / "src" / "pages" / "Twin.jsx").read_text(encoding="utf-8")
    avatar = (REPO / "frontend" / "src" / "pages" / "AvatarStudio.jsx").read_text(encoding="utf-8")
    setup = (REPO / "frontend" / "src" / "pages" / "SetupKeys.jsx").read_text(encoding="utf-8")
    companion = (REPO / "frontend" / "src" / "pages" / "Companion.jsx").read_text(encoding="utf-8")
    assert "palette: Palette" in abilities_ui
    assert 'create: "Create"' in abilities_ui
    assert "create_artwork" in twin
    assert "edit_video" in twin
    assert "make_music" in twin
    assert "open_studio" in twin
    assert "cannot click every button" in avatar.lower()
    assert "no Adobe or music-app password" in setup
    assert "creative_job: Palette" in companion


def test_creative_local_module_parses():
    path = ROOT / "companion_desktop" / "heirloom" / "creative_local.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "run_creative_job" in names
    assert "workspace" in names
