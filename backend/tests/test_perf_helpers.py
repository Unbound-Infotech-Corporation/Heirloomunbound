"""Unit tests for performance-oriented helpers (no live HTTP / LLM required)."""
from __future__ import annotations

import abilities as ab
from routers.twin import _entry_excerpt, _history_turns, _ARCHIVE_CONTENT_CHARS


def test_history_turns_caps_and_filters():
    msgs = [
        {"role": "system", "content": "ignore"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": ""},  # empty — drop
        {"role": "tool", "content": "nope"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"},
        {"role": "assistant", "content": "a3"},
    ]
    out = _history_turns(msgs, limit=4)
    assert [m["content"] for m in out] == ["u2", "a2", "u3", "a3"]


def test_entry_excerpt_truncates_content():
    long = "x" * (_ARCHIVE_CONTENT_CHARS + 200)
    text = _entry_excerpt({"type": "memory", "title": "T", "content": long})
    assert "T" in text
    assert "[MEMORY]" in text
    # Excerpt body should be truncated well under the raw content length.
    assert len(text) < len(long)


def test_tool_names_for_abilities_no_db():
    # Defaults: core always present; music has no tools; web adds web_*.
    names = ab.tool_names_for_abilities({"web", "music"})
    assert "search_archive" in names
    assert "web_search" in names
    assert "get_weather" in names
    # Terminal is not enabled → run_command absent
    assert "run_command" not in names

    empty = ab.tool_names_for_abilities(set())
    assert empty == ab.CORE_TOOLS
