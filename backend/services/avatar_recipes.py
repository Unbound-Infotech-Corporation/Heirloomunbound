"""Pinokio + ComfyUI recipes for a local lifelike twin.

Catalog only — no database. The cloud cannot run these models; the home PC
does, via Pinokio (one-click install) or ComfyUI already used for photo restore.

Honest scope
------------
A realtime Black-Mirror full-body clone is not something we can download into
the cloud. What *is* free and local today:

* **Look at you** — LivePortrait copies your webcam / a driving video onto
  your portrait so the twin turns, blinks, and tracks you.
* **Talks like you** — cloned or local TTS audio drives EchoMimic / Sonic /
  WAN MultiTalk so lips and expression match the voice.
* **Full-body still** — InstantID / IPAdapter in ComfyUI, using a few photos
  plus a body sheet (height, build) as the identity prompt.
* **Short full-body motion** — WAN 2.1 image-to-video on a beefy GPU
  (not realtime).

InsightFace weights are non-commercial; prefer the MediaPipe LivePortrait
path. This catalog is for the *owner's own face only*.
"""
from __future__ import annotations

from typing import Any, Optional

ANGLES: tuple[str, ...] = ("front", "left", "right", "three_quarter", "full")

BUILDS: tuple[str, ...] = ("slim", "average", "athletic", "heavy")

PRESENTATIONS: tuple[str, ...] = (
    "unspecified",
    "masculine",
    "feminine",
    "androgynous",
)

ENGINES: tuple[str, ...] = ("auto", "local", "did")

JOB_KINDS: tuple[str, ...] = ("still", "talk", "look")

# Pinokio deep-links install the GitHub app in one click on the home PC.
_PINOKIO_ITEM = "https://pinokio.co/item?uri="

PINOKIO_APPS: list[dict[str, Any]] = [
    {
        "id": "pinokio-comfy",
        "label": "ComfyUI (Pinokio)",
        "kind": "host",
        "blurb": "The workbench. Install this first — InstantID, LivePortrait, EchoMimic, and WAN all run as nodes inside it.",
        "vram_gb": 8,
        "github": "https://github.com/pinokiofactory/comfy",
        "pinokio_url": f"{_PINOKIO_ITEM}https://github.com/pinokiofactory/comfy",
        "docs_url": "https://github.com/comfyanonymous/ComfyUI",
    },
    {
        "id": "pinokio-liveportrait",
        "label": "LivePortrait (Pinokio)",
        "kind": "look_at_you",
        "blurb": "Point a webcam at yourself. Your uploaded face looks back — blinks, turns, tracks. This is the scary-real one.",
        "vram_gb": 6,
        "github": "https://github.com/pinokiofactory/liveportrait",
        "pinokio_url": f"{_PINOKIO_ITEM}https://github.com/pinokiofactory/liveportrait",
        "docs_url": "https://github.com/KwaiVGI/LivePortrait",
        "license_note": "Use the MediaPipe face detector (MIT). InsightFace weights are non-commercial.",
    },
]

RECIPES: list[dict[str, Any]] = [
    {
        "id": "liveportrait",
        "label": "Look at you",
        "kind": "look",
        "blurb": "Your portrait copies your live motion. Webcam on the home PC, front photo as the source. Near-realtime on a 6 GB card.",
        "vram_gb": 6,
        "realtime": True,
        "body": False,
        "pinokio_url": PINOKIO_APPS[1]["pinokio_url"],
        "github": "https://github.com/kijai/ComfyUI-LivePortraitKJ",
        "comfy_nodes": "kijai/ComfyUI-LivePortraitKJ",
        "license_note": "Prefer MediaPipe over InsightFace.",
        "howto": "Install LivePortrait in Pinokio (or the ComfyUI node). Heirloom copies your front photo into ~/Heirloom/avatar and opens the app. Enable the webcam as the driving video.",
    },
    {
        "id": "echomimic",
        "label": "Talking twin (EchoMimic)",
        "kind": "talk",
        "blurb": "Audio-driven. v2 is semi-body (shoulders + hands); v3 is a unified human animator. Best local match for 'talks like you'.",
        "vram_gb": 10,
        "realtime": False,
        "body": True,
        "pinokio_url": PINOKIO_APPS[0]["pinokio_url"],
        "github": "https://github.com/smthemex/ComfyUI_EchoMimic",
        "comfy_nodes": "smthemex/ComfyUI_EchoMimic",
        "license_note": "Ant Group EchoMimic — check the model card before commercial use.",
        "howto": "Install ComfyUI in Pinokio, then the EchoMimic custom node. Heirloom drops your photos, a body prompt, and (if local TTS is on) a spoken WAV into ~/Heirloom/avatar. Load those in the EchoMimic workflow.",
    },
    {
        "id": "sonic",
        "label": "Emotive lips (Sonic)",
        "kind": "talk",
        "blurb": "Portrait talking-head via Stable Video Diffusion. Strong expressions, needs SVD XT weights.",
        "vram_gb": 12,
        "realtime": False,
        "body": False,
        "pinokio_url": PINOKIO_APPS[0]["pinokio_url"],
        "github": "https://github.com/smthemex/ComfyUI_Sonic",
        "comfy_nodes": "smthemex/ComfyUI_Sonic",
        "license_note": "Needs SVD XT checkpoints in ComfyUI/models.",
        "howto": "Same ComfyUI host. Point Sonic at your front photo plus a WAV of the twin's line.",
    },
    {
        "id": "multitalk",
        "label": "WAN MultiTalk",
        "kind": "talk",
        "blurb": "Audio → lips and expression on WAN 2.1 image-to-video. ~10 s at 480p. Needs a 12 GB+ card.",
        "vram_gb": 12,
        "realtime": False,
        "body": True,
        "pinokio_url": PINOKIO_APPS[0]["pinokio_url"],
        "github": "https://github.com/kijai/ComfyUI-WanVideoWrapper",
        "comfy_nodes": "kijai/ComfyUI-WanVideoWrapper",
        "license_note": "WAN 2.1 weights are large — download only what you will run.",
        "howto": "Use a full-body still as the start frame. Keep clips short; this is not a live mirror.",
    },
    {
        "id": "instantid",
        "label": "Full-body still (InstantID)",
        "kind": "still",
        "blurb": "A few face photos + height and build → one identity-consistent full-body still. That still is what EchoMimic / WAN then animate.",
        "vram_gb": 8,
        "realtime": False,
        "body": True,
        "pinokio_url": PINOKIO_APPS[0]["pinokio_url"],
        "github": "https://github.com/instantX-research/InstantID",
        "comfy_nodes": "cubiq/ComfyUI_InstantID or IPAdapter + PuLID",
        "license_note": "Identity adapters work best with 3–5 clear photos, not one selfie.",
        "howto": "Heirloom writes prompt.txt from your body sheet and copies every angle into the avatar folder. In ComfyUI, load InstantID / IPAdapter with those refs.",
    },
]

