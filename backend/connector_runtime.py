"""Live mailbox lookup. Mongo is imported inside the functions."""
from __future__ import annotations

import logging
from typing import Any, Optional

from assignments import InMemoryConnector, normalize_action_kind
from connector_secrets import SecretKeyMissing, fernet_from_env
from connectors import provider_from_document
from email_gmail import GMAIL_NOT_ENABLED, ProviderDisabled
from mail_provider import EmailSendConnector, MailProvider, RefusingConnector

logger = logging.getLogger(__name__)


async def provider_for_user(user_id: str) -> Optional[MailProvider]:
    """Connected IMAP provider, or None. Failures stay quiet and secret-free."""
    try:
        from connector_store import MongoConnectorStore

        doc = await MongoConnectorStore().get_connector(user_id, "imap")
    except Exception:  # noqa: BLE001
        logger.warning("connector lookup failed")
        return None
    if not doc or doc.get("status") != "connected":
        return None
    try:
        return provider_from_document(doc, fernet=fernet_from_env())
    except (SecretKeyMissing, ProviderDisabled, ValueError):
        logger.warning("connector secret unreadable")
        return None


async def connector_for_approval(user_id: str, approval: dict[str, Any]) -> Any:
    """Email sends go through the mailbox. Anything else keeps the in-memory spine."""
    kind = normalize_action_kind(str(approval.get("action_kind") or ""))
    payload = approval.get("payload") or {}
    if kind == "send" and isinstance(payload, dict) and payload.get("channel") == "email":
        provider = await provider_for_user(user_id)
        if provider is None:
            return RefusingConnector()
        return EmailSendConnector(provider)
    return InMemoryConnector()


def gmail_refusal() -> str:
    return GMAIL_NOT_ENABLED
