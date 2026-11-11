"""Code workspace engine: folder, diffs, command approval, local coder.

The editor UI (Monaco, terminal, git buttons) is a later Windows pass. This
module is the policy and the diff math that pass can call.

Coder models are local Ollama tags only (qwen2.5-coder, qwen3-coder, and
other local coder tags). Hosted tags are ignored. The twin's brain is not
reused and ``model_router.py`` is not involved.

The vault, owner keys, and observer notes are not a code project. Commands
wait for Confirm. Destructive commands cannot be confirmed.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path
from typing import Any

from owner_privacy import redact_private

SKIP_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "bin",
    "obj",
    "dist",
}
SECRET_NAMES = {
    ".env",
    "box.env",
    "owner.pass",
    "odysseus.token",
    "id_rsa",
    "credentials.json",
}
CODER_HINTS = (
    "qwen3-coder",
    "qwen2.5-coder",
    "deepseek-coder",
    "codellama",
    "starcoder",
)
HOSTED_MARKERS = ("claude", "gpt-4", "gpt-3", "gemini", "sonnet", "opus", "haiku", "openai/")
BLOCKED_FRAGMENTS = (
    "rm -rf /",
    "rm -rf /*",
    ":(){",
    "mkfs",
    "diskpart",
    "format c:",
    "format d:",
    "shutdown",
    "restart-computer",
    "stop-computer",
    "dd if=",
)


class CodePrivacyError(Exception):
    """The folder is private memory, not a project."""


class CodeEditError(Exception):
    """A hunk could not be applied."""


def _hosted(tag: str) -> bool:
    name = (tag or "").strip().lower()
    if name.startswith("gpt-oss"):
        return False
    return any(marker in name for marker in HOSTED_MARKERS)


def pick_coder_model(tags: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Choose a local coder tag. Never a hosted model, never the twin brain by default."""
    local = [tag.strip() for tag in tags if tag and tag.strip() and not _hosted(tag)]
    for hint in CODER_HINTS:
        for tag in local:
            if hint in tag.lower():
                return {"model": tag, "backend": "ollama", "cloud": False, "reason": ""}
    return {
        "model": None,
        "backend": "none",
        "cloud": False,
        "reason": (
            "No local coder model yet. Pull qwen2.5-coder in Ollama. "
            "The twin's brain is left alone."
        ),
    }


def cursor_status(*, binaries_present: bool = False, signed_in: bool = False) -> dict[str, Any]:
    return {
        "enabled": False,
        "available": bool(binaries_present),
        "signed_in": bool(signed_in),
        "detail": (
            "Cursor is optional. Heirloom's code tools use a local coder model. "
            "Nothing is installed for you."
        ),
    }


def _under_live_box(path: Path) -> bool:
    try:
        path.resolve().relative_to(Path("/var/lib/heirloom").resolve())
    except (ValueError, OSError):
        return False
    return True


def assert_project(path: Path) -> Path:
    resolved = Path(path).resolve()
    if _under_live_box(resolved):
        raise CodePrivacyError(
            "The Twin Box data folder is not a code project. Your memories stay out of the editor."
        )
    parts = {part.lower() for part in resolved.parts}
    if "vault" in parts or "observer" in parts:
        raise CodePrivacyError("That folder holds private memories, not project files.")
    if not resolved.is_dir():
        raise CodePrivacyError("Choose a project folder.")
    return resolved


def list_tree(path: Path, *, limit: int = 200) -> dict[str, Any]:
    root = assert_project(path)
    files: list[str] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS and not name.startswith(".")]
        for name in filenames:
            if name in SECRET_NAMES or name.endswith(".token") or name.endswith(".pem"):
                continue
            files.append(os.path.relpath(os.path.join(dirpath, name), root))
            if len(files) >= limit:
                truncated = True
                break
        if truncated:
            break
    return {"root": str(root), "files": sorted(files), "truncated": truncated}


def pack_context(files: dict[str, str], private_texts: list[str] | None = None) -> str:
    """File text for a local coder. Secret names and private memories are dropped."""
    parts: list[str] = []
    for name, text in files.items():
        base = Path(name).name
        if base in SECRET_NAMES or base.endswith(".token"):
            continue
        cleaned = redact_private(text or "", private_texts)
        parts.append(f"## {name}\n{cleaned}")
    return "\n".join(parts)


def diff_hunks(before: str, after: str) -> list[dict[str, Any]]:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
    hunks: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks.append({
            "id": f"h{len(hunks) + 1}",
            "op": tag,
            "start_line": i1 + 1,
            "before": "".join(before_lines[i1:i2]),
            "after": "".join(after_lines[j1:j2]),
        })
    return hunks


def apply_hunks(before: str, hunks: list[dict[str, Any]], accept_ids: list[str] | set[str]) -> str:
    """Apply accepted hunks. Rejected hunks stay as they were."""
    accepted = set(accept_ids)
    updated = before
    for hunk in hunks:
        if hunk.get("id") not in accepted:
            continue
        old = hunk.get("before") or ""
        new = hunk.get("after") or ""
        if not old:
            line = int(hunk.get("start_line") or 1)
            rows = updated.splitlines(keepends=True)
            index = max(0, min(len(rows), line - 1))
            rows.insert(index, new if new.endswith("\n") or not new else new)
            updated = "".join(rows)
            continue
        if old not in updated:
            raise CodeEditError(f"Could not find hunk {hunk.get('id')} in the file.")
        updated = updated.replace(old, new, 1)
    return updated


def parse_porcelain(text: str) -> list[dict[str, str]]:
    rows = []
    for line in (text or "").splitlines():
        if len(line) < 4:
            continue
        rows.append({"status": line[:2], "path": line[3:]})
    return rows


def review_command(command: str) -> dict[str, Any]:
    lowered = " ".join((command or "").lower().split())
    for fragment in BLOCKED_FRAGMENTS:
        if fragment in lowered:
            return {
                "allow": False,
                "needs_approval": False,
                "blocked": True,
                "executed": False,
                "reason": "That command can damage this PC. Heirloom will not run it.",
            }
    if "remove-item" in lowered and "-recurse" in lowered and (":\\" in lowered or lowered.endswith(" /")):
        return {
            "allow": False,
            "needs_approval": False,
            "blocked": True,
            "executed": False,
            "reason": "That command can damage this PC. Heirloom will not run it.",
        }
    return {
        "allow": False,
        "needs_approval": True,
        "blocked": False,
        "executed": False,
        "reason": "Waiting for Confirm before running this command.",
        "command": command,
    }


def approve_command(command: str, *, approved: bool) -> dict[str, Any]:
    """Confirmation never runs the command. The Windows terminal does that later."""
    decision = review_command(command)
    if decision["blocked"] or not approved:
        return decision
    return {
        **decision,
        "allow": True,
        "needs_approval": False,
        "executed": False,
        "reason": "Confirmed. The terminal may run it on this PC.",
    }


def plan_agent(goal: str) -> dict[str, Any]:
    return {
        "goal": goal,
        "cloud": False,
        "status": "planned",
        "steps": [
            {"id": "read", "detail": "Read the project files you opened."},
            {"id": "edit", "detail": "Propose edits as hunks you can accept or reject."},
            {"id": "test", "detail": "Run tests only after you confirm the command."},
            {"id": "report", "detail": "Tell you what changed."},
        ],
    }
