"""Seal per-user BYO API keys before they sit in Mongo or on disk.

The Fernet key is ``HEIRLOOM_BYO_KEY`` in the environment. It is not written
into the user document, ``secrets.json``, or the repo. Mailbox passwords keep
using ``CONNECTOR_SECRET_KEY`` in ``connector_secrets.py``. These are
different secrets on purpose.

Sealed values start with ``enc:v1:``. A migration can tell them from legacy
plaintext and will not encrypt them twice. When ``HEIRLOOM_BYO_KEY`` is
missing, new keys are refused and existing plaintext is left as it is.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from connector_secrets import SecretKeyMissing, fernet_from_material, open_secret, seal_secret

PREFIX = "enc:v1:"
ENV_NAME = "HEIRLOOM_BYO_KEY"
MISSING_DETAIL = "Set HEIRLOOM_BYO_KEY before saving an API key."
UNREADABLE_DETAIL = "Couldn't read the saved API key. Check HEIRLOOM_BYO_KEY."

# Stored on the user document. OpenAI and Resend are not written by a
# per-user route today; they are sealed if a document already has them.
BYO_FIELDS = (
    "elevenlabs_api_key",
    "d_id_api_key",
    "fal_api_key",
    "openai_api_key",
    "resend_api_key",
)


class ByoKeyMissing(Exception):
    """The server has no BYO key, or a sealed value cannot be opened."""


def _env_map(env: Optional[dict[str, str]]) -> dict[str, str]:
    if env is not None:
        return env
    return dict(os.environ)


def fernet_for_byo(env: Optional[dict[str, str]] = None):
    material = (_env_map(env).get(ENV_NAME) or "").strip()
    if not material:
        raise ByoKeyMissing(MISSING_DETAIL)
    try:
        return fernet_from_material(material)
    except SecretKeyMissing as exc:
        raise ByoKeyMissing(MISSING_DETAIL) from exc


def is_sealed(value: str) -> bool:
    return (value or "").startswith(PREFIX)


def store_key(plaintext: str, env: Optional[dict[str, str]] = None) -> str:
    """Return a sealed value. Empty stays empty. Already sealed is unchanged."""
    text = (plaintext or "").strip()
    if not text:
        return ""
    if is_sealed(text):
        return text
    token = seal_secret(text, fernet_for_byo(env))
    return PREFIX + token


def read_key(stored: str, env: Optional[dict[str, str]] = None) -> str:
    """Return the plaintext key. Legacy plaintext is returned until migrated."""
    raw = (stored or "").strip()
    if not raw:
        return ""
    if not is_sealed(raw):
        return raw
    token = raw[len(PREFIX):]
    if not token:
        raise ByoKeyMissing(UNREADABLE_DETAIL)
    try:
        return open_secret(token, fernet_for_byo(env))
    except (ByoKeyMissing, SecretKeyMissing) as exc:
        raise ByoKeyMissing(UNREADABLE_DETAIL) from exc


def preview_key(stored: str, env: Optional[dict[str, str]] = None) -> str:
    """Mask for a settings screen. Never returns the sealed token."""
    try:
        plain = read_key(stored, env)
    except ByoKeyMissing:
        return ""
    if not plain:
        return ""
    if len(plain) < 10:
        return "…"
    return plain[:6] + "…" + plain[-4:]


def plan_seal(document: dict[str, Any], env: Optional[dict[str, str]] = None) -> tuple[str, dict[str, str]]:
    """Decide a user-document update.

    ``no-key`` means ``HEIRLOOM_BYO_KEY`` is unset. The caller must not write.
    ``unchanged`` means every present key is already sealed or empty.
    ``seal`` maps field names to sealed values. Plaintext is not in the map.
    """
    try:
        fernet = fernet_for_byo(env)
    except ByoKeyMissing:
        return "no-key", {}
    changes: dict[str, str] = {}
    for field in BYO_FIELDS:
        value = document.get(field)
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text or is_sealed(text):
            continue
        changes[field] = PREFIX + seal_secret(text, fernet)
    if not changes:
        return "unchanged", {}
    return "seal", changes


def scrub(text: str, *secrets: str) -> str:
    """Remove known key material from a log or error string."""
    out = "" if text is None else str(text)
    for secret in secrets:
        raw = (secret or "").strip()
        if len(raw) >= 8 and raw in out:
            out = out.replace(raw, "[redacted]")
    return out


def _sensitive_name(name: str) -> bool:
    lowered = (name or "").lower()
    return any(fragment in lowered for fragment in ("key", "secret", "token", "password"))


def public_log(event: str, **fields: object) -> str:
    """One log line. Fields whose names look like secrets are not printed."""
    hidden: list[str] = []
    parts = [event]
    for name, value in fields.items():
        text = "" if value is None else str(value)
        if _sensitive_name(name):
            if text:
                hidden.append(text)
            parts.append(f"{name}=[redacted]")
        else:
            parts.append(f"{name}={text}")
    return scrub(" ".join(parts), *hidden)


async def migrate_users(users: Any, env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Encrypt plaintext BYO fields in place.

    The returned dict has counts only. It does not contain key material.
    A missing ``HEIRLOOM_BYO_KEY`` updates nothing.
    """
    sample = plan_seal({}, env)
    if sample[0] == "no-key":
        return {"ok": False, "reason": "HEIRLOOM_BYO_KEY is not set", "updated": 0}
    projection = {"_id": 1, **{name: 1 for name in BYO_FIELDS}}
    updated = 0
    cursor = users.find({}, projection)
    async for document in cursor:
        status, changes = plan_seal(document, env)
        if status != "seal" or not changes:
            continue
        await users.update_one({"_id": document["_id"]}, {"$set": changes})
        updated += 1
    return {"ok": True, "updated": updated}
