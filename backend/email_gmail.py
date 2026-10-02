"""Gmail OAuth provider — not enabled.

IMAP with an app password is the v1 mailbox. This module is the seam a later
change would fill in. It does not start an OAuth flow, store a Google client
secret, or call Google.

What the owner would configure before this can be turned on:

- A Google Cloud OAuth client (desktop or web) for this Heirloom install.
- ``GOOGLE_OAUTH_CLIENT_ID`` and ``GOOGLE_OAUTH_CLIENT_SECRET`` on the server.
- Consent scopes ``https://www.googleapis.com/auth/gmail.readonly`` and
  ``https://www.googleapis.com/auth/gmail.compose`` (send stays behind an
  Heirloom Approval; the token is not a reason to skip that).
- A redirect URL owned by this server, same shape as the Spotify connector.

Until that exists, ``enabled`` is false and every method refuses.
"""
from __future__ import annotations

from typing import Any

GMAIL_NOT_ENABLED = (
    "Gmail OAuth is not enabled in this build. "
    "To add it later, register an OAuth client in Google Cloud, set "
    "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET, and request "
    "gmail.readonly plus gmail.compose. Heirloom does not start that flow yet. "
    "Use IMAP with an app password until then."
)


class ProviderDisabled(RuntimeError):
    """The provider is a documented seam, not a live connection."""


class GmailOAuthProvider:
    provider_id = "gmail"
    enabled = False

    def list_threads(self, *, limit: int = 10) -> list[Any]:
        raise ProviderDisabled(GMAIL_NOT_ENABLED)

    def get_thread(self, thread_id: str) -> list[Any]:
        raise ProviderDisabled(GMAIL_NOT_ENABLED)

    def create_draft(self, *, to: str, subject: str, body: str, thread_id: str = "") -> Any:
        raise ProviderDisabled(GMAIL_NOT_ENABLED)

    def send_message(self, *, to: str, subject: str, body: str, approval_id: str) -> dict[str, Any]:
        raise ProviderDisabled(GMAIL_NOT_ENABLED)

    def test_connection(self) -> dict[str, Any]:
        raise ProviderDisabled(GMAIL_NOT_ENABLED)
