"""Resend transactional-email service.

All outgoing email goes through here. We use Resend's sync SDK wrapped in
`asyncio.to_thread` so FastAPI's event loop never blocks on the network.

Two production templates are defined:

  - `send_magic_link_email`: sent immediately after Stripe checkout completes.
    Includes a one-tap login link + a Windows-companion download link.
  - `send_heir_release_email`: sent when an heir is released. Includes the
    public-portal link.

Both templates use inline CSS + table-based layout (the only format that
renders consistently across Gmail, Outlook, Apple Mail, and mobile clients).

Test-mode caveat: when SENDER_EMAIL is `onboarding@resend.dev`, Resend only
delivers to the email address that owns the Resend account. To send to actual
customers, the user must verify a domain on resend.com/domains and update
SENDER_EMAIL in .env.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import resend
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
SENDER_NAME = os.environ.get("SENDER_NAME", "Heirloom")
PUBLIC_FRONTEND_URL = os.environ.get(
    "PUBLIC_FRONTEND_URL",
    os.environ.get("PUBLIC_BACKEND_URL", ""),
).rstrip("/")

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

# ----------------------------- Low-level send -----------------------------

async def _send(to: str, subject: str, html: str, text: Optional[str] = None) -> dict:
    """Fire a single transactional email via Resend.

    Returns the Resend response dict on success. On failure, logs and returns
    {"error": "..."} — callers should NOT block their critical path on this.
    """
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not set — skipping email send to %s", to)
        return {"skipped": True, "reason": "RESEND_API_KEY missing"}

    params = {
        "from": f"{SENDER_NAME} <{SENDER_EMAIL}>",
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if text:
        params["text"] = text
    try:
        result = await asyncio.to_thread(resend.Emails.send, params)
        logger.info("Resend → %s (subject=%r) id=%s", to, subject, result.get("id"))
        return result
    except Exception as exc:  # noqa: BLE001
        logger.error("Resend FAILED for %s (%r): %s", to, subject, exc)
        return {"error": str(exc)}


# ----------------------------- Shared chrome -----------------------------

_BG = "#121110"
_SURFACE = "#1c1a17"
_BORDER = "#2a2723"
_TEXT_PRIMARY = "#f0eadf"
_TEXT_SECONDARY = "#b3a896"
_ACCENT = "#d4a373"
_INVERSE = "#121110"


def _wrap(inner: str, preheader: str = "") -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Heirloom</title></head>
<body style="margin:0;padding:0;background:{_BG};font-family:Georgia,'Times New Roman',serif;color:{_TEXT_PRIMARY};-webkit-font-smoothing:antialiased;">
  <span style="display:none!important;visibility:hidden;opacity:0;color:transparent;height:0;width:0;font-size:1px;line-height:1px;">{preheader}</span>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{_BG};">
    <tr><td align="center" style="padding:40px 20px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:560px;background:{_SURFACE};border:1px solid {_BORDER};">
        <tr><td style="padding:36px 40px 12px 40px;">
          <div style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:{_TEXT_SECONDARY};">a continuation of you</div>
          <div style="font-family:Georgia,serif;font-size:30px;font-weight:300;letter-spacing:-0.5px;color:{_TEXT_PRIMARY};margin-top:6px;">Heirloom</div>
        </td></tr>
        <tr><td style="padding:18px 40px 36px 40px;">{inner}</td></tr>
        <tr><td style="padding:18px 40px 28px 40px;border-top:1px solid {_BORDER};">
          <div style="font-family:'Courier New',monospace;font-size:10px;letter-spacing:0.16em;text-transform:uppercase;color:#7a6f5e;line-height:1.6;">
            a product of unbound infotech &middot; <a href="mailto:support@heirloom.app" style="color:{_ACCENT};text-decoration:none;">support@heirloom.app</a><br>
            you received this because you bought or were named in a Heirloom archive
          </div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _btn(label: str, url: str) -> str:
    return (
        f'<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:24px 0;">'
        f'<tr><td bgcolor="{_ACCENT}" style="border-radius:2px;">'
        f'<a href="{url}" target="_blank" '
        f'style="display:inline-block;padding:14px 26px;font-family:Arial,sans-serif;font-size:14px;font-weight:600;letter-spacing:0.5px;color:{_INVERSE};text-decoration:none;">{label}</a>'
        f"</td></tr></table>"
    )


# ----------------------------- Templates -----------------------------

async def send_magic_link_email(
    *,
    to: str,
    name: str,
    login_url: str,
    download_url: str,
    backend_url: str,
) -> dict:
    """Post-Stripe-checkout welcome + magic-link login email."""
    full_login = f"{PUBLIC_FRONTEND_URL or backend_url}/auth/magic/{login_url.split('/')[-1]}"
    full_download = f"{backend_url}{download_url}"
    greeting = f"Welcome, {name.split()[0]}," if name else "Welcome,"
    inner = f"""
