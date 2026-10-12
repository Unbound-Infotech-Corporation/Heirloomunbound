"""Vision model picked from VRAM. Weights in the default table are Apache-2.0.

No GPU means OCR and heuristics only. Llama-based LLaVA is not selected: the
Llama community license is not an unrestricted commercial license.
"""
from __future__ import annotations

# MiB. Keep this table in sync with heirloom_observer_model_for_vram_mib in box/lib/models.sh.
_SIX_GB = 6 * 1024
_TWELVE_GB = 12 * 1024


def vision_model_for_vram_mib(mib: int | str | None) -> str:
    """Return an Ollama tag, or ``\"\"`` when the box should not load a vision model."""
    try:
        value = int(mib)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        return ""
    if value < _SIX_GB:
        return "moondream"
    if value < _TWELVE_GB:
        return "qwen2.5vl:3b"
    return "qwen2.5vl:7b"


def vision_model_license(tag: str) -> str:
    name = (tag or "").strip().lower()
    if not name:
        return "none"
    if name.startswith("moondream") or name.startswith("qwen2.5vl") or name.startswith("qwen3-vl"):
        return "Apache-2.0"
    return "check-before-use"
