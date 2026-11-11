"""Setup Center, restore fence, secrets, and guided pages."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from owner_privacy import json_hides_secret
from setup_center import (
    LINUX_LIVE_ROOT,
    CloudModelDeferred,
    FileSecretStore,
    RestoreRefused,
    SecretStore,
    accept_secret,
    apply_restore,
    checklist,
    flow_by_id,
    flows,
    inventory_backup,
    plan_restore,
    repair_plan,
)


SECRET = "hf_live_token_should_never_appear_in_reports"


def test_guides_skip_hosted_chat_keys():
    ids = {row["id"] for row in flows()}
    assert "huggingface" in ids
    assert "home_assistant" in ids
    assert "resend" in ids
    assert "hue" in ids
    assert "ollama" in ids
    for banned in ("openai", "anthropic", "gemini", "elevenlabs", "claude"):
        assert banned not in ids
    assert flow_by_id("huggingface")["url"].endswith("/settings/tokens")
    assert flow_by_id("dns")["url"] == ""


def test_cloud_model_keys_are_refused():
    with pytest.raises(CloudModelDeferred):
        accept_secret("openai", "sk-live-key-value")
    with pytest.raises(CloudModelDeferred):
        accept_secret("elevenlabs", "el-secret-key")


def test_huggingface_token_is_masked_and_not_logged():
    result = accept_secret("huggingface", SECRET)
    assert result["ok"] is True
    assert result["log"] == "[redacted]"
    assert json_hides_secret(result, SECRET)
    bad = accept_secret("huggingface", "not-a-hf-token")
    assert bad["ok"] is False
    assert json_hides_secret(bad, "not-a-hf-token")


def test_home_assistant_token_must_stay_on_the_lan():
    refused = accept_secret("home_assistant", "ha_token_value_1234", base_url="https://example.com")
    assert refused["ok"] is False
    assert json_hides_secret(refused, "ha_token_value_1234")
    ok = accept_secret(
        "home_assistant",
        "ha_token_value_1234",
        base_url="http://192.168.1.20:8123",
    )
    assert ok["ok"] is True
    store = SecretStore()
    store.put("owner", "home_assistant", "ha_token_value_1234")
    assert json_hides_secret(store.public_view("owner"), "ha_token_value_1234")


def test_file_store_public_copy_hides_the_key(tmp_path: Path):
    store = FileSecretStore(tmp_path)
    store.put("owner", "huggingface", SECRET)
    public = json.loads((tmp_path / "public.json").read_text(encoding="utf-8"))
    assert json_hides_secret(public, SECRET)
    assert SECRET in (tmp_path / "secrets.json").read_text(encoding="utf-8")


def test_checklist_and_repair_stay_local():
    steps = {row["id"]: row for row in checklist({"free_bytes": 0, "ollama_ready": False})}
    assert steps["mind"]["status"] == "needs_you"
    assert "hosted" in steps["mind"]["detail"]
    assert steps["accounts"]["status"] == "optional"
    assert steps["writing"]["status"] == "ready"
    titles = [row["title"] for row in repair_plan({"whisper_ready": False, "ollama_ready": True, "companion_paired": True, "voice_ready": True})]
    assert titles == ["Download hearing again"]


def _backup(root: Path) -> None:
    heirloom = root / "heirloom"
    (heirloom / "vault").mkdir(parents=True)
    (heirloom / "vault" / "memory.txt").write_text("private memory about the oak tree", encoding="utf-8")
    (heirloom / "owner").mkdir()
    (heirloom / "owner" / "odysseus.token").write_text(SECRET, encoding="utf-8")
    (heirloom / "observer").mkdir()
    (heirloom / "observer" / "notes.jsonl").write_text('{"text":"watched"}\n', encoding="utf-8")
    (heirloom / "presence").mkdir()
    (heirloom / "presence" / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (heirloom / "lab").mkdir()
    (heirloom / "lab" / "turn.jsonl").write_text("{}\n", encoding="utf-8")
    (heirloom / "backups").mkdir()
    (heirloom / "backups" / "mongo.archive").write_bytes(b"mongodump")
    (heirloom / "backups" / "readme.txt").write_text("skip me", encoding="utf-8")
    (heirloom / "ollama").mkdir()
    (heirloom / "ollama" / "blob.bin").write_bytes(b"weights")
    (heirloom / "box.env").write_text("HEIRLOOM_BOX=1\n", encoding="utf-8")
    (root / "odysseus").mkdir()
    (root / "odysseus" / "app.json").write_text('{"name":"odysseus"}', encoding="utf-8")
    (root / "git-preserve").mkdir()
    (root / "git-preserve" / "hotfix.py").write_text("print('uncommitted')\n", encoding="utf-8")


def test_inventory_lists_slots_without_reading_secrets(tmp_path: Path):
    _backup(tmp_path)
    catalog = inventory_backup(tmp_path)
    assert json_hides_secret(catalog, SECRET)
    assert "private memory about the oak tree" not in json.dumps(catalog)
    assert catalog["contents_loaded"] is False
    assert catalog["hotfix"]["present"] is True
    assert catalog["hotfix"]["applied_to_git"] is False
    paths = {row["path"] for row in catalog["files"]}
    assert "heirloom/owner/odysseus.token" in paths
    assert "heirloom/backups/mongo.archive" in paths
    assert "git-preserve/hotfix.py" in paths
    assert "odysseus/app.json" in paths
    assert "heirloom/ollama/blob.bin" not in paths
    assert "heirloom/backups/readme.txt" not in paths
    token = next(row for row in catalog["files"] if row["path"].endswith("odysseus.token"))
    assert token["secret"] is True


def test_restore_copies_and_leaves_the_source_alone(tmp_path: Path):
    source = tmp_path / "backup"
    dest = tmp_path / "new-pc"
    source.mkdir()
    _backup(source)
    token = source / "heirloom" / "owner" / "odysseus.token"
    before = token.read_bytes()
    plan = plan_restore(source, dest, confirm=True)
    assert plan["refused"] is None
    assert plan["deletes"] == []
    result = apply_restore(plan)
    assert result["hotfix_applied_to_git"] is False
    assert result["deleted"] == []
    assert token.read_bytes() == before
    assert (dest / "vault" / "memory.txt").read_text(encoding="utf-8").startswith("private memory")
    assert (dest / "owner" / "odysseus.token").read_text(encoding="utf-8") == SECRET
    assert (dest / "backups" / "mongo.archive").read_bytes() == b"mongodump"
    assert (dest / "odysseus" / "app.json").is_file()
    assert (dest / "review" / "git-preserve" / "hotfix.py").read_text(encoding="utf-8").startswith("print")
    assert not (dest / "ollama").exists()
    kept = dest / "owner" / "odysseus.token"
    kept.write_text("already here", encoding="utf-8")
    again = apply_restore(plan_restore(source, dest, confirm=True))
    assert kept.read_text(encoding="utf-8") == "already here"
    assert any(row["status"] == "left_in_place" for row in again["written"])


def test_restore_refuses_the_live_linux_box(tmp_path: Path):
    source = tmp_path / "backup"
    source.mkdir()
    _backup(source)
    live = Path(LINUX_LIVE_ROOT) / "imported"
    plan = plan_restore(source, live, confirm=True, new_machine=True, box_mode=True)
    assert plan["refused"]
    assert "live Linux" in plan["refused"]
    assert plan["copies"] == []
    with pytest.raises(RestoreRefused):
        apply_restore(plan)
    assert not Path(LINUX_LIVE_ROOT).exists()


def test_restore_on_a_new_machine_can_use_its_own_data_root(tmp_path: Path):
    source = tmp_path / "backup"
    dest = tmp_path / "HeirloomVault"
    source.mkdir()
    _backup(source)
    blocked = plan_restore(source, dest, box_mode=True, data_root=dest, new_machine=False, confirm=True)
    assert "new PC" in (blocked["refused"] or "")
    allowed = plan_restore(source, dest, box_mode=True, data_root=dest, new_machine=True, confirm=False)
    assert allowed["refused"] is None
    with pytest.raises(RestoreRefused):
        apply_restore(allowed)
    allowed["confirm"] = True
    apply_restore(allowed)
    assert (dest / "vault" / "memory.txt").is_file()


def test_restore_refuses_to_write_inside_the_backup(tmp_path: Path):
    source = tmp_path / "backup"
    source.mkdir()
    _backup(source)
    plan = plan_restore(source, source / "nested", confirm=True)
    assert plan["refused"]
    assert plan["copies"] == []
