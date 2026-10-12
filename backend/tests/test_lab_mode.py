"""Lab telemetry is local, owner-only, and does not relax the heir or approval fence."""
from __future__ import annotations

import json

from assignments import effect_needs_approval
from lab_mode import (
    LabStore,
    build_github_issue,
    file_github_issue,
    github_issue_target,
    lab_allowed,
    lab_mode_enabled,
    publish_report,
    record_chat_turn,
    render_report,
)
from owner_rail import owner_mode_allowed


def test_lab_mode_defaults_off(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_LAB_MODE", raising=False)
    assert lab_mode_enabled() is False
    assert lab_allowed(audience="owner") is False


def test_heirs_never_enter_lab_even_when_enabled():
    assert lab_allowed(audience="heir", heir_surface=False, enabled=True) is False
    assert lab_allowed(audience="caller", heir_surface=False, enabled=True) is False
    assert lab_allowed(audience="owner", heir_surface=True, enabled=True) is False
    assert lab_allowed(audience="owner", heir_surface=False, enabled=True) is True
    assert lab_allowed(audience="owner", heir_surface=False, enabled=False) is False
    assert owner_mode_allowed(audience="heir") is False
    assert owner_mode_allowed(audience="owner", heir_surface=True) is False


def test_lab_mode_does_not_relax_approvals(monkeypatch):
    monkeypatch.setenv("HEIRLOOM_LAB_MODE", "1")
    assert lab_mode_enabled() is True
    assert effect_needs_approval("send", clone_autonomy_value="act") is True
    assert effect_needs_approval("post", clone_autonomy_value="act") is True
    assert effect_needs_approval("delete", clone_autonomy_value="ask") is True
    assert effect_needs_approval("spend", clone_autonomy_value="act") is True


def test_telemetry_is_local_and_omits_message_text(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_LAB_MODE", "1")
    store = LabStore(tmp_path)
    turn_id = record_chat_turn(
        route="twin",
        latency_ms=42,
        model="qwen2.5:7b",
        prompt_tokens=8,
        completion_tokens=5,
        approvals_created=1,
        audience="owner",
        user_id="owner-1",
        store=store,
    )
    assert turn_id
    refused = record_chat_turn(
        route="twin",
        audience="heir",
        store=store,
    )
    assert refused is None
    rows = store.read_all()
    assert len(rows) == 1
    row = rows[0]
    assert row["route"] == "twin"
    assert row["latency_ms"] == 42
    assert row["model"] == "qwen2.5:7b"
    assert row["tokens"] == {"prompt": 8, "completion": 5}
    assert row["approvals_created"] == 1
    assert "content" not in row
    assert "reply" not in row
    raw = (tmp_path / "turns.jsonl").read_text(encoding="utf-8")
    assert "mongodb" not in raw.lower()
    stored = store.set_feedback(turn_id, "down", "too vague")
    assert stored["feedback"]["vote"] == "down"
    assert stored["feedback"]["note"] == "too vague"


def test_report_is_markdown_without_transcripts(tmp_path):
    store = LabStore(tmp_path / "lab")
    store.append({
        "turn_id": "lab_a",
        "route": "assist",
        "latency_ms": 10,
        "model": "qwen2.5:3b",
        "tokens": {"prompt": 1, "completion": 1},
        "approvals_created": 0,
        "approvals_approved": 1,
        "approvals_declined": 0,
        "error": None,
        "feedback": {"vote": "up", "note": "did the job"},
    })
    store.append({
        "turn_id": "lab_b",
        "route": "clone",
        "error": "timeout",
        "approvals_declined": 2,
        "feedback": None,
    })
    text = render_report(store.read_all(), day="2026-10-12")
    assert "2026-10-12" in text
    assert "Turns: 2" in text
    assert "assist: 1" in text
    assert "did the job" in text
    assert "timeout" in text
    path = publish_report(store, tmp_path / "reports")["path"]
    assert path.endswith(".md")
    assert "did the job" in open(path, encoding="utf-8").read()


def test_github_issue_stays_off_without_token_and_repo(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("HEIRLOOM_LAB_GITHUB_REPO", raising=False)
    assert github_issue_target() is None
    assert github_issue_target(token="secret", repo="") is None
    assert github_issue_target(token="", repo="acme/heirloom") is None
    assert github_issue_target(token="secret", repo="https://github.com/acme/heirloom") is None


def test_github_issue_is_labeled_lab_report_when_configured(tmp_path):
    captured = {}

    def opener(request, timeout=20):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["auth"] = request.get_header("Authorization")

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"html_url":"https://github.com/acme/heirloom/issues/7"}'

        return _Response()

    store = LabStore(tmp_path / "lab")
    store.append({"turn_id": "lab_c", "route": "twin", "feedback": None})
    result = publish_report(
        store,
        tmp_path / "reports",
        token="tok",
        repo="acme/heirloom",
        opener=opener,
    )
    assert result["github"] == "filed"
    assert captured["url"] == "https://api.github.com/repos/acme/heirloom/issues"
    assert captured["body"]["labels"] == ["lab-report"]
    assert captured["body"]["title"].startswith("Lab report ")
    issue = build_github_issue("hello", day="2026-10-12")
    assert issue["labels"] == ["lab-report"]
    url = file_github_issue("hello", token="tok", repo="acme/heirloom", day="2026-10-12", opener=opener)
    assert url.endswith("/7")
