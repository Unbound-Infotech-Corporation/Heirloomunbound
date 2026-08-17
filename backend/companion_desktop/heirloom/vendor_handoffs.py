"""Official vendor URLs for first-run when the cloud has no /api/studio yet.

The downloadable zip is baked by whatever backend is live. Production can lag
GitHub. First-run still opens ElevenLabs / D-ID / fal pages and accepts paste
into Heirloom. Screen watch and phone pairing need the studio API.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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

PROFILE_FEATURES = {
    "lite": ("stt",),
    "full": ("stt", "tts", "twin"),
    "max": ("stt", "tts", "twin", "vision"),
}

_SERVICES = (
    {
        "id": "elevenlabs",
        "label": "ElevenLabs",
        "powers": "Cloned voice so the twin sounds like you.",
        "signup_url": "https://elevenlabs.io/app/sign-up",
        "dashboard_url": "https://elevenlabs.io/app/settings/api-keys",
        "save_path": "/voice-clone/api-key",
        "verify_service": "elevenlabs",
        "placeholder": "sk_…",
        "email_query_param": "email",
        "key_where": "Settings → API Keys. Click Create Key.",
        "key_what": "Copy the secret that starts with sk_.",
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
        "email_query_param": "email",
        "key_where": "Account settings → API. Create or copy the key.",
        "key_what": "Paste the key, or email:secret if they show both.",
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
        "email_query_param": "email",
        "key_where": "Dashboard → Keys. Create a key.",
        "key_what": "Copy it as key_id:key_secret.",
        "create_account_bullets": (
            "Click Sign up on fal.ai.",
            "If the email box is empty, paste (Ctrl+V). Heirloom copied it.",
            "Click I'm not a robot, then submit their form.",
        ),
    },
)


def inbox_for_email(email: str = "") -> dict:
    clean = (email or "").strip().lower()
    domain = clean.split("@")[-1] if "@" in clean else ""
    label, url = INBOX_DOMAINS.get(domain, ("your email inbox", None))
    return {"email": clean, "domain": domain, "label": label, "url": url}


def _signup_url(url: str, email: str, param: str | None) -> str:
    if not email or not param:
        return url
    parts = urlparse(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q.setdefault(param, email)
    return urlunparse(parts._replace(query=urlencode(q)))


def _steps(spec: dict, email: str) -> list[dict]:
    clean = (email or "").strip().lower()
    inbox = inbox_for_email(clean)
    signup = _signup_url(spec["signup_url"], clean, spec.get("email_query_param"))
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
            "bullets": list(spec.get("create_account_bullets") or ()),
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


def local_handoffs(email: str = "") -> list[dict]:
    """Coach queue that does not need GET /api/studio/first-run."""
    out: list[dict] = []
    for spec in _SERVICES:
        out.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "powers": spec["powers"],
                "signup_url": spec["signup_url"],
                "dashboard_url": spec["dashboard_url"],
                "save_path": spec["save_path"],
                "verify_service": spec["verify_service"],
                "placeholder": spec["placeholder"],
                "coach_steps": _steps(spec, email),
            }
        )
    return out


def provision_features(profile_id: str) -> list[str]:
    return list(PROFILE_FEATURES.get(profile_id) or PROFILE_FEATURES["full"])