RECIPE_BY_ID: dict[str, dict[str, Any]] = {r["id"]: r for r in RECIPES}

_KIND_DEFAULT = {"look": "liveportrait", "talk": "echomimic", "still": "instantid"}


def recipe_for(recipe_id: str) -> Optional[dict[str, Any]]:
    rid = (recipe_id or "").strip().lower()
    return RECIPE_BY_ID.get(rid)


def default_recipe_for(kind: str) -> dict[str, Any]:
    kid = (kind or "").strip().lower()
    rid = _KIND_DEFAULT.get(kid, "liveportrait")
    return RECIPE_BY_ID[rid]


def is_known_angle(angle: str) -> bool:
    return (angle or "").strip().lower() in ANGLES


def is_known_kind(kind: str) -> bool:
    return (kind or "").strip().lower() in JOB_KINDS


def is_known_engine(engine: str) -> bool:
    return (engine or "").strip().lower() in ENGINES


def normalize_body(raw: Optional[dict]) -> dict[str, Any]:
    """Clamp a body-sheet payload. Missing fields stay None / default."""
    src = raw if isinstance(raw, dict) else {}
    height = src.get("height_cm")
    weight = src.get("weight_kg")
    try:
        height_cm = int(height) if height not in (None, "") else None
    except (TypeError, ValueError):
        height_cm = None
    try:
        weight_kg = int(weight) if weight not in (None, "") else None
    except (TypeError, ValueError):
        weight_kg = None
    if height_cm is not None:
        height_cm = max(90, min(230, height_cm))
    if weight_kg is not None:
        weight_kg = max(30, min(250, weight_kg))
    build = str(src.get("build") or "average").strip().lower()
    if build not in BUILDS:
        build = "average"
    presentation = str(src.get("presentation") or "unspecified").strip().lower()
    if presentation not in PRESENTATIONS:
        presentation = "unspecified"
    notes = str(src.get("notes") or "").strip()[:500]
    return {
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "build": build,
        "presentation": presentation,
        "notes": notes,
    }


def still_prompt(body: Optional[dict], extra: str = "") -> str:
    """Identity prompt for InstantID / IPAdapter full-body stills."""
    b = normalize_body(body)
    bits = [
        "Photorealistic full-body photograph of the same person as the reference photos,",
        "standing, looking at the camera, natural skin texture, accurate facial identity,",
        "no extra people, no cartoon, no text, 85mm, soft studio light.",
    ]
    if b["height_cm"]:
        bits.append(f"Height about {b['height_cm']} cm.")
    bits.append(f"Build: {b['build']}.")
    if b["presentation"] != "unspecified":
        bits.append(f"Presentation: {b['presentation']}.")
    if b["weight_kg"]:
        bits.append(f"Weight about {b['weight_kg']} kg — keep proportions honest.")
    if b["notes"]:
        bits.append(b["notes"])
    extra = (extra or "").strip()
    if extra:
        bits.append(extra)
    return " ".join(bits)


