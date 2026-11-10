"""Local-first defaults. Paid cloud seats are never required."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STUDY_OLLAMA = "http://127.0.0.1:11435"
MAIN_OLLAMA = "http://127.0.0.1:11434"
WELL_KNOWN_INSTALL = Path("G:/HeirloomStudyHall")

# Dedicated instance (11435). Embed models stay off the speaking panel.
EMBED_MODELS = ("mxbai-embed-large", "nomic-embed-text")

# A diverse mix of families, all on the Study Hall Ollama, plus a small moderator.
DEFAULT_READERS = (
    {"model": "phi4:14b", "host": "study"},
    {"model": "mistral-small3.2:24b", "host": "study"},
    {"model": "gemma3:27b", "host": "study"},
)
DEFAULT_MODERATOR = {"model": "llama3.1:8b", "host": "study"}
MODERATOR_FALLBACKS = (
    {"model": "qwen3:8b", "host": "main"},
)

# Known on the owner's machines. Discovery still trusts whatever /api/tags returns.
KNOWN_STUDY_MODELS = (
    "nomic-embed-text",
    "mxbai-embed-large",
    "phi4:14b",
    "mistral-small3.2:24b",
    "gemma3:27b",
    "deepseek-r1:32b",
    "qwen3:30b",
    "llama3.1:8b",
)
KNOWN_MAIN_MODELS = (
    "qwen3:8b",
    "qwen3:32b",
    "llama3.3:70b",
    "gpt-oss:120b",
    "qwen2.5vl",
)

USER_AGENT = "HeirloomStudyHall/0.9 (local; owner-operated research)"
MIN_INTERVAL = 1.5


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_data_dir() -> Path:
    env = (os.environ.get("STUDYHALL_DATA") or os.environ.get("HEIRLOOM_STUDY_HALL") or "").strip()
    if env:
        return Path(env)
    return package_root() / "data"


def default_config() -> dict[str, Any]:
    return {
        "ollama": [
            {"name": "study", "url": STUDY_OLLAMA},
            {"name": "main", "url": MAIN_OLLAMA},
        ],
        "local_servers": [],
        "cloud": [],
        "min_interval": MIN_INTERVAL,
        "panel": {
            "readers": [dict(item) for item in DEFAULT_READERS],
            "moderator": dict(DEFAULT_MODERATOR),
            "moderator_fallbacks": [dict(item) for item in MODERATOR_FALLBACKS],
        },
        "embed_models": list(EMBED_MODELS),
    }


def config_path() -> Path | None:
    env = (os.environ.get("STUDYHALL_CONFIG") or "").strip()
    if env:
        return Path(env)
    data = default_data_dir()
    beside_data = data.parent / "config.json"
    if beside_data.is_file():
        return beside_data
    bundled = package_root() / "config.json"
    if bundled.is_file():
        return bundled
    return None


def load_config() -> dict[str, Any]:
    config = default_config()
    path = config_path()
    if path is None or not path.is_file():
        return config
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return config
    if not isinstance(loaded, dict):
        return config
    for key in ("ollama", "local_servers", "cloud", "embed_models"):
        if key in loaded and isinstance(loaded[key], list):
            config[key] = loaded[key]
    if isinstance(loaded.get("min_interval"), (int, float)) and loaded["min_interval"] >= 0:
        config["min_interval"] = float(loaded["min_interval"])
    if isinstance(loaded.get("panel"), dict):
        config["panel"] = {**config["panel"], **loaded["panel"]}
    return config
