"""Encrypt connector secrets before they touch Mongo.

ElevenLabs and the other BYO keys are stored as plain user fields. There is
no shared encrypted store to reuse, so connector app passwords use Fernet.
The key is ``CONNECTOR_SECRET_KEY`` (a Fernet key, or any long passphrase
we hash into one). The password is never written in the clear.
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class SecretKeyMissing(RuntimeError):
    """The server has no key, so it must not store a password."""


def fernet_from_material(material: str) -> Fernet:
    raw = (material or "").strip()
    if not raw:
        raise SecretKeyMissing("Set CONNECTOR_SECRET_KEY before connecting a mailbox.")
    try:
        return Fernet(raw.encode("utf-8"))
    except (ValueError, TypeError):
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def fernet_from_env(env: Optional[dict[str, str]] = None) -> Fernet:
    source = env if env is not None else os.environ
    return fernet_from_material(source.get("CONNECTOR_SECRET_KEY", ""))


def seal_secret(secret: str, fernet: Fernet) -> str:
    token = fernet.encrypt((secret or "").encode("utf-8"))
    return token.decode("utf-8")


def open_secret(token: str, fernet: Fernet) -> str:
    try:
        return fernet.decrypt((token or "").encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise SecretKeyMissing("Couldn't read the saved mailbox secret.") from exc