def public_catalog() -> dict[str, Any]:
    return {
        "angles": list(ANGLES),
        "builds": list(BUILDS),
        "presentations": list(PRESENTATIONS),
        "engines": list(ENGINES),
        "pinokio": PINOKIO_APPS,
        "recipes": RECIPES,
        "setup": SIMPLE_SETUP,
        "honest": (
            "These models run on your home computer, not in Heirloom's cloud. "
            "A live full-body photoreal clone still needs a local GPU. "
            "LivePortrait is the look-back-at-you path; EchoMimic / Sonic / WAN "
            "are the talking path; InstantID builds the still those animators start from."
        ),
    }


# Grandmother path: one permission, then the home PC downloads official installers.
# Pinokio and ComfyUI are local programs. They do not need an email, password, or
# cloud account. We never collect login secrets for third-party sites.
PINOKIO_RELEASES_API = "https://api.github.com/repos/pinokiocomputer/pinokio/releases/latest"

DOWNLOAD_HOSTS: tuple[str, ...] = (
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "release-assets.githubusercontent.com",
)

SIMPLE_SETUP: dict[str, Any] = {
    "title": "Set up my twin",
    "blurb": "Three taps. We install the free tools on your home computer. No extra accounts, no passwords.",
    "consent": (
        "I want Heirloom to install the free twin tools on my home computer. "
        "Pinokio and ComfyUI run on this PC and do not need an email or password. "
        "Heirloom will never ask for my login to those programs."
    ),
    "windows_note": (
        "Windows may show a blue 'Windows protected your PC' box. That is normal for a new download. "
        "Click More info, then Run anyway."
    ),
    "no_accounts": True,
    "no_passwords": True,
    "releases_api": PINOKIO_RELEASES_API,
    "apps": [a["pinokio_url"] for a in PINOKIO_APPS],
    "steps": [
        "Add a photo of your face (a clear one, looking at the camera).",
        "Tick the box so we know you want this on your computer.",
        "Tap Set up my twin. Leave the Heirloom app open on the home computer.",
        "If Windows asks, click More info, then Run anyway. Then tap Install in the Pinokio window.",
        "When that is done, tap Look at me.",
    ],
}


def host_is_allowed(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url or "").hostname or "").lower()
    return host in DOWNLOAD_HOSTS


def pick_pinokio_asset(assets: list, system: str, machine: str = "") -> Optional[dict[str, Any]]:
    """Choose the official Pinokio installer for this OS from a GitHub release."""
    sys_name = (system or "").lower()
    arch = (machine or "").lower()
    arm = arch in ("arm64", "aarch64")
    rows: list[dict[str, Any]] = []
    for raw in assets or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "")
        url = str(raw.get("browser_download_url") or "")
        if not name or not url or "blockmap" in name.lower():
            continue
        if not host_is_allowed(url):
            continue
        rows.append({"name": name, "url": url})
    if sys_name.startswith("win"):
        for row in rows:
            if row["name"].lower() == "pinokio.exe":
                return row
        for row in rows:
            if row["name"].lower().endswith(".exe"):
                return row
    if sys_name in ("darwin", "mac", "macos"):
        dmg = [r for r in rows if r["name"].lower().endswith(".dmg")]
        for row in dmg:
            has_arm = "arm64" in row["name"].lower()
            if has_arm == arm:
                return row
        return dmg[0] if dmg else None
    # Linux
    if arm:
        for row in rows:
            n = row["name"].lower()
            if n.endswith(".appimage") and "arm64" in n:
                return row
    for row in rows:
        n = row["name"].lower()
        if n.endswith(".appimage") and "arm64" not in n:
            return row
    for row in rows:
        if row["name"].lower().endswith(".deb"):
            return row
    return None


# Keys we will never accept on the easy-setup endpoint. Pinokio and ComfyUI
# are local programs; they do not need an email or password.
_SECRET_SETUP_KEYS = frozenset({
    "password",
    "passwd",
    "pass",
    "email",
    "username",
    "login",
    "secret",
    "api_key",
    "token",
    "pinokio_password",
    "comfy_password",
    "huggingface_token",
})


def reject_secret_fields(raw: Optional[dict]) -> None:
    """Raise ValueError if the payload looks like a third-party login."""
    src = raw if isinstance(raw, dict) else {}
    for key in src:
        k = str(key).strip().lower()
        if k in _SECRET_SETUP_KEYS or "password" in k:
            raise ValueError(
                "Heirloom never asks for a Pinokio or ComfyUI password. "
                "Those programs run on your computer and do not need an account."
            )


def consent_is_given(raw: Optional[dict]) -> bool:
    src = raw if isinstance(raw, dict) else {}
    value = src.get("consent")
    if value is True:
        return True
    if isinstance(value, str) and value.strip().lower() in ("true", "yes", "1", "on"):
        return True
    return False


def assert_setup_payload_safe(raw: Optional[dict]) -> None:
    """Grandmother-plain checks before we queue the home-PC installer."""
    reject_secret_fields(raw)
    if not consent_is_given(raw):
        raise ValueError("Tick the box so we know you want this on your computer.")
