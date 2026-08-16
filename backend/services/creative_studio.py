"""Creative twin — local art, short video, and music sketches.

Catalog only — no database. The cloud cannot paint, cut, or compose; the home
PC does, via Pinokio / ComfyUI, then we open the studio the owner already has.

Honest scope
------------
We cannot puppet Photoshop, Premiere, CapCut, Ableton, FL Studio, or Logic the
way a person does. We do not collect Adobe or DAW passwords.

What *is* real today:

* **Art** — describe a picture. Fooocus / Flux (ComfyUI) sketches it locally.
  Then we open Photoshop, Affinity, GIMP, Krita, or Photopea so they can finish.
* **Video** — a short clip via WAN in ComfyUI (not a full movie, not realtime).
  Then we open CapCut, Premiere, DaVinci, or similar. Opening YouTube Studio or
  TikTok is a website — we cannot edit those timelines.
* **Music** — ACE-Step sketches a short song locally. Then we open Ableton,
  FL Studio, Logic, GarageBand, Reaper, or BandLab.

Pinokio and ComfyUI do not need an account.
"""
from __future__ import annotations

from typing import Any, Optional

_PINOKIO_ITEM = "https://pinokio.co/item?uri="

PINOKIO_COMFY = f"{_PINOKIO_ITEM}https://github.com/pinokiofactory/comfy"
PINOKIO_FOOOCUS = f"{_PINOKIO_ITEM}https://github.com/pinokiofactory/fooocus"
PINOKIO_ACE = f"{_PINOKIO_ITEM}https://github.com/ace-step/ACE-Step"

JOB_KINDS: tuple[str, ...] = ("art", "video", "music", "open")

SECRET_KEYS = frozenset({
    "password",
    "passwd",
    "secret",
    "adobe_password",
    "app_password",
    "api_key",
    "creative_cloud",
})

MODELS: list[dict[str, Any]] = [
    {
        "id": "fooocus",
        "kind": "art",
        "label": "Fooocus (pictures)",
        "blurb": "Describe a picture. It sketches it on your computer. Paste the same words into Photoshop Firefly if you have it.",
        "vram_gb": 8,
        "pinokio_url": PINOKIO_FOOOCUS,
        "github": "https://github.com/lllyasviel/Fooocus",
        "host": "fooocus",
    },
    {
        "id": "flux-comfy",
        "kind": "art",
        "label": "Flux in ComfyUI",
        "blurb": "Same idea, inside the ComfyUI workbench you may already have from Avatar Studio.",
        "vram_gb": 8,
        "pinokio_url": PINOKIO_COMFY,
        "github": "https://github.com/comfyanonymous/ComfyUI",
        "host": "comfy",
    },
    {
        "id": "wan-video",
        "kind": "video",
        "label": "WAN short clips",
        "blurb": "A short clip from a description or a still. Not realtime. Not a full movie edit.",
        "vram_gb": 12,
        "pinokio_url": PINOKIO_COMFY,
        "github": "https://github.com/kijai/ComfyUI-WanVideoWrapper",
        "host": "comfy",
    },
    {
        "id": "ace-step",
        "kind": "music",
        "label": "ACE-Step (music sketch)",
        "blurb": "A short song from a description. Open it in your DAW to arrange and mix.",
        "vram_gb": 8,
        "pinokio_url": PINOKIO_ACE,
        "github": "https://github.com/ace-step/ACE-Step",
        "host": "ace-step",
    },
]

# Fallback websites when the native app is not installed.
_PHOTOPEA = "https://www.photopea.com"
_CAPCUT_WEB = "https://www.capcut.com/editor"
_BANDLAB = "https://www.bandlab.com"

