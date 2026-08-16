"""Local AI helpers for the Heirloom desktop companion.

One-click model downloads (Ollama) and on-PC chat so the phone / web app
can use a model that never leaves the house.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request


OLLAMA_HOST = "http://127.0.0.1:11434"


def ollama_bin() -> str | None:
    return shutil.which("ollama")


def ollama_installed() -> bool:
    return bool(ollama_bin())


def list_local_models() -> tuple[str, str]:
    """Return (status, newline-separated model tags) for `list_models` commands."""
    binary = ollama_bin()
    if not binary:
        return "error", "Ollama isn't installed yet. Get it from https://ollama.com — one installer, then tap Download again."
    try:
        r = subprocess.run([binary, "list"], capture_output=True, text=True, timeout=20)
    except Exception as exc:  # noqa: BLE001
        return "error", str(exc)
    if r.returncode != 0:
        return "error", ((r.stderr or r.stdout or "ollama list failed")[-2000:])
    tags = []
    for i, line in enumerate((r.stdout or "").splitlines()):
        if i == 0 and line.lower().startswith("name"):
            continue
        name = line.split()[0].strip() if line.split() else ""
        if name:
            tags.append(name)
    return "ok", "\n".join(tags) if tags else "(none installed)"


def pull_model(name: str) -> tuple[str, str]:
    binary = ollama_bin()
    if not binary:
        return (
            "error",
            "Ollama isn't installed on this PC yet. Install it from https://ollama.com (one click), open it once, then tap Download again.",
        )
    model = (name or "").strip()
    if not model:
        return "error", "No model name given."
    try:
        r = subprocess.run(
            [binary, "pull", model],
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        return "error", f"Download of {model} timed out. Try again — Ollama keeps partial files."
    except Exception as exc:  # noqa: BLE001
        return "error", str(exc)
    out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    if r.returncode != 0:
        return "error", out[-2000:] or f"ollama pull {model} failed"
    return "ok", f"ready: {model}"


def llm_chat_local(payload: dict) -> tuple[str, str]:
    """OpenAI-compatible chat against local Ollama. Used when Twin chat is
    assigned to a home-PC model.
    """
    model = (payload.get("model") or "").strip()
    messages = payload.get("messages") or []
    if not model:
        return "error", "No local model selected."
    if not isinstance(messages, list) or not messages:
        return "error", "No messages to send."
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        return "ok", text.strip() or "(empty reply)"
    except urllib.error.URLError as exc:
        return "error", (
            f"Ollama isn't answering on {OLLAMA_HOST}. Open the Ollama app on this PC. ({exc})"
        )
    except Exception as exc:  # noqa: BLE001
        return "error", str(exc)


def parse_tags(output: str) -> list[str]:
    tags = []
    for line in (output or "").splitlines():
        name = line.split()[0].strip() if line.split() else ""
        if name and name.lower() != "name" and not name.startswith("("):
            tags.append(name)
    return tags
