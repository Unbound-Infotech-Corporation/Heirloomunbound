"""Code workspace policy: privacy, hunks, commands, local coder models."""
from __future__ import annotations

from pathlib import Path

import pytest

from assist_receipt import tool_label
from code_workspace import (
    CodePrivacyError,
    apply_hunks,
    approve_command,
    cursor_status,
    diff_hunks,
    list_tree,
    pack_context,
    parse_porcelain,
    pick_coder_model,
    plan_agent,
)
from assist_agent import (
    McpRefused,
    draft_message,
    prepare_odysseus,
    prepare_research,
    tools_for,
    validate_mcp,
)
from owner_privacy import OwnerHidden, require_owner


def test_coder_stays_local_and_off_the_twin_router():
    chosen = pick_coder_model(["llama3.1", "gpt-4o", "qwen2.5-coder:7b", "claude-3"])
    assert chosen == {"model": "qwen2.5-coder:7b", "backend": "ollama", "cloud": False, "reason": ""}
    preferred = pick_coder_model(["qwen2.5-coder:7b", "qwen3-coder:30b"])
    assert preferred["model"] == "qwen3-coder:30b"
    alone = pick_coder_model(["gpt-oss:120b", "gemini-2.5"])
    assert alone["model"] is None
    assert alone["cloud"] is False
    assert "twin" in alone["reason"]
    assert cursor_status(binaries_present=True)["enabled"] is False
    import code_workspace
    source = Path(code_workspace.__file__).read_text(encoding="utf-8")
    assert "import model_router" not in source
    assert "import llm_provider" not in source


def test_project_tree_skips_secrets_and_the_vault(tmp_path: Path):
    project = tmp_path / "app"
    (project / "src").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print(1)\n", encoding="utf-8")
    (project / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "pkg.js").write_text("x", encoding="utf-8")
    listed = list_tree(project)
    assert listed["files"] == ["src/main.py"]
    with pytest.raises(CodePrivacyError):
        list_tree(Path("/var/lib/heirloom/vault"))
    packed = pack_context(
        {"src/main.py": "print(1)\n", ".env": "TOKEN=secret", "notes.md": "private memory about the oak tree"},
        ["private memory about the oak tree"],
    )
    assert "TOKEN" not in packed
    assert "oak tree" not in packed
    assert "[private]" in packed


def test_hunks_can_be_accepted_one_at_a_time():
    before = "alpha\nbeta\n"
    after = "alpha\nBETA\ngamma\n"
    hunks = diff_hunks(before, after)
    assert hunks
    rejected = apply_hunks(before, hunks, [])
    assert rejected == before
    accepted = apply_hunks(before, hunks, [hunk["id"] for hunk in hunks])
    assert accepted == after


def test_hunks_change_the_named_line_when_the_text_repeats():
    before = "same\nsame\n"
    hunks = diff_hunks(before, "same\nchanged\n")
    assert len(hunks) == 1
    assert hunks[0]["start_line"] == 2
    assert apply_hunks(before, hunks, [hunks[0]["id"]]) == "same\nchanged\n"


def test_several_inserts_keep_their_order():
    before = "a\n"
    hunks = diff_hunks(before, "a\nb\nc\n")
    assert apply_hunks(before, hunks, [hunk["id"] for hunk in hunks]) == "a\nb\nc\n"


def test_commands_wait_and_dangerous_ones_cannot_be_confirmed():
    waiting = approve_command("pytest -q", approved=False)
    assert waiting["needs_approval"] is True
    assert waiting["executed"] is False
    confirmed = approve_command("pytest -q", approved=True)
    assert confirmed["allow"] is True
    assert confirmed["executed"] is False
    blocked = approve_command("rm -rf /", approved=True)
    assert blocked["blocked"] is True
    assert blocked["allow"] is False
    assert approve_command("shutdown /s", approved=True)["blocked"] is True
    rows = parse_porcelain(" M README.md\n?? new.txt\n")
    assert rows[0] == {"status": " M", "path": "README.md"}
    assert rows[1]["path"] == "new.txt"
    assert plan_agent("fix the test")["cloud"] is False


