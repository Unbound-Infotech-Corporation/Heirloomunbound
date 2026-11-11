"""BYO API keys are sealed at rest and stay out of logs."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from byo_secrets import (
    BYO_FIELDS,
    ByoKeyMissing,
    is_sealed,
    migrate_users,
    plan_seal,
    preview_key,
    public_log,
    read_key,
    scrub,
    store_key,
)
from setup_center import FileSecretStore


SECRET = "sk_live_BYO_should_not_leak_99"
ENV = {"HEIRLOOM_BYO_KEY": "test-byo-key-material-not-a-real-secret"}


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for document in self._docs:
            yield document


class _Users:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = [dict(row) for row in docs]

    def find(self, _query, _projection=None):
        return _Cursor(self.docs)

    async def update_one(self, filt, update):
        for document in self.docs:
            if document.get("_id") == filt.get("_id"):
                document.update(update.get("$set") or {})


def test_store_round_trip_hides_plaintext():
    sealed = store_key(SECRET, ENV)
    assert is_sealed(sealed)
    assert SECRET not in sealed
    assert read_key(sealed, ENV) == SECRET
    assert store_key(sealed, ENV) == sealed


def test_missing_key_does_not_store_or_wipe_plaintext(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_BYO_KEY", raising=False)
    with pytest.raises(ByoKeyMissing):
        store_key(SECRET, {})
    status, changes = plan_seal({"elevenlabs_api_key": SECRET, "name": "Ada"}, {})
    assert status == "no-key"
    assert changes == {}
    assert SECRET not in json.dumps(changes)


def test_plan_seals_known_fields_once():
    document = {
        "elevenlabs_api_key": SECRET,
        "d_id_api_key": "did-live-key-abcdefghij",
        "fal_api_key": "",
        "openai_api_key": "sk-openai-live-value-0001",
        "resend_api_key": "re_live_resend_value_0001",
        "email": "ada@example.com",
    }
    status, changes = plan_seal(document, ENV)
    assert status == "seal"
    assert set(changes) == {
        "elevenlabs_api_key",
        "d_id_api_key",
        "openai_api_key",
        "resend_api_key",
    }
    blob = json.dumps(changes)
    assert SECRET not in blob
    assert "did-live-key-abcdefghij" not in blob
    assert "sk-openai-live-value-0001" not in blob
    assert "re_live_resend_value_0001" not in blob
    assert "ada@example.com" not in changes.values()
    again_status, again = plan_seal({**document, **changes}, ENV)
    assert again_status == "unchanged"
    assert again == {}
    assert "openai_api_key" in BYO_FIELDS
    assert "resend_api_key" in BYO_FIELDS


def test_preview_uses_plaintext_not_the_token():
    sealed = store_key("test-key-1234567890", ENV)
    assert preview_key(sealed, ENV) == "test-k…7890"
    assert "enc:v1" not in preview_key(sealed, ENV)
    assert preview_key(sealed, {}) == ""


def test_logs_and_errors_drop_the_key():
    line = public_log("saved", user_id="u1", elevenlabs_api_key=SECRET)
    assert SECRET not in line
    assert "user_id=u1" in line
    assert "[redacted]" in line
    noisy = f"ElevenLabs error: invalid {SECRET} for this account"
    assert SECRET not in scrub(noisy, SECRET)


def test_migration_seals_in_place_and_is_idempotent():
    users = _Users([
        {"_id": "a", "elevenlabs_api_key": SECRET, "email": "ada@example.com"},
        {"_id": "b", "fal_api_key": "fal-live-key-zzzzzzzz"},
        {"_id": "c", "name": "no keys"},
    ])

    async def _run():
        return await migrate_users(users, ENV)

    first = asyncio.run(_run())
    assert first == {"ok": True, "updated": 2}
    assert users.docs[0]["email"] == "ada@example.com"
    assert SECRET not in users.docs[0]["elevenlabs_api_key"]
    assert read_key(users.docs[0]["elevenlabs_api_key"], ENV) == SECRET
    assert read_key(users.docs[1]["fal_api_key"], ENV) == "fal-live-key-zzzzzzzz"
    sealed_a = users.docs[0]["elevenlabs_api_key"]

    async def _again():
        return await migrate_users(users, ENV)

    second = asyncio.run(_again())
    assert second == {"ok": True, "updated": 0}
    assert users.docs[0]["elevenlabs_api_key"] == sealed_a


def test_migration_without_a_key_leaves_plaintext():
    users = _Users([{"_id": "a", "d_id_api_key": SECRET}])

    async def _run():
        return await migrate_users(users, {})

    result = asyncio.run(_run())
    assert result["ok"] is False
    assert result["updated"] == 0
    assert users.docs[0]["d_id_api_key"] == SECRET
    assert SECRET not in json.dumps({k: v for k, v in result.items() if k != "reason"})


def test_file_store_seals_and_reloads(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_BYO_KEY", ENV["HEIRLOOM_BYO_KEY"])
    store = FileSecretStore(tmp_path)
    store.put("owner", "huggingface", SECRET)
    raw = (tmp_path / "secrets.json").read_text(encoding="utf-8")
    public = (tmp_path / "public.json").read_text(encoding="utf-8")
    assert SECRET not in raw
    assert SECRET not in public
    assert "enc:v1:" in raw
    loaded = FileSecretStore(tmp_path)
    loaded.load()
    assert loaded.get("owner", "huggingface") == SECRET
    first_sealed = json.loads(raw)["owner"]["huggingface"]
    loaded.load()
    second = json.loads((tmp_path / "secrets.json").read_text(encoding="utf-8"))
    assert second["owner"]["huggingface"] == first_sealed


def test_file_store_migrates_existing_plaintext(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_BYO_KEY", ENV["HEIRLOOM_BYO_KEY"])
    (tmp_path / "secrets.json").write_text(
        json.dumps({"owner": {"huggingface": SECRET}}),
        encoding="utf-8",
    )
    store = FileSecretStore(tmp_path)
    store.load()
    raw = (tmp_path / "secrets.json").read_text(encoding="utf-8")
    assert SECRET not in raw
    assert store.get("owner", "huggingface") == SECRET


def test_file_store_load_keeps_plaintext_when_the_sealer_is_missing(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("HEIRLOOM_BYO_KEY", raising=False)
    original = json.dumps({
        "owner": {"huggingface": SECRET},
        "other": {"home_assistant": "ha_token_value_1234"},
    })
    (tmp_path / "secrets.json").write_text(original, encoding="utf-8")
    store = FileSecretStore(tmp_path)
    store.load()
    assert store.get("owner", "huggingface") == SECRET
    assert store.get("other", "home_assistant") == "ha_token_value_1234"
    assert (tmp_path / "secrets.json").read_text(encoding="utf-8") == original
    public = (tmp_path / "public.json").read_text(encoding="utf-8")
    assert SECRET not in public
    assert "ha_token_value_1234" not in public


def test_file_store_load_continues_past_an_unreadable_sealed_value(tmp_path: Path, monkeypatch):
    sealed = store_key(SECRET, ENV)
    monkeypatch.delenv("HEIRLOOM_BYO_KEY", raising=False)
    (tmp_path / "secrets.json").write_text(
        json.dumps({"owner": {"huggingface": sealed, "home_assistant": "ha_token_value_1234"}}),
        encoding="utf-8",
    )
    store = FileSecretStore(tmp_path)
    store.load()
    assert store.get("owner", "huggingface") == ""
    assert store.get("owner", "home_assistant") == "ha_token_value_1234"
    raw = (tmp_path / "secrets.json").read_text(encoding="utf-8")
    assert SECRET not in raw
    assert "ha_token_value_1234" in raw


def test_file_store_refuses_a_new_key_when_the_sealer_is_missing(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("HEIRLOOM_BYO_KEY", raising=False)
    store = FileSecretStore(tmp_path)
    with pytest.raises(ByoKeyMissing):
        store.put("owner", "huggingface", SECRET)
    assert not (tmp_path / "secrets.json").exists()
