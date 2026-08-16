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


async def send_desktop_sign_in_email(*, to: str, code: str) -> dict:
    """Sign-in slip for Unbound Keyboard / the Heirloom app. Paste in the app — not a password."""
    inner = f"""
<p style="font-family:Georgia,serif;font-size:22px;font-weight:300;line-height:1.35;margin:0 0 14px 0;color:{_TEXT_PRIMARY};">
  Your sign-in slip
</p>
<p style="font-family:Georgia,serif;font-size:17px;line-height:1.55;margin:0 0 20px 0;color:{_TEXT_SECONDARY};">
  Open Unbound Keyboard on your computer. Paste this slip into the sign-in box. This is a Heirloom note &mdash; not a Google, Microsoft, or Windows password. We never ask for those.
</p>
<p style="font-family:'Courier New',monospace;font-size:16px;letter-spacing:0.04em;line-height:1.5;margin:0 0 22px 0;padding:14px 16px;background:{_BG};border:1px solid {_BORDER};color:{_TEXT_PRIMARY};word-break:break-all;">
  {code}
</p>
<p style="font-family:Arial,sans-serif;font-size:13px;line-height:1.55;margin:0;color:#7a6f5e;">
  It works for about an hour. If it expires, tap Send a sign-in note again.
</p>
"""
    return await _send(
        to=to,
        subject="Your Unbound Keyboard sign-in slip",
        html=_wrap(inner, preheader="Paste this slip into Unbound Keyboard on your computer."),
        text=(
            "Open Unbound Keyboard on your computer and paste this sign-in slip:\n\n"
            f"{code}\n\n"
            "This is a Heirloom note — not a Google, Microsoft, or Windows password.\n"
            "It works for about an hour."
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


async def send_letter_email(
    *,
    to: str,
    recipient_name: str,
    owner_name: str,
    title: str,
    body: str,
) -> dict:
    """A sealed letter reaching its delivery date — the message itself, enclosed."""
    greeting = f"Dear {recipient_name.split()[0]}," if recipient_name else "Dear friend,"
    # Preserve the writer's line breaks in HTML.
    body_html = (body or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    inner = f"""
<p style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:0.16em;text-transform:uppercase;color:#7a6f5e;margin:0 0 6px 0;">a sealed letter, now opened</p>
<p style="font-family:Georgia,serif;font-size:24px;font-weight:300;line-height:1.3;margin:0 0 18px 0;color:{_TEXT_PRIMARY};">
  {title}
</p>
<p style="font-family:Georgia,serif;font-size:16px;line-height:1.4;margin:0 0 14px 0;color:{_TEXT_SECONDARY};">
  {greeting}
</p>
<div style="font-family:Georgia,serif;font-size:17px;line-height:1.65;margin:0 0 22px 0;color:{_TEXT_PRIMARY};">
  {body_html}
</div>
<p style="font-family:Arial,sans-serif;font-size:13px;line-height:1.55;margin:22px 0 0 0;color:#7a6f5e;border-top:1px solid {_BORDER};padding-top:18px;">
  {owner_name or "Someone who loved you"} wrote this for you and asked Heirloom to deliver it today.
</p>
"""
    return await _send(
        to=to,
        subject=f"{owner_name or 'Someone who loved you'} left you a letter: {title}",
        html=_wrap(inner, preheader=f"A sealed letter from {owner_name or 'someone who loved you'} has reached its day."),
        text=(
            f"{title}\n\n{greeting}\n\n{body}\n\n"
            f"— {owner_name or 'Someone who loved you'} asked Heirloom to deliver this to you today."
        ),
    )



async def send_budget_alert_email(
    *,
    to: str,
    owner_name: str,
    provider: str,
    tier: str,  # "80" or "100"
    spent_usd: float,
    cap_usd: float,
) -> dict:
    """One-shot budget warning to the archive owner.

    Fires when a routed LLM provider crosses 80% (soft warning) or 100%
    (auto-fallback engaged) of its monthly cap. Non-blocking — the router
    keeps working even if delivery fails.
    """
    percent = int(round(100 * (spent_usd / cap_usd))) if cap_usd else 0
    if tier == "100":
        headline = f"You've hit your monthly cap on {provider}"
        sub = "Your twin has automatically routed to the next cheapest provider so nothing breaks."
        color = "#c47016"
    else:
        headline = f"You're 80% of the way to your {provider} budget"
        sub = "Heads up so nothing surprises you at the end of the month."
        color = _ACCENT
    inner = f"""
<p style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:0.16em;text-transform:uppercase;color:#7a6f5e;margin:0 0 6px 0;">budget · {provider}</p>
<p style="font-family:Georgia,serif;font-size:24px;font-weight:300;line-height:1.3;margin:0 0 12px 0;color:{_TEXT_PRIMARY};">{headline}</p>
<p style="font-family:Georgia,serif;font-size:15px;line-height:1.55;margin:0 0 20px 0;color:{_TEXT_SECONDARY};">
  {sub}
</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="border:1px solid {_BORDER};border-radius:6px;width:100%;margin:0 0 18px 0;">
  <tr><td style="padding:12px 16px;color:{_TEXT_SECONDARY};font-family:Arial,sans-serif;font-size:13px;">Spent this month</td>
      <td style="padding:12px 16px;text-align:right;color:{color};font-family:'Courier New',monospace;font-size:14px;">${spent_usd:.4f}</td></tr>
  <tr><td style="padding:12px 16px;border-top:1px solid {_BORDER};color:{_TEXT_SECONDARY};font-family:Arial,sans-serif;font-size:13px;">Monthly cap</td>
      <td style="padding:12px 16px;border-top:1px solid {_BORDER};text-align:right;color:{_TEXT_PRIMARY};font-family:'Courier New',monospace;font-size:14px;">${cap_usd:.2f}</td></tr>
  <tr><td style="padding:12px 16px;border-top:1px solid {_BORDER};color:{_TEXT_SECONDARY};font-family:Arial,sans-serif;font-size:13px;">Utilisation</td>
      <td style="padding:12px 16px;border-top:1px solid {_BORDER};text-align:right;color:{color};font-family:'Courier New',monospace;font-size:14px;">{percent}%</td></tr>
</table>
<p style="font-family:Arial,sans-serif;font-size:13px;line-height:1.6;margin:0 0 6px 0;color:{_TEXT_SECONDARY};">
  Manage this in your <a href="{os.environ.get('PUBLIC_BACKEND_URL','').rstrip('/')}/routing" style="color:{_ACCENT};text-decoration:none;">AI Router</a> — raise the cap, switch the task to a cheaper provider, or disable the alert entirely.
</p>
"""
    subject = (
        f"Heirloom · {provider} hit 100% of its monthly cap"
        if tier == "100"
        else f"Heirloom · {provider} is at 80% of its monthly cap"
    )
    return await _send(
        to=to,
        subject=subject,
        html=_wrap(inner, preheader=f"{provider} usage at {percent}% of your monthly cap."),
        text=(
            f"{headline}\n\n{sub}\n\n"
            f"Spent this month: ${spent_usd:.4f} of ${cap_usd:.2f} ({percent}%)\n\n"
            "Manage this at /routing in your Heirloom app."
        ),
    )


async def send_provider_rotation_email(
    *, to: str, owner_name: str, provider: str, error: str,
) -> dict:
    """Alert the archive owner that a BYOK provider just flipped green → red.

    Fires exactly once per red episode (reset when the provider goes green
    again). Non-blocking — the health loop keeps running regardless.
    """
    inner = f"""
<p style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:0.16em;text-transform:uppercase;color:#7a6f5e;margin:0 0 6px 0;">provider · {provider}</p>
<p style="font-family:Georgia,serif;font-size:24px;font-weight:300;line-height:1.3;margin:0 0 12px 0;color:{_TEXT_PRIMARY};">Your {provider} key just stopped working</p>
<p style="font-family:Georgia,serif;font-size:15px;line-height:1.55;margin:0 0 20px 0;color:{_TEXT_SECONDARY};">
  The hourly health check found {provider} answering with an error — your twin will fall back to the next provider in your chain, but if this key was your primary you'll want to fix it before too many calls miss.
</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="border:1px solid {_BORDER};border-radius:6px;width:100%;margin:0 0 18px 0;">
  <tr><td style="padding:12px 16px;color:{_TEXT_SECONDARY};font-family:Arial,sans-serif;font-size:13px;">What went wrong</td>
      <td style="padding:12px 16px;text-align:right;color:{_TEXT_PRIMARY};font-family:'Courier New',monospace;font-size:12px;word-break:break-word;">{error[:120]}</td></tr>
</table>
<p style="font-family:Arial,sans-serif;font-size:13px;line-height:1.6;margin:0 0 6px 0;color:{_TEXT_SECONDARY};">
  Fix this in your <a href="{os.environ.get('PUBLIC_BACKEND_URL','').rstrip('/')}/routing" style="color:{_ACCENT};text-decoration:none;">AI Router</a> — paste a new key, hit Verify, and the alert will reset itself the next time we see a green probe.
</p>
"""
    return await _send(
        to=to,
        subject=f"Heirloom · {provider} key just broke",
        html=_wrap(inner, preheader=f"{provider} is failing health checks. Fix at /routing."),
        text=(
            f"Your {provider} key just stopped working.\n\n"
            f"Error: {error[:180]}\n\n"
            "Fix this at /routing in your Heirloom app."
        ),
    )

