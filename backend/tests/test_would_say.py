"""Local style and factual scores. No cloud judge."""
from __future__ import annotations

import asyncio

from would_say import (
    case_from_style,
    cases_from_messages,
    execute_run,
    local_only_reason,
    parse_judge,
    selectable_conversations,
    style_score,
)


def test_cases_come_from_owner_lines_and_style():
    messages = [
        {"role": "user", "content": "How was the lake?"},
        {"role": "assistant", "content": "We stayed until the light went."},
        {"role": "user", "content": "And then?"},
        {"role": "assistant", "content": "Drove home quiet."},
    ]
    cases = cases_from_messages(messages)
    assert cases[0]["prompt"] == "How was the lake?"
    assert "light went" in cases[0]["reference"]
    assert cases[0]["source"] == "conversation"
    mixed = selectable_conversations([
        {"conversation_id": "heir_1", "messages": [{"role": "user", "content": "secret heir"}]},
        {"conversation_id": "twin_1", "audience": "owner", "messages": messages},
        {"conversation_id": "phone_1", "audience": "caller", "messages": [{"role": "user", "content": "caller line"}]},
    ])
    blob = " ".join(row.get("content") or "" for row in mixed)
    assert "secret heir" not in blob
    assert "caller line" not in blob
    assert "How was the lake?" in blob
    style = case_from_style({"humor": "dry", "word_choice": "short words", "sample_count": 3})
    assert style is not None
    assert style["source"] == "style"
    assert "short words" in style["reference"]


def test_style_score_and_judge_parse():
    close = style_score("yeah I reckon we head out early", "yeah I reckon we leave early")
    far = style_score("quarterly revenue rose", "yeah I reckon we leave early")
    assert close > far
    score, note = parse_judge('{"score": 0.25, "note": "conflicts"}')
    assert score == 0.25
    assert note == "conflicts"
    assert parse_judge("not json") == (0.0, "judge did not answer")


def test_run_scores_each_brain_without_a_cloud_call():
    calls = {"complete": [], "judge": []}

    async def complete(prompt: str) -> str:
        calls["complete"].append(prompt)
        return "yeah I reckon we head out early"

    async def judge(prompt, reference, reply):
        calls["judge"].append(reply)
        if "never" in reply:
            return 0.0, "conflicts"
        return 1.0, "matches the reference"

    async def _run():
        return await execute_run(
            [{"case_id": "c1", "prompt": "How was it?", "reference": "yeah I reckon we head out early"}],
            brain="local",
            complete=complete,
            judge=judge,
            profile_text="word_choice: short words",
            model="qwen2.5:14b",
        )

    result = asyncio.run(_run())
    assert result["brain"] == "local"
    assert result["model"] == "qwen2.5:14b"
    assert result["mean_factual"] == 1.0
    assert result["mean_style"] > 0.5
    assert calls["judge"] == ["yeah I reckon we head out early"]
    assert local_only_reason() in {None, "Would-say runs on local Ollama only"}


def test_cloud_provider_is_refused(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_BOX", raising=False)
    monkeypatch.delenv("HEIRLOOM_LLM_PROVIDER", raising=False)
    assert local_only_reason() == "Would-say runs on local Ollama only"