STUDIOS: list[dict[str, Any]] = [
    # --- art ---
    {
        "id": "photoshop",
        "label": "Photoshop",
        "kind": "art",
        "aliases": ("photoshop", "ps", "adobe photoshop", "creative cloud"),
        "app_names": ("Adobe Photoshop 2026", "Adobe Photoshop 2025", "Adobe Photoshop 2024", "Adobe Photoshop 2023", "Adobe Photoshop", "Photoshop"),
        "windows_globs": (
            r"%ProgramFiles%\Adobe\Adobe Photoshop 20*\Photoshop.exe",
            r"%ProgramFiles(x86)%\Adobe\Adobe Photoshop 20*\Photoshop.exe",
        ),
        "darwin_apps": ("Adobe Photoshop 2026", "Adobe Photoshop 2025", "Adobe Photoshop 2024", "Adobe Photoshop 2023", "Adobe Photoshop"),
        "linux_bins": (),
        "fallback_url": _PHOTOPEA,
        "can_edit_timeline": True,
    },
    {
        "id": "affinity",
        "label": "Affinity Photo",
        "kind": "art",
        "aliases": ("affinity", "affinity photo"),
        "app_names": ("Affinity Photo 2", "Affinity Photo"),
        "windows_globs": (r"%ProgramFiles%\Affinity\Photo 2\Photo.exe",),
        "darwin_apps": ("Affinity Photo 2", "Affinity Photo"),
        "linux_bins": (),
        "fallback_url": _PHOTOPEA,
        "can_edit_timeline": True,
    },
    {
        "id": "gimp",
        "label": "GIMP",
        "kind": "art",
        "aliases": ("gimp",),
        "app_names": ("GIMP", "gimp"),
        "windows_globs": (r"%ProgramFiles%\GIMP 2\bin\gimp-2.*.exe",),
        "darwin_apps": ("GIMP",),
        "linux_bins": ("gimp",),
        "fallback_url": _PHOTOPEA,
        "can_edit_timeline": True,
    },
    {
        "id": "krita",
        "label": "Krita",
        "kind": "art",
        "aliases": ("krita",),
        "app_names": ("Krita", "krita"),
        "windows_globs": (r"%ProgramFiles%\Krita (x64)\bin\krita.exe",),
        "darwin_apps": ("Krita",),
        "linux_bins": ("krita",),
        "fallback_url": _PHOTOPEA,
        "can_edit_timeline": True,
    },
    {
        "id": "paintnet",
        "label": "Paint.NET",
        "kind": "art",
        "aliases": ("paint.net", "paintnet", "paint net"),
        "app_names": ("PaintDotNet", "paintdotnet"),
        "windows_globs": (r"%ProgramFiles%\paint.net\PaintDotNet.exe",),
        "darwin_apps": (),
        "linux_bins": (),
        "fallback_url": _PHOTOPEA,
        "can_edit_timeline": True,
    },
    {
        "id": "photopea",
        "label": "Photopea",
        "kind": "art",
        "aliases": ("photopea",),
        "app_names": (),
        "windows_globs": (),
        "darwin_apps": (),
        "linux_bins": (),
        "url": _PHOTOPEA,
        "fallback_url": _PHOTOPEA,
        "can_edit_timeline": True,
    },
    # --- video ---
    {
        "id": "capcut",
        "label": "CapCut",
        "kind": "video",
        "aliases": ("capcut", "cap cut"),
        "app_names": ("CapCut",),
        "windows_globs": (
            r"%LOCALAPPDATA%\CapCut\Apps\*\CapCut.exe",
            r"%LOCALAPPDATA%\CapCut\CapCut.exe",
        ),
        "darwin_apps": ("CapCut",),
        "linux_bins": (),
        "fallback_url": _CAPCUT_WEB,
        "can_edit_timeline": True,
    },
    {
        "id": "premiere",
        "label": "Premiere Pro",
        "kind": "video",
        "aliases": ("premiere", "premiere pro", "adobe premiere"),
        "app_names": ("Adobe Premiere Pro 2026", "Adobe Premiere Pro 2025", "Adobe Premiere Pro 2024", "Adobe Premiere Pro"),
        "windows_globs": (r"%ProgramFiles%\Adobe\Adobe Premiere Pro 20*\Adobe Premiere Pro.exe",),
        "darwin_apps": ("Adobe Premiere Pro 2026", "Adobe Premiere Pro 2025", "Adobe Premiere Pro 2024", "Adobe Premiere Pro"),
        "linux_bins": (),
        "fallback_url": _CAPCUT_WEB,
        "can_edit_timeline": True,
    },
    {
        "id": "davinci",
        "label": "DaVinci Resolve",
        "kind": "video",
        "aliases": ("davinci", "resolve", "davinci resolve"),
        "app_names": ("DaVinci Resolve",),
        "windows_globs": (r"%ProgramFiles%\Blackmagic Design\DaVinci Resolve\Resolve.exe",),
        "darwin_apps": ("DaVinci Resolve",),
        "linux_bins": ("davinci-resolve", "resolve"),
        "fallback_url": _CAPCUT_WEB,
        "can_edit_timeline": True,
    },
    {
        "id": "aftereffects",
        "label": "After Effects",
        "kind": "video",
        "aliases": ("after effects", "ae", "aftereffects"),
        "app_names": ("Adobe After Effects 2026", "Adobe After Effects 2025", "Adobe After Effects 2024", "Adobe After Effects"),
        "windows_globs": (r"%ProgramFiles%\Adobe\Adobe After Effects 20*\Support Files\AfterFX.exe",),
        "darwin_apps": ("Adobe After Effects 2026", "Adobe After Effects 2025", "Adobe After Effects 2024"),
        "linux_bins": (),
        "fallback_url": _CAPCUT_WEB,
        "can_edit_timeline": True,
    },
    {
        "id": "finalcut",
        "label": "Final Cut Pro",
        "kind": "video",
        "aliases": ("final cut", "final cut pro", "fcp"),
        "app_names": ("Final Cut Pro",),
        "windows_globs": (),
        "darwin_apps": ("Final Cut Pro",),
        "linux_bins": (),
        "fallback_url": _CAPCUT_WEB,
        "can_edit_timeline": True,
    },
    {
        "id": "imovie",
        "label": "iMovie",
        "kind": "video",
        "aliases": ("imovie",),
        "app_names": ("iMovie",),
        "windows_globs": (),
        "darwin_apps": ("iMovie",),
        "linux_bins": (),
        "fallback_url": _CAPCUT_WEB,
        "can_edit_timeline": True,
    },
    {
        "id": "kdenlive",
        "label": "Kdenlive",
        "kind": "video",
        "aliases": ("kdenlive",),
        "app_names": ("kdenlive",),
        "windows_globs": (),
        "darwin_apps": ("Kdenlive",),
        "linux_bins": ("kdenlive",),
        "fallback_url": _CAPCUT_WEB,
        "can_edit_timeline": True,
    },
    {
        "id": "shotcut",
        "label": "Shotcut",
        "kind": "video",
        "aliases": ("shotcut",),
        "app_names": ("Shotcut", "shotcut"),
        "windows_globs": (r"%ProgramFiles%\Shotcut\shotcut.exe",),
        "darwin_apps": ("Shotcut",),
        "linux_bins": ("shotcut",),
        "fallback_url": _CAPCUT_WEB,
        "can_edit_timeline": True,
    },
    {
        "id": "vegas",
        "label": "VEGAS Pro",
        "kind": "video",
        "aliases": ("vegas", "vegas pro"),
        "app_names": ("VEGAS Pro",),
        "windows_globs": (r"%ProgramFiles%\VEGAS\VEGAS Pro *\vegas*.exe",),
        "darwin_apps": (),
        "linux_bins": (),
        "fallback_url": _CAPCUT_WEB,
        "can_edit_timeline": True,
    },
    {
        "id": "youtube_studio",
        "label": "YouTube Studio",
        "kind": "video",
        "aliases": ("youtube", "youtube studio", "yt studio"),
        "app_names": (),
        "windows_globs": (),
        "darwin_apps": (),
        "linux_bins": (),
        "url": "https://studio.youtube.com",
        "fallback_url": "https://studio.youtube.com",
        "can_edit_timeline": False,
        "honest": "I can open YouTube Studio. I cannot edit a video on YouTube's page.",
    },
    {
        "id": "tiktok",
        "label": "TikTok",
        "kind": "video",
        "aliases": ("tiktok", "tik tok"),
        "app_names": (),
        "windows_globs": (),
        "darwin_apps": (),
        "linux_bins": (),
        "url": "https://www.tiktok.com/studio",
        "fallback_url": "https://www.tiktok.com/studio",
        "can_edit_timeline": False,
        "honest": "I can open TikTok. I cannot edit a clip on TikTok's page.",
    },
    # --- music ---
    {
        "id": "ableton",
        "label": "Ableton Live",
        "kind": "music",
        "aliases": ("ableton", "ableton live"),
        "app_names": ("Ableton Live 12 Suite", "Ableton Live 12", "Ableton Live 11", "Ableton Live"),
        "windows_globs": (r"%ProgramFiles%\Ableton\Live *\Program\Ableton Live *.exe",),
        "darwin_apps": ("Ableton Live 12 Suite", "Ableton Live 12", "Ableton Live 11", "Ableton Live"),
        "linux_bins": (),
        "fallback_url": _BANDLAB,
        "can_edit_timeline": True,
    },
    {
        "id": "flstudio",
        "label": "FL Studio",
        "kind": "music",
        "aliases": ("fl studio", "flstudio", "fruity loops"),
        "app_names": ("FL Studio 2024", "FL Studio 21", "FL Studio", "FL64"),
        "windows_globs": (
            r"%ProgramFiles%\Image-Line\FL Studio *\FL64.exe",
            r"%ProgramFiles%\Image-Line\FL Studio\FL64.exe",
        ),
        "darwin_apps": ("FL Studio",),
        "linux_bins": (),
        "fallback_url": _BANDLAB,
        "can_edit_timeline": True,
    },
    {
        "id": "logic",
        "label": "Logic Pro",
        "kind": "music",
        "aliases": ("logic", "logic pro", "logic pro x"),
        "app_names": ("Logic Pro",),
        "windows_globs": (),
        "darwin_apps": ("Logic Pro", "Logic Pro X"),
        "linux_bins": (),
        "fallback_url": _BANDLAB,
        "can_edit_timeline": True,
    },
    {
        "id": "garageband",
        "label": "GarageBand",
        "kind": "music",
        "aliases": ("garageband", "garage band"),
        "app_names": ("GarageBand",),
        "windows_globs": (),
        "darwin_apps": ("GarageBand",),
        "linux_bins": (),
        "fallback_url": _BANDLAB,
        "can_edit_timeline": True,
    },
    {
        "id": "reaper",
        "label": "REAPER",
        "kind": "music",
        "aliases": ("reaper",),
        "app_names": ("REAPER", "reaper"),
        "windows_globs": (r"%ProgramFiles%\REAPER (x64)\reaper.exe", r"%ProgramFiles%\REAPER\reaper.exe"),
        "darwin_apps": ("REAPER",),
        "linux_bins": ("reaper",),
        "fallback_url": _BANDLAB,
        "can_edit_timeline": True,
    },
    {
        "id": "cubase",
        "label": "Cubase",
        "kind": "music",
        "aliases": ("cubase",),
        "app_names": ("Cubase 14", "Cubase 13", "Cubase"),
        "windows_globs": (r"%ProgramFiles%\Steinberg\Cubase *\Cubase.exe",),
        "darwin_apps": ("Cubase 14", "Cubase 13", "Cubase"),
        "linux_bins": (),
        "fallback_url": _BANDLAB,
        "can_edit_timeline": True,
    },
    {
        "id": "protools",
        "label": "Pro Tools",
        "kind": "music",
        "aliases": ("pro tools", "protools"),
        "app_names": ("Pro Tools",),
        "windows_globs": (r"%ProgramFiles%\Avid\Pro Tools\ProTools.exe",),
        "darwin_apps": ("Pro Tools",),
        "linux_bins": (),
        "fallback_url": _BANDLAB,
        "can_edit_timeline": True,
    },
    {
        "id": "cakewalk",
        "label": "Cakewalk",
        "kind": "music",
        "aliases": ("cakewalk", "bandlab cakewalk"),
        "app_names": ("Cakewalk",),
        "windows_globs": (r"%ProgramFiles%\Cakewalk\Cakewalk Core\Cakewalk.exe",),
        "darwin_apps": (),
        "linux_bins": (),
        "fallback_url": _BANDLAB,
        "can_edit_timeline": True,
    },
    {
        "id": "bandlab",
        "label": "BandLab",
        "kind": "music",
        "aliases": ("bandlab",),
        "app_names": (),
        "windows_globs": (),
        "darwin_apps": (),
        "linux_bins": (),
        "url": _BANDLAB,
        "fallback_url": _BANDLAB,
        "can_edit_timeline": True,
    },
]

