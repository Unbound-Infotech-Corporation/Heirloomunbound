"""First-run setup catalog: disk budgets, vendor email, phone pairing.

Local models and vault live on the dedicated PC. Cloud vendors (ElevenLabs,
D-ID, fal) require the owner to create their own account and complete any
robot checks — Heirloom stores the resulting key. We do not automate
third-party sign-up or captcha.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Four Heirloom Unbound install sizes. Legacy ids stay aliases so saved
# companion / studio_setup rows from lite/full/max keep resolving.
PROFILE_ALIASES = {
    "lite": "small",
    "full": "medium",
    "max": "large",
    "studio": "large",
}

DEDICATED_RECOMMEND_GB = 180
LARGE_RECOMMEND_GB = 100
MEDIUM_RECOMMEND_GB = 40

SPACE_PROFILES = (
    {
        "id": "small",
        "label": "Small",
        "gb_min": 5,
        "gb_max": 12,
        "vault_tier": "lite",
        "provision_features": ("stt", "tts"),
        "whisper": "base",
        "gpu_required": False,
        "voice_clone": (),
        "warm_engines": (),
        "machine_role": False,
        "summary": "App, Whisper, Piper, and a lite vault. Twin, TTS, and avatar stay cloud Auto fallbacks.",
        "includes": (
            "Heirloom Unbound app",
            "faster-whisper base or tiny (~0.2 GB) — CPU is enough",
            "Piper voice (~0.1 GB) if installable",
            "Vault: daily summaries only",
            "Twin / TTS / avatar: cloud Auto fallback — no Ollama, Voicebox, or LatentSync required",
        ),
    },
    {
        "id": "medium",
        "label": "Medium",
        "gb_min": 40,
        "gb_max": 70,
        "vault_tier": "partial",
        "provision_features": ("stt", "tts", "twin", "voice_clone"),
        "whisper": "small",
        "gpu_required": False,
        "voice_clone": ("qwen3_tts_0_6b", "voicebox"),
        "warm_engines": ("ollama",),
        "machine_role": False,
        "summary": "Small plus a local twin mind and one voice-clone path. Cloud keys stay optional.",
        "includes": (
            "Everything in Small",
            "Ollama + llama3.1 (~5–8 GB)",
            "faster-whisper small (~0.5 GB)",
            "One voice-clone path: Qwen3-TTS 0.6B or Voicebox (coach if the engine is not listening)",
            "Waveform likeness",
            "Vault: transcripts forever, audio 30 days",
        ),
    },
    {
        "id": "large",
        "label": "Large",
        "gb_min": 100,
        "gb_max": 160,
        "vault_tier": "full",
        "provision_features": (
            "stt",
            "tts",
            "twin",
            "vision",
            "voicebox",
            "qwen3_tts",
            "latentsync",
            "avatar",
        ),
        "whisper": "large-v3",
        "gpu_required": True,
        "voice_clone": ("voicebox", "qwen3_tts_1_7b"),
        "warm_engines": ("ollama", "voicebox", "qwen3_tts", "latentsync"),
        "machine_role": False,
        "summary": "Full local stack: stronger twin, vision, both clone engines, and a talking likeness.",
        "includes": (
            "faster-whisper large-v3 (~3 GB)",
            "Stronger twin + vision (llama3.1 + llava)",
            "Voicebox AND Qwen3-TTS 1.7B (coach or silent MSI/Docker/pip — never Pinokio)",
            "LatentSync talking likeness (+ MuseTalk when the license allows)",
            "Local beautify when present",
            "Vault: keep every recording",
        ),
    },
    {
        "id": "dedicated",
        "label": "Dedicated PC",
        "gb_min": 200,
        "gb_max": 0,
        "vault_tier": "full",
        "provision_features": (
            "stt",
            "tts",
            "twin",
            "vision",
            "voicebox",
            "qwen3_tts",
            "latentsync",
            "avatar",
            "machine_role",
        ),
        "whisper": "large-v3",
        "gpu_required": True,
        "voice_clone": ("voicebox", "qwen3_tts_1_7b"),
        "warm_engines": ("ollama", "voicebox", "qwen3_tts", "latentsync"),
        "machine_role": True,
        "summary": "Consecrate this machine for Heirloom Unbound: Large plus startup, vault drive, and warm engines.",
        "includes": (
            "Everything in Large",
            "This-PC-exists-for-Heirloom-Unbound consent",
            "Vault / data drive (second disk recommended)",
            "Start with Windows + optional always-on service",
            "High-performance power plan only with explicit consent",
            "Warm probes for Ollama, Voicebox, Qwen3-TTS, LatentSync",
            "Standing routines and live room listen default toward on",
            "Optional desktop / lock branding: Heirloom Unbound · Dedicated",
            "Overnight maintenance hook to keep models current",
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
    "space_profile": "medium",
    "install_profile": "medium",
    "vendor_email": "",
    "prefer_local": True,
    "phone_features": ["twin", "capture", "journal", "reminders"],
    "paired_phone_id": None,
    "dedicated_consent": False,
    "vault_drive": "",
    "start_with_windows": False,
    "power_plan_consent": False,
    "warm_engines": False,
    "live_listen_default": False,
    "branding_dedicated": False,
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_IDS = {p["id"] for p in PHONE_FEATURES if not p.get("pc_only")}
_CANONICAL_IDS = {p["id"] for p in SPACE_PROFILES}
_PROFILE_IDS = _CANONICAL_IDS | set(PROFILE_ALIASES)

# Official / HF / Ollama artifacts. Engine listeners are probed, never Pinokio.
_PROVISION_ARTIFACTS: dict[str, dict] = {
    "app": {
        "id": "app",
        "kind": "app",
        "name": "Heirloom Unbound app",
        "url": "",
        "approx_bytes": 400_000_000,
        "required": True,
        "fatal": True,
        "order": 1,
        "probe": "app",
        "install": "bundle",
    },
    "whisper-tiny": {
        "id": "whisper-tiny",
        "kind": "whisper",
        "name": "Whisper tiny",
        "url": "https://huggingface.co/Systran/faster-whisper-tiny",
        "approx_bytes": 80_000_000,
        "required": False,
        "fatal": False,
        "order": 10,
        "probe": "whisper",
        "install": "faster-whisper",
        "whisper": "tiny",
    },
    "whisper-base": {
        "id": "whisper-base",
        "kind": "whisper",
        "name": "Whisper base",
        "url": "https://huggingface.co/Systran/faster-whisper-base",
        "approx_bytes": 150_000_000,
        "required": True,
        "fatal": False,
        "order": 11,
        "probe": "whisper",
        "install": "faster-whisper",
        "whisper": "base",
    },
    "whisper-small": {
        "id": "whisper-small",
        "kind": "whisper",
        "name": "Whisper small",
        "url": "https://huggingface.co/Systran/faster-whisper-small",
        "approx_bytes": 500_000_000,
        "required": True,
        "fatal": False,
        "order": 12,
        "probe": "whisper",
        "install": "faster-whisper",
        "whisper": "small",
    },
    "whisper-large-v3": {
        "id": "whisper-large-v3",
        "kind": "whisper",
        "name": "Whisper large-v3",
        "url": "https://huggingface.co/Systran/faster-whisper-large-v3",
        "approx_bytes": 3_100_000_000,
        "required": True,
        "fatal": False,
        "order": 13,
        "probe": "whisper",
        "install": "faster-whisper",
        "whisper": "large-v3",
    },
    "piper": {
        "id": "piper",
        "kind": "tts",
        "name": "Piper",
        "url": "https://github.com/rhasspy/piper",
        "approx_bytes": 100_000_000,
        "required": False,
        "fatal": False,
        "order": 20,
        "probe": "piper",
        "install": "path",
    },
    "ollama-llama31": {
        "id": "ollama-llama31",
        "kind": "twin",
        "name": "Ollama llama3.1",
        "url": "https://ollama.com/library/llama3.1",
        "approx_bytes": 5_000_000_000,
        "required": True,
        "fatal": False,
        "order": 30,
        "probe": "ollama",
        "install": "ollama-pull",
        "model": "llama3.1",
    },
    "ollama-llava": {
        "id": "ollama-llava",
        "kind": "vision",
        "name": "Ollama llava",
        "url": "https://ollama.com/library/llava",
        "approx_bytes": 4_500_000_000,
        "required": False,
        "fatal": False,
        "order": 31,
        "probe": "ollama",
        "install": "ollama-pull",
        "model": "llava",
    },
    "qwen3-tts-0-6b": {
        "id": "qwen3-tts-0-6b",
        "kind": "voice_clone",
        "name": "Qwen3-TTS 0.6B",
        "url": "https://huggingface.co/Qwen/Qwen3-TTS",
        "approx_bytes": 1_200_000_000,
        "required": False,
        "fatal": False,
        "order": 40,
        "probe": "qwen3_tts",
        "install": "coach-or-pip",
    },
    "qwen3-tts-1-7b": {
        "id": "qwen3-tts-1-7b",
        "kind": "voice_clone",
        "name": "Qwen3-TTS 1.7B",
        "url": "https://huggingface.co/Qwen/Qwen3-TTS",
        "approx_bytes": 3_400_000_000,
        "required": False,
        "fatal": False,
        "order": 41,
        "probe": "qwen3_tts",
        "install": "coach-or-pip",
    },
    "voicebox": {
        "id": "voicebox",
        "kind": "voice_clone",
        "name": "Voicebox",
        "url": "https://github.com/facebookresearch/voicebox",
        "approx_bytes": 8_000_000_000,
        "required": False,
        "fatal": False,
        "order": 42,
        "probe": "voicebox",
        "install": "coach-or-msi",
    },
    "latentsync": {
        "id": "latentsync",
        "kind": "avatar",
        "name": "LatentSync",
        "url": "https://github.com/bytedance/LatentSync",
        "approx_bytes": 18_000_000_000,
        "required": False,
        "fatal": False,
        "order": 50,
        "probe": "latentsync",
        "install": "coach-or-docker",
    },
    "musetalk": {
        "id": "musetalk",
        "kind": "avatar",
        "name": "MuseTalk",
        "url": "https://github.com/TMElyralab/MuseTalk",
        "approx_bytes": 6_000_000_000,
        "required": False,
        "fatal": False,
        "order": 51,
        "probe": "musetalk",
        "install": "coach-if-license-ok",
    },
    "vault-lite": {
        "id": "vault-lite",
        "kind": "vault",
        "name": "Vault lite",
        "url": "",
        "approx_bytes": 500_000_000,
        "required": True,
        "fatal": False,
        "order": 80,
        "probe": "vault",
        "install": "local",
    },
    "vault-partial": {
        "id": "vault-partial",
        "kind": "vault",
        "name": "Vault partial",
        "url": "",
        "approx_bytes": 8_000_000_000,
        "required": True,
        "fatal": False,
        "order": 81,
        "probe": "vault",
        "install": "local",
    },
    "vault-full": {
        "id": "vault-full",
        "kind": "vault",
        "name": "Vault full",
        "url": "",
        "approx_bytes": 60_000_000_000,
        "required": True,
        "fatal": False,
        "order": 82,
        "probe": "vault",
        "install": "local",
    },
}

_PROFILE_ARTIFACT_IDS: dict[str, tuple[str, ...]] = {
    "small": ("app", "whisper-tiny", "whisper-base", "piper", "vault-lite"),
    "medium": (
        "app",
        "whisper-tiny",
        "whisper-base",
        "whisper-small",
        "piper",
        "ollama-llama31",
        "qwen3-tts-0-6b",
        "voicebox",
        "vault-partial",
    ),
    "large": (
        "app",
        "whisper-base",
        "whisper-small",
        "whisper-large-v3",
        "piper",
        "ollama-llama31",
        "ollama-llava",
        "voicebox",
        "qwen3-tts-1-7b",
        "latentsync",
        "musetalk",
        "vault-full",
    ),
    "dedicated": (
        "app",
        "whisper-base",
        "whisper-small",
        "whisper-large-v3",
        "piper",
        "ollama-llama31",
        "ollama-llava",
        "voicebox",
        "qwen3-tts-1-7b",
        "latentsync",
        "musetalk",
        "vault-full",
    ),
}


def normalize_profile_id(profile_id: str | None) -> str:
    raw = str(profile_id or "").strip().lower()
    if raw in PROFILE_ALIASES:
        return PROFILE_ALIASES[raw]
    if raw in _CANONICAL_IDS:
        return raw
    return "medium"


def space_profile(profile_id: str) -> dict:
    wanted = normalize_profile_id(profile_id)
    for p in SPACE_PROFILES:
        if p["id"] == wanted:
            return p
    return next(p for p in SPACE_PROFILES if p["id"] == "medium")


def recommend_profile(free_gb: float | int | None) -> str:
    """Pick an install size from free disk. Dedicated only when space is huge."""
    try:
        free = float(free_gb) if free_gb is not None else 0.0
    except (TypeError, ValueError):
        free = 0.0
    if free >= DEDICATED_RECOMMEND_GB:
        return "dedicated"
    if free >= LARGE_RECOMMEND_GB:
        return "large"
    if free >= MEDIUM_RECOMMEND_GB:
        return "medium"
    return "small"


def provision_features(profile_id: str) -> list[str]:
    return list(space_profile(profile_id)["provision_features"])


def provision_manifest(profile_id: str) -> dict:
    profile = space_profile(profile_id)
    pid = profile["id"]
    artifacts = []
    for art_id in _PROFILE_ARTIFACT_IDS.get(pid, ()):
        spec = _PROVISION_ARTIFACTS.get(art_id)
        if spec:
            artifacts.append(dict(spec))
    artifacts.sort(key=lambda a: int(a.get("order") or 0))
    approx = sum(int(a.get("approx_bytes") or 0) for a in artifacts)
    return {
        "id": pid,
        "label": profile["label"],
        "gpu_required": bool(profile.get("gpu_required")),
        "whisper": profile.get("whisper") or "base",
        "vault_tier": profile.get("vault_tier") or "lite",
        "features": list(profile["provision_features"]),
        "warm_engines": list(profile.get("warm_engines") or ()),
        "voice_clone": list(profile.get("voice_clone") or ()),
        "machine_role": bool(profile.get("machine_role")),
        "approx_bytes": approx,
        "artifacts": artifacts,
        "install_order": [a["id"] for a in artifacts],
        "health_probes": list(dict.fromkeys(a["probe"] for a in artifacts if a.get("probe"))),
        "coach_on_engine_failure": True,
        "abort_on_engine_failure": False,
        "pinokio": False,
    }


def public_space_profile(profile: dict) -> dict:
    return dict(
        profile,
        provision_features=list(profile["provision_features"]),
        includes=list(profile["includes"]),
        warm_engines=list(profile.get("warm_engines") or ()),
        voice_clone=list(profile.get("voice_clone") or ()),
        manifest=provision_manifest(profile["id"]),
    )


def clamp_setup(raw: dict | None) -> dict:
    src = dict(SETUP_DEFAULTS)
    src["phone_features"] = list(SETUP_DEFAULTS["phone_features"])
    if not isinstance(raw, dict):
        return src
    src["complete"] = bool(raw.get("complete"))
    incoming = raw.get("space_profile") or raw.get("install_profile")
    if incoming in _PROFILE_IDS or incoming in _CANONICAL_IDS:
        src["space_profile"] = normalize_profile_id(str(incoming))
    elif incoming:
        src["space_profile"] = normalize_profile_id(str(incoming))
    src["install_profile"] = src["space_profile"]
    email = str(raw.get("vendor_email") or "").strip()[:200].lower()
    src["vendor_email"] = email if (not email or _EMAIL_RE.match(email)) else ""
    src["prefer_local"] = bool(raw.get("prefer_local", True))
    feats = raw.get("phone_features")
    if isinstance(feats, list):
        src["phone_features"] = [str(x) for x in feats if str(x) in _PHONE_IDS]
    pid = raw.get("paired_phone_id")
    src["paired_phone_id"] = str(pid).strip()[:64] if pid else None
    src["dedicated_consent"] = bool(raw.get("dedicated_consent"))
    src["vault_drive"] = str(raw.get("vault_drive") or "").strip()[:500]
    src["start_with_windows"] = bool(raw.get("start_with_windows"))
    src["power_plan_consent"] = bool(raw.get("power_plan_consent"))
    src["warm_engines"] = bool(raw.get("warm_engines"))
    src["live_listen_default"] = bool(raw.get("live_listen_default"))
    src["branding_dedicated"] = bool(raw.get("branding_dedicated"))
    if src["space_profile"] == "dedicated":
        src["install_profile"] = "dedicated"
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
        "product": "Heirloom Unbound",
        "space_profiles": [public_space_profile(p) for p in SPACE_PROFILES],
        "profile_aliases": dict(PROFILE_ALIASES),
        "phone_features": [dict(p) for p in PHONE_FEATURES],
        "cloud_services": services,
        "full_power_gb": {"min": 100, "max": 160},
        "recommend_gb": {
            "dedicated": DEDICATED_RECOMMEND_GB,
            "large": LARGE_RECOMMEND_GB,
            "medium": MEDIUM_RECOMMEND_GB,
        },
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