<p style="font-family:Georgia,serif;font-size:22px;font-weight:300;line-height:1.35;margin:0 0 14px 0;color:{_TEXT_PRIMARY};">
  {greeting}
</p>
<p style="font-family:Georgia,serif;font-size:17px;line-height:1.55;margin:0 0 20px 0;color:{_TEXT_SECONDARY};">
  Your Heirloom is ready. Lifetime, paid once, yours forever. This is the link that signs you in &mdash; one tap, no password.
</p>
{_btn("Sign in to Heirloom", full_login)}
<p style="font-family:Arial,sans-serif;font-size:13px;line-height:1.55;margin:0 0 22px 0;color:#7a6f5e;">
  The link works for 24 hours and then quietly expires. If it does, write to <a href="mailto:support@heirloom.app" style="color:{_ACCENT};text-decoration:none;">support@heirloom.app</a> and we&rsquo;ll send another.
</p>
<div style="border-top:1px solid {_BORDER};padding-top:22px;margin-top:8px;">
  <p style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:0.16em;text-transform:uppercase;color:#7a6f5e;margin:0 0 8px 0;">also &middot; the windows companion</p>
  <p style="font-family:Georgia,serif;font-size:15px;line-height:1.55;margin:0 0 14px 0;color:{_TEXT_SECONDARY};">
    Drop this on the PC where you want Heirloom to live. Hidden tray icon, runs at sign-in.
  </p>
  <a href="{full_download}" style="font-family:Arial,sans-serif;font-size:13px;color:{_ACCENT};text-decoration:underline;">Download Windows companion (.zip)</a>
</div>
"""
    return await _send(
        to=to,
        subject="Your Heirloom is ready",
        html=_wrap(inner, preheader="One tap to sign in. Lifetime access enclosed."),
        text=(
            f"{greeting}\n\nYour Heirloom is ready.\n\n"
            f"Sign in (24h link): {full_login}\n\n"
            f"Windows companion download: {full_download}\n\n"
            "Questions: support@heirloom.app"
        ),
    )


async def send_heir_release_email(
    *,
    to: str,
    heir_name: str,
    owner_name: str,
    portal_url: str,
) -> dict:
    """Sent when an heir is released. Public portal link enclosed."""
    greeting = f"Hello {heir_name.split()[0]}," if heir_name else "Hello,"
    inner = f"""
<p style="font-family:Georgia,serif;font-size:22px;font-weight:300;line-height:1.35;margin:0 0 14px 0;color:{_TEXT_PRIMARY};">
  {greeting}
</p>
<p style="font-family:Georgia,serif;font-size:17px;line-height:1.55;margin:0 0 20px 0;color:{_TEXT_SECONDARY};">
  {owner_name or "Someone you love"} chose you as an heir to their Heirloom &mdash; a private archive of their voice, memories, and the things they wanted you to keep. They have released that archive to you today.
</p>
<p style="font-family:Georgia,serif;font-size:17px;line-height:1.55;margin:0 0 6px 0;color:{_TEXT_SECONDARY};">
  Whenever you are ready, you can read what they left.
</p>
{_btn("Open the archive", portal_url)}
<p style="font-family:Arial,sans-serif;font-size:13px;line-height:1.55;margin:0 0 6px 0;color:#7a6f5e;">
  This link is yours alone. Keep it private. You can come back to it whenever you like.
</p>
"""
    return await _send(
        to=to,
        subject=f"{owner_name or 'Someone you love'} left this for you",
        html=_wrap(inner, preheader=f"{owner_name or 'A Heirloom owner'} released their archive to you."),
        text=(
            f"{greeting}\n\n"
            f"{owner_name or 'Someone you love'} released their Heirloom archive to you today.\n\n"
            f"Open it whenever you are ready: {portal_url}\n\n"
            "This link is yours alone."
        ),
    )
