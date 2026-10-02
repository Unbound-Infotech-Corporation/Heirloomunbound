"""Connector records for one owner. Secrets stay encrypted, off this view."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from cryptography.fernet import Fernet

from assignments import assignments_allowed
from connector_secrets import open_secret, seal_secret
from email_gmail import GMAIL_NOT_ENABLED
from email_imap import ImapConfig, ImapSmtpProvider, parse_imap_config
from email_intent import NOT_CONNECTED_REPLY

IMAP_SCOPES = ["mail.read", "mail.draft", "mail.send"]

PROVIDERS = (
    {
        "id": "imap",
        "label": "IMAP / SMTP",
        "enabled": True,
        "note": "App password. TLS required. Works with any mailbox that speaks IMAP and SMTP.",
    },
    {
        "id": "gmail",
        "label": "Gmail",
        "enabled": False,
        "note": GMAIL_NOT_ENABLED,
    },
)


def connectors_allowed(*, audience: Optional[str], heir_surface: bool = False) -> bool:
    """Same owner fence as assignments. Heirs never see connectors."""
    return assignments_allowed(audience=audience, heir_surface=heir_surface)


def new_connector_id() -> str:
    return f"con_{uuid.uuid4().hex[:12]}"


def public_connector(doc: dict[str, Any]) -> dict[str, Any]:
    """Safe for the owner UI and the assignment log. No secret, no body."""
    return {
        "connector_id": doc.get("connector_id"),
        "provider": doc.get("provider"),
        "status": doc.get("status"),
        "scopes": list(doc.get("scopes") or []),
        "account": doc.get("account") or "",
        "host": doc.get("host") or "",
        "port": doc.get("port"),
        "security": doc.get("security") or "",
        "smtp_host": doc.get("smtp_host") or "",
        "smtp_port": doc.get("smtp_port"),
        "smtp_security": doc.get("smtp_security") or "",
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def status_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    public = [public_connector(row) for row in rows if row.get("status") != "disconnected"]
    connected = {row.get("provider") for row in public if row.get("status") == "connected"}
    providers = []
    for spec in PROVIDERS:
        providers.append({
            **spec,
            "connected": spec["id"] in connected,
        })
    return {
        "connectors": public,
        "providers": providers,
        "not_connected": NOT_CONNECTED_REPLY,
    }


def seal_imap_connector(
    *,
    user_id: str,
    config: ImapConfig,
    now: str,
    fernet: Fernet,
    existing: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    prior = existing or {}
    return {
        "connector_id": prior.get("connector_id") or new_connector_id(),
        "user_id": user_id,
        "provider": "imap",
        "status": "connected",
        "scopes": list(IMAP_SCOPES),
        "account": config.username,
        "host": config.host,
        "port": config.port,
        "security": config.security,
        "smtp_host": config.smtp_host,
        "smtp_port": config.smtp_port,
        "smtp_security": config.smtp_security,
        "secret": seal_secret(config.password, fernet),
        "created_at": prior.get("created_at") or now,
        "updated_at": now,
    }


def provider_from_document(
    doc: dict[str, Any],
    *,
    fernet: Fernet,
    imap_factory: Any = None,
    smtp_factory: Any = None,
) -> ImapSmtpProvider:
    if doc.get("provider") != "imap" or doc.get("status") != "connected":
        raise ValueError("No connected IMAP mailbox")
    password = open_secret(str(doc.get("secret") or ""), fernet)
    config = parse_imap_config({
        "host": doc.get("host"),
        "port": doc.get("port"),
        "security": doc.get("security"),
        "smtp_host": doc.get("smtp_host"),
        "smtp_port": doc.get("smtp_port"),
        "smtp_security": doc.get("smtp_security"),
        "username": doc.get("account"),
        "app_password": password,
    })
    kwargs: dict[str, Any] = {}
    if imap_factory is not None:
        kwargs["imap_factory"] = imap_factory
    if smtp_factory is not None:
        kwargs["smtp_factory"] = smtp_factory
    return ImapSmtpProvider(config, **kwargs)
