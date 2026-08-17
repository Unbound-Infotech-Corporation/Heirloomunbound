"""First-run setup catalog: disk budgets, vendor email, phone pairing.

Local models and vault live on the dedicated PC. Cloud vendors (ElevenLabs,
D-ID, fal) require the owner to create their own account and complete any
robot checks — Heirloom stores the resulting key. We do not automate
third-party sign-up or captcha.
"""
from __future__ import annotations

import re

# Realistic disk budgets for "full power" on a dedicated Windows box.
# Ollama runtime + llama3.1 + llava + Whisper + Piper + venv + vault headroom.
SPACE_PROFILES = (
    {
        "id": "lite",
        "label": "Lite",
        "gb_min": 3,
        "gb_max": 8,
        "vault_tier": "lite",
        "provision_features": ("stt",),
        "whisper": "base",
        "summary": "Local Whisper for journals. Twin and voice can use cloud fallbacks.",
        "includes": (
            "faster-whisper base (~0.2 GB)",
            "Vault: daily summaries only",
            "Cloud twin/TTS if you add keys",
        ),
    },
    {
        "id": "full",
        "label": "Full local (recommended)",
        "gb_min": 20,
        "gb_max": 35,
        "vault_tier": "partial",
        "provision_features": ("stt", "tts", "twin"),
        "whisper": "base",
        "summary": "Whisper + Ollama llama3.1 + Piper on this PC. Cloud keys are optional extras.",
        "includes": (
            "faster-whisper base (~0.2 GB)",
            "Ollama + llama3.1 (~5–8 GB)",
            "Piper voice (~0.1 GB) if installable",
            "Vault: transcripts forever, audio 30 days",
        ),
    },
    {
        "id": "max",
        "label": "Maximum",
        "gb_min": 40,
        "gb_max": 50,
        "vault_tier": "full",
        "provision_features": ("stt", "tts", "twin", "vision"),
        "whisper": "base",
        "summary": "Everything local: twin, screen vision (llava), speech, and a full vault.",
        "includes": (
            "faster-whisper (~0.2 GB)",
            "Ollama + llama3.1 + llava (~12–18 GB)",
            "Piper + vault keeping every recording",
            "Headroom for future models",
        ),
    },
)

PHONE_FEATURES = (
    {
        "id": "twin",
        "label": "Talk to twin",
        "hint": "Chat from your phone; heavy inference still runs on the PC.",
        "default": True,
    },
    {
        "id": "capture",
        "label": "Quick capture",
        "hint": "Save a thought or photo into the archive from your pocket.",
        "default": True,
    },
    {
        "id": "journal",
        "label": "Voice journal",
        "hint": "Record on the phone; transcription prefers the PC.",
        "default": True,
    },
    {
        "id": "reminders",
        "label": "Reminders",
        "hint": "See and snooze reminders the twin set.",
        "default": True,
    },
    {
        "id": "live_listen",
        "label": "Live room listen",
        "hint": "Always-on mic — stays on the dedicated PC, not the phone.",
        "default": False,
        "pc_only": True,
    },
)

CLOUD_SETUP_SERVICES = (
    {
        "id": "elevenlabs",
        "label": "ElevenLabs",
        "powers": "Cloned voice so the twin sounds like you.",
        "signup_url": "https://elevenlabs.io/app/sign-up",
        "dashboard_url": "https://elevenlabs.io/app/settings/api-keys",
        "save_path": "/voice-clone/api-key",
        "verify_service": "elevenlabs",
        "placeholder": "sk_…",
        "required_for": ("tts",),
    },
    {
        "id": "did",
        "label": "D-ID",
        "powers": "Talking-head video of your face.",
        "signup_url": "https://studio.d-id.com/",
        "dashboard_url": "https://studio.d-id.com/account-settings",
        "save_path": "/avatar/api-key",
        "verify_service": "did",
        "placeholder": "email:secret",
        "required_for": ("avatar",),
    },
    {
        "id": "fal",
        "label": "fal.ai",
        "powers": "Optional Avatar Studio beautify only.",
        "signup_url": "https://fal.ai/login",
        "dashboard_url": "https://fal.ai/dashboard/keys",
        "save_path": "/avatar-studio/api-key",
        "verify_service": "fal",
        "placeholder": "key_id:key_secret",
        "required_for": (),
    },
)

SETUP_DEFAULTS: dict = {
    "complete": False,
    "space_profile": "full",
    "vendor_email": "",
    "prefer_local": True,
    "phone_features": ["twin", "capture", "journal", "reminders"],
    "paired_phone_id": None,
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_IDS = {p["id"] for p in PHONE_FEATURES if not p.get("pc_only")}
_PROFILE_IDS = {p["id"] for p in SPACE_PROFILES}


def space_profile(profile_id: str) -> dict:
    for p in SPACE_PROFILES:
        if p["id"] == profile_id:
            return p
    return next(p for p in SPACE_PROFILES if p["id"] == "full")


def clamp_setup(raw: dict | None) -> dict:
    src = dict(SETUP_DEFAULTS)
    src["phone_features"] = list(SETUP_DEFAULTS["phone_features"])
    if not isinstance(raw, dict):
        return src
    src["complete"] = bool(raw.get("complete"))
    if raw.get("space_profile") in _PROFILE_IDS:
        src["space_profile"] = raw["space_profile"]
    email = str(raw.get("vendor_email") or "").strip()[:200].lower()
    src["vendor_email"] = email if (not email or _EMAIL_RE.match(email)) else ""
    src["prefer_local"] = bool(raw.get("prefer_local", True))
    feats = raw.get("phone_features")
    if isinstance(feats, list):
        src["phone_features"] = [str(x) for x in feats if str(x) in _PHONE_IDS]
    pid = raw.get("paired_phone_id")
    src["paired_phone_id"] = str(pid).strip()[:64] if pid else None
    return src


def setup_catalog() -> dict:
    return {
        "space_profiles": [dict(p, provision_features=list(p["provision_features"]), includes=list(p["includes"])) for p in SPACE_PROFILES],
        "phone_features": [dict(p) for p in PHONE_FEATURES],
        "cloud_services": [dict(s, required_for=list(s["required_for"])) for s in CLOUD_SETUP_SERVICES],
        "full_power_gb": {"min": 20, "max": 50},
        "local_first": True,
        "vendor_signup_policy": (
            "Heirloom opens the official vendor site and stores the API key you paste. "
            "You create the account and complete any 'not a robot' checks yourself. "
            "We cannot create third-party accounts or solve captchas on your behalf."
        ),
    }
