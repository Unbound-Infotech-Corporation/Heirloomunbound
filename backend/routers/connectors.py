"""Owner-only connectors. Heirs, callers, and the heir surface never reach this."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from connector_secrets import SecretKeyMissing, fernet_from_env
from connectors import (
    connectors_allowed,
    public_connector,
    seal_imap_connector,
    status_payload,
)
from connector_runtime import gmail_refusal
from deps import get_current_user
from email_imap import ImapSmtpProvider, parse_imap_config
from mail_provider import MailAccessError

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner_gate(user: dict) -> None:
    if user.get("account_status") == "refunded":
        raise HTTPException(status_code=403, detail="account_inactive")
    if not connectors_allowed(
        audience=user.get("audience") or "owner",
        heir_surface=bool(user.get("heir_surface")),
    ):
        raise HTTPException(status_code=403, detail="owner_only")


def _store():
    from connector_store import MongoConnectorStore

    return MongoConnectorStore()


class ImapBody(BaseModel):
    provider: str = "imap"
    host: str = ""
    port: int = 993
    security: str = "ssl"
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_security: str = "ssl"
    username: str = ""
    app_password: str = Field("", max_length=256)


class DisconnectBody(BaseModel):
    provider: str = "imap"


def _config_or_400(body: ImapBody):
    try:
        return parse_imap_config(body.model_dump())
    except MailAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_connectors(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    rows = await _store().list_connectors(user["user_id"])
    return {"connectors": [public_connector(row) for row in rows]}


@router.get("/status")
async def connector_status(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    rows = await _store().list_connectors(user["user_id"])
    return status_payload(rows)


@router.post("/test")
async def test_connector(body: ImapBody, user: dict = Depends(get_current_user)):
    """Sign in only. Does not save the password and does not send mail."""
    _owner_gate(user)
    if (body.provider or "imap").strip().lower() == "gmail":
        raise HTTPException(status_code=400, detail=gmail_refusal())
    config = _config_or_400(body)
    try:
        result = ImapSmtpProvider(config).test_connection()
    except MailAccessError as exc:
        return {"ok": False, "detail": str(exc)}
    return {"ok": True, "detail": result.get("detail") or "Signed in. Nothing was sent."}


@router.post("/connect")
async def connect(body: ImapBody, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    provider = (body.provider or "imap").strip().lower()
    if provider == "gmail":
        raise HTTPException(status_code=400, detail=gmail_refusal())
    if provider != "imap":
        raise HTTPException(status_code=400, detail="Unknown connector.")
    config = _config_or_400(body)
    try:
        ImapSmtpProvider(config).test_connection()
    except MailAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        fernet = fernet_from_env()
    except SecretKeyMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    store = _store()
    existing = await store.get_connector(user["user_id"], "imap")
    doc = seal_imap_connector(
        user_id=user["user_id"],
        config=config,
        now=_now(),
        fernet=fernet,
        existing=existing,
    )
    await store.upsert_connector(doc)
    return {"connector": public_connector(doc)}


@router.post("/disconnect")
async def disconnect(body: DisconnectBody, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    provider = (body.provider or "imap").strip().lower()
    if provider == "gmail":
        return {"disconnected": False, "provider": "gmail"}
    removed = await _store().delete_connector(user["user_id"], provider)
    return {"disconnected": removed, "provider": provider}