def test_assist_chat_tools_stay_off_the_twin_and_strip_memories():
    import asyncio

    from assist_studio_tools import exec_studio_tool, prompt_private_snippets, studio_names_for

    prompt = "=== LONG-TERM MEMORY ===\n- Grew up in Vermont. [#12]\n- Mom\n===\n"
    snippets = prompt_private_snippets(prompt)
    assert "Grew up in Vermont." in snippets
    assert "[#12]" not in " ".join(snippets)
    assert "Mom" in snippets
    cited = asyncio.run(exec_studio_tool(
        "web_research",
        {"query": "Look up Grew up in Vermont."},
        role="assistant",
        audience="owner",
        private_texts=snippets,
    ))
    assert "Vermont" not in cited["summary"]
    from owner_privacy import redact_private

    assert redact_private("weather in Mombasa", ["Mom"]) == "weather in Mombasa"
    assert redact_private("Call Mom tonight", ["Mom"]) == "Call [private] tonight"

    assert "smart_home_set" in studio_names_for("assistant", "owner")
    assert studio_names_for("twin", "owner") == set()
    assert studio_names_for("assistant", "heir") == set()
    assert studio_names_for("assistant", "owner", source="phone") == set()
    memory = "private memory about the oak tree"
    research = asyncio.run(exec_studio_tool(
        "web_research",
        {"query": f"Look up {memory}"},
        role="assistant",
        audience="owner",
        private_texts=[memory],
    ))
    assert memory not in research["summary"]
    assert memory not in str(research["ui"])
    lamp = asyncio.run(exec_studio_tool(
        "smart_home_set",
        {"name": "Hall light", "kind": "light", "action": "off", "approved": True, "always_allow": True, "critical_confirm": True},
        role="assistant",
        audience="owner",
    ))
    assert lamp["ui"]["needs_confirm"] is True
    assert lamp["ui"]["ok"] is False
    blocked = asyncio.run(exec_studio_tool(
        "smart_home_set",
        {"name": "Kitchen fridge", "kind": "plug", "action": "off", "approved": True, "always_allow": True},
        role="assistant",
        audience="owner",
    ))
    assert blocked["ui"]["needs_confirm"] is True
    twin = asyncio.run(exec_studio_tool(
        "writing_rewrite",
        {"text": "This is very long.", "mode": "shorter"},
        role="twin",
        audience="owner",
    ))
    assert twin["ui"]["error"] == "assist_only"
    draft = asyncio.run(exec_studio_tool(
        "draft_message",
        {"to": "family@example.com", "body": f"Remember {memory}"},
        role="assistant",
        audience="owner",
        private_texts=[memory],
    ))
    assert draft["ui"]["sent"] is False
    assert memory not in draft["ui"]["body"]
    assert tools_for(role="assistant", audience="owner") 
    assert tools_for(role="twin", audience="owner") == []
    assert tools_for(role="assistant", audience="heir") == []
    assert tools_for(role="assistant", audience="owner", heir_surface=True) == []
    memory = "private memory about the oak tree"
    research = prepare_research(f"Look up {memory}", [memory])
    assert memory not in research["payload"]
    assert research["sent_private"] is False
    odysseus = prepare_odysseus(f"Ask about {memory} in /var/lib/heirloom/vault", [memory])
    assert memory not in odysseus["payload"]
    assert "/var/lib/heirloom/vault" not in odysseus["payload"]
    draft = draft_message(kind="email", to="family@example.com", body=f"Remember {memory}", private_texts=[memory])
    assert draft["sent"] is False
    assert memory not in draft["body"]
    with pytest.raises(McpRefused):
        validate_mcp({"url": "https://mcp.example.com"})
    local = validate_mcp({"command": "heirloom-mcp"})
    assert local["remote"] is False
    assert tool_label("smart_home_set") == "Change a device"
    assert tool_label("writing_rewrite") == "Rewrite writing"
    with pytest.raises(OwnerHidden):
        require_owner({"audience": "heir", "heir_surface": True})
    require_owner({"audience": "owner", "heir_surface": False})