STUDIO_BY_ID: dict[str, dict[str, Any]] = {s["id"]: s for s in STUDIOS}

_DEFAULT_STUDIO = {"art": "photoshop", "video": "capcut", "music": "ableton"}

_KIND_NOUN = {"art": "picture", "video": "clip", "music": "song", "open": "studio"}


def recipe_for(kind: str) -> Optional[dict[str, Any]]:
    want = (kind or "").strip().lower()
    for model in MODELS:
        if model["kind"] == want:
            return model
    return None


def normalize_studio(name: str, kind: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Resolve a human studio name to a catalog row. Empty name → default for kind."""
    raw = (name or "").strip().lower()
    want_kind = (kind or "").strip().lower() or None
    if not raw:
        if want_kind in _DEFAULT_STUDIO:
            return STUDIO_BY_ID[_DEFAULT_STUDIO[want_kind]]
        return None
    for studio in STUDIOS:
        if want_kind and studio["kind"] != want_kind and raw not in studio["aliases"]:
            # Allow cross-kind match when they named a specific app.
            pass
        if studio["id"] == raw or studio["label"].lower() == raw:
            return studio
        if raw in studio["aliases"]:
            return studio
        if raw in studio["id"].replace("_", " "):
            return studio
    # Partial: "adobe photoshop 2024" contains alias "adobe photoshop"
    for studio in STUDIOS:
        if any(alias in raw for alias in studio["aliases"] if len(alias) >= 3):
            return studio
    if want_kind in _DEFAULT_STUDIO:
        return STUDIO_BY_ID[_DEFAULT_STUDIO[want_kind]]
    return None


def reject_secrets(args: dict) -> Optional[str]:
    """Never collect Adobe / DAW passwords. Returns a user-facing message or None."""
    for key in args or {}:
        if str(key).lower().strip() in SECRET_KEYS:
            return (
                "I never need a Photoshop, Adobe, CapCut, or music-app password. "
                "Describe what you want made. After you say yes, I use the programs already on your computer."
            )
    return None


def confirm_preview(kind: str, prompt: str, studio_label: str, *, source: str = "") -> str:
    noun = _KIND_NOUN.get(kind, "work")
    bits = [
        f"I'll sketch this {noun} on your home computer, then open {studio_label}.",
        f"What you asked for:\n{(prompt or '').strip()[:800] or '(no description yet)'}",
    ]
    if source:
        bits.append(f"Starting from: {source[:200]}")
    studio = normalize_studio(studio_label, kind)
    if studio and studio.get("honest"):
        bits.append(studio["honest"])
    bits.append(
        "This uses the graphics card. The first time, Pinokio may download a model (a few GB). "
        f"I cannot click every button inside {studio_label}."
    )
    bits.append("I never need a Photoshop, Adobe, or music-app password.")
    bits.append("If that sounds right, say yes. Then I call this tool again with confirmed=true.")
    return "\n".join(bits)


def howto_text(kind: str, studio: dict[str, Any], prompt: str, source: str = "") -> str:
    label = studio.get("label") or "your studio"
    lines = [
        "Heirloom creative folder",
        "========================",
        "",
        "Your description is in prompt.txt and copied to the clipboard.",
        "Pinokio / ComfyUI do not need an account. We never need a Photoshop or music-app password.",
        "",
    ]
    if kind == "art":
        lines += [
            "Pictures",
            "--------",
            "1. Pinokio should be opening Fooocus or ComfyUI. Paste prompt.txt there and generate.",
            f"2. When a picture appears, open it in {label} (File → Open) to finish.",
            "3. If you have Photoshop Firefly, paste the same prompt there — it is already on the clipboard.",
            "I cannot click every Photoshop control for you.",
        ]
    elif kind == "video":
        lines += [
            "Video",
            "-----",
            "1. Pinokio / ComfyUI (WAN) can make a SHORT clip on this PC — not a full movie, not realtime.",
            f"2. Open that clip in {label} to cut, add titles, and add music.",
        ]
        if not studio.get("can_edit_timeline", True):
            lines.append(
                f"3. {studio.get('honest') or f'I opened {label} in the browser. I cannot edit its timeline.'} "
                "Use CapCut, Premiere, or DaVinci on this computer to edit."
            )
        else:
            lines.append("I cannot click every timeline button for you.")
        if source:
            lines.append(f"You mentioned this source: {source}")
    elif kind == "music":
        lines += [
            "Music",
            "-----",
            "1. Pinokio / ACE-Step can sketch a SHORT song from prompt.txt.",
            f"2. Open the audio in {label} to arrange, mix, and finish.",
            "I cannot play every fader in the DAW for you.",
        ]
    else:
        lines.append(f"Opened {label}.")
    lines += ["", "Folder: this one (prompt.txt lives here)."]
    return "\n".join(lines) + "\n"


def job_payload(
    kind: str,
    prompt: str,
    studio: dict[str, Any],
    *,
    source: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Self-contained payload for the home PC. No cloud secrets."""
    recipe = recipe_for(kind) if kind in ("art", "video", "music") else {}
    recipe = recipe or {}
    return {
        "kind": kind,
        "prompt": (prompt or "")[:4000],
        "title": (title or "")[:80],
        "source": (source or "")[:500],
        "recipe_id": recipe.get("id") or "",
        "pinokio_url": recipe.get("pinokio_url") or "",
        "studio": studio["id"],
        "studio_label": studio.get("label") or studio["id"],
        "studio_url": studio.get("url") or "",
        "fallback_url": studio.get("fallback_url") or "",
        "windows_globs": list(studio.get("windows_globs") or ()),
        "darwin_apps": list(studio.get("darwin_apps") or ()),
        "linux_bins": list(studio.get("linux_bins") or ()),
        "app_names": list(studio.get("app_names") or ()),
        "can_edit_timeline": bool(studio.get("can_edit_timeline", True)),
        "howto": howto_text(kind, studio, prompt, source),
    }


def public_catalog() -> dict[str, Any]:
    return {
        "kinds": list(JOB_KINDS),
        "models": MODELS,
        "studios": [
            {
                "id": s["id"],
                "label": s["label"],
                "kind": s["kind"],
                "web": bool(s.get("url")),
                "can_edit_timeline": bool(s.get("can_edit_timeline", True)),
            }
            for s in STUDIOS
        ],
        "honest": (
            "These models run on your home computer. We sketch a picture, a short clip, "
            "or a short song, then open the app you already own. We cannot click every "
            "control inside Photoshop, CapCut, or a DAW. Pinokio needs no account. "
            "We never ask for an Adobe or music-app password."
        ),
    }
