"""First-run setup catalog: disk budgets, vendor email, phone pairing.

Local models and vault live on the dedicated PC. Cloud vendors (ElevenLabs,
D-ID, fal) require the owner to create their own account and complete any
robot checks — Heirloom stores the resulting key. We do not automate
third-party sign-up or captcha.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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
        "email_query_param": "email",
        "key_where": "Settings → API Keys. Click Create Key.",
        "key_what": "Copy the secret that starts with sk_.",
        "you_do": (
            "If the email box is empty, paste (Ctrl+V) — Heirloom copied it.",
            "Click I'm not a robot / complete their check.",
            "Finish their sign-up, then come back here.",
        ),
        "create_account_bullets": (
            "Click Create account / Sign up — Heirloom cannot press that for you.",
            "If the email box is empty, paste (Ctrl+V). Heirloom copied it.",
            "Click I'm not a robot, then submit their form.",
        ),
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
        "email_query_param": "email",
        "key_where": "Account settings → API. Create or copy the key.",
        "key_what": "Paste the key, or email:secret if they show both.",
        "you_do": (
            "If the email box is empty, paste (Ctrl+V) — Heirloom copied it.",
            "Click I'm not a robot / complete their check.",
            "Finish their sign-up, then come back here.",
        ),
        "create_account_bullets": (
            "Click Sign up / Create account on their page.",
            "If the email box is empty, paste (Ctrl+V). Heirloom copied it.",
            "Click I'm not a robot, then submit their form.",
        ),
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
        "email_query_param": "email",
        "key_where": "Dashboard → Keys. Create a key.",
        "key_what": "Copy it as key_id:key_secret.",
        "you_do": (
            "If the email box is empty, paste (Ctrl+V) — Heirloom copied it.",
            "Click I'm not a robot / complete their check.",
            "Finish their sign-up, then come back here.",
        ),
        "create_account_bullets": (
            "Click Sign up on fal.ai.",
            "If the email box is empty, paste (Ctrl+V). Heirloom copied it.",
            "Click I'm not a robot, then submit their form.",
        ),
    },
)

INBOX_DOMAINS = {
    "gmail.com": ("Gmail", "https://mail.google.com/mail/u/0/#inbox"),
    "googlemail.com": ("Gmail", "https://mail.google.com/mail/u/0/#inbox"),
    "outlook.com": ("Outlook", "https://outlook.live.com/mail/0/"),
    "hotmail.com": ("Outlook", "https://outlook.live.com/mail/0/"),
    "live.com": ("Outlook", "https://outlook.live.com/mail/0/"),
    "msn.com": ("Outlook", "https://outlook.live.com/mail/0/"),
    "yahoo.com": ("Yahoo Mail", "https://mail.yahoo.com/"),
    "ymail.com": ("Yahoo Mail", "https://mail.yahoo.com/"),
    "icloud.com": ("iCloud Mail", "https://www.icloud.com/mail"),
    "me.com": ("iCloud Mail", "https://www.icloud.com/mail"),
    "mac.com": ("iCloud Mail", "https://www.icloud.com/mail"),
    "proton.me": ("Proton Mail", "https://mail.proton.me/u/0/inbox"),
    "protonmail.com": ("Proton Mail", "https://mail.proton.me/u/0/inbox"),
    "aol.com": ("AOL Mail", "https://mail.aol.com/"),
}

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


def signup_url_with_email(signup: str, email: str = "", param: str | None = "email") -> str:
    """Attach email as a query param when the vendor page might prefill it."""
    clean = (email or "").strip().lower()
    if not clean or not param or not signup:
        return signup
    parts = urlparse(signup)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[param] = clean
    return urlunparse(parts._replace(query=urlencode(query)))


def inbox_for_email(email: str = "") -> dict:
    """Official webmail inbox for a vendor-email domain, if we know one."""
    clean = (email or "").strip().lower()
    domain = clean.split("@")[-1] if "@" in clean else ""
    label, url = INBOX_DOMAINS.get(domain, ("your email inbox", None))
    return {"email": clean, "domain": domain, "label": label, "url": url}


def vendor_coach_steps(spec: dict, email: str = "") -> list[dict]:
    """Stay-on-top guide: we open official pages; they click robot / verify / copy."""
    clean = (email or "").strip().lower()
    inbox = inbox_for_email(clean)
    signup = signup_url_with_email(
        spec["signup_url"], clean, spec.get("email_query_param")
    )
    verify_body = (
        f"We opened {inbox['label']}. Find the message from {spec['label']} and click Verify."
        if inbox.get("url")
        else f"Open the inbox for {clean or 'your email'} and click the verify link from {spec['label']}."
    )
    return [
        {
            "id": "create_account",
            "kind": "pause",
            "title": f"Create your {spec['label']} account",
            "body": (
                "Their official sign-up page is open. Click Create account, paste your email "
                "if the box is empty, then click I'm not a robot. Heirloom cannot press those."
            ),
            "bullets": list(spec.get("create_account_bullets") or spec.get("you_do") or ()),
            "copy": clean,
            "open_url": signup,
            "auto_open": True,
            "cta": "I signed up (and clicked I'm not a robot)",
        },
        {
            "id": "verify_email",
            "kind": "pause",
            "title": f"Verify in {inbox['label']}",
            "body": verify_body,
            "bullets": [
                f"Look for mail to {clean}." if clean else "Use the same email you just typed.",
                "Open their message and click Verify / Confirm.",
            ],
            "open_url": inbox.get("url"),
            "auto_open": bool(inbox.get("url")),
            "cta": "I verified the email",
            "skip_cta": "Skip — already verified",
        },
        {
            "id": "find_key",
            "kind": "pause",
            "title": f"Get the {spec['label']} API key",
            "body": spec.get("key_where") or "Open their API keys page and copy a key.",
            "bullets": [spec.get("key_what") or "Copy the secret, then continue."],
            "open_url": spec["dashboard_url"],
            "auto_open": True,
            "cta": "I'm on the API keys page",
        },
        {
            "id": "paste_key",
            "kind": "paste",
            "title": "Paste the key into Heirloom",
            "body": "This box stays in Heirloom. After it saves, the guide moves to the next vendor.",
            "bullets": [spec.get("key_what") or "Paste the secret you copied."],
            "placeholder": spec["placeholder"],
            "cta": "Verify & save",
        },
    ]


def vendor_handoff(service_id: str, email: str = "") -> dict | None:
    """Official URLs + coach script. Humans still click robot / verify email."""
    spec = None
    for s in CLOUD_SETUP_SERVICES:
        if s["id"] == service_id:
            spec = s
            break
    if not spec:
        return None
    clean = (email or "").strip().lower()
    signup = signup_url_with_email(
        spec["signup_url"], clean, spec.get("email_query_param")
    )
    inbox = inbox_for_email(clean)
    return {
        "id": spec["id"],
        "label": spec["label"],
        "signup_url": signup,
        "dashboard_url": spec["dashboard_url"],
        "save_path": spec["save_path"],
        "verify_service": spec["verify_service"],
        "placeholder": spec["placeholder"],
        "email_query_param": spec.get("email_query_param") or "email",
        "email": clean,
        "inbox": inbox,
        "coach_steps": vendor_coach_steps(spec, clean),
        "we_do": [
            "Copy your vendor email to the clipboard.",
            "Open their official sign-up page, then their inbox, then their API keys page.",
            "Keep a stay-on-top guide with what to click and where to paste.",
            "Store the key you paste, then move to the next vendor.",
        ],
        "you_do": list(spec.get("you_do") or ()),
    }


def setup_catalog() -> dict:
    services = []
    for s in CLOUD_SETUP_SERVICES:
        services.append(
            {
                **{k: v for k, v in s.items() if k != "you_do"},
                "required_for": list(s["required_for"]),
                "you_do": list(s.get("you_do") or ()),
            }
        )
    return {
        "space_profiles": [dict(p, provision_features=list(p["provision_features"]), includes=list(p["includes"])) for p in SPACE_PROFILES],
        "phone_features": [dict(p) for p in PHONE_FEATURES],
        "cloud_services": services,
        "full_power_gb": {"min": 20, "max": 50},
        "local_first": True,
        "vendor_signup_policy": (
            "On the dedicated PC, after local models finish installing, a stay-on-top "
            "guide opens. Heirloom copies your email, opens the official sign-up page, "
            "then your inbox, then their API keys page, and watches the screen to "
            "advance. You click Create account, I'm not a robot, and Verify — we cannot "
            "drive their website, solve captchas, or read keys off the screen. Paste "
            "the key into Heirloom."
        ),
    }
