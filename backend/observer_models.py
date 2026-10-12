"""Vision model picked from VRAM. Weights in the default table are Apache-2.0.

No GPU means OCR and heuristics only. Llama-based LLaVA is not selected: the
Llama community license is not an unrestricted commercial license.

The reference Twin Box is an RTX 3090 (24 GB) with 32 GB of system RAM.
``qwen2.5:32b`` is about 20 GB, so it does not sit beside a vision model.
Keep this table in sync with ``box/lib/models.sh``.
"""
from __future__ import annotations

from dataclasses import dataclass

# MiB. Keep the vision-only ladder in sync with heirloom_observer_model_for_vram_mib.
_SIX_GB = 6 * 1024
_TWELVE_GB = 12 * 1024

# RTX 3090 reports 24576 MiB. The lab machine has 32 GB of system RAM.
REFERENCE_VRAM_MIB = 24 * 1024
REFERENCE_RAM_MIB = 32 * 1024
# Room for KV cache, the vision pass, and CUDA, on top of the two weight files.
VRAM_HEADROOM_MIB = 4 * 1024
# Four gray thumbnails plus one analysis frame. Modest next to Mongo and Ollama.
RAM_RING_SLOTS = 4
RAM_RING_BUDGET_BYTES = 64 * 1024 * 1024
RAM_RING_BUDGET_MAX_BYTES = 256 * 1024 * 1024

# Ollama library card sizes, rounded up to MiB. Not a measurement from this machine.
WEIGHTS_MIB = {
    "qwen2.5:3b": 2048,
    "qwen2.5:7b": 4915,
    "qwen2.5:14b": 9216,
    "qwen2.5:32b": 20480,
    "qwen2.5:72b": 48128,
    "moondream": 1741,
    "qwen2.5vl:3b": 3277,
    "qwen2.5vl:7b": 6144,
}

# Strongest co-resident pair first. All of these tags are Apache-2.0.
_SHARED_PAIRS = (
    ("qwen2.5:14b", "qwen2.5vl:7b"),
    ("qwen2.5:7b", "qwen2.5vl:7b"),
    ("qwen2.5:7b", "qwen2.5vl:3b"),
    ("qwen2.5:3b", "qwen2.5vl:3b"),
    ("qwen2.5:3b", "moondream"),
)
_VISION_ALONE = ("qwen2.5vl:7b", "qwen2.5vl:3b", "moondream")
_CHAT_ALONE = ("qwen2.5:72b", "qwen2.5:32b", "qwen2.5:14b", "qwen2.5:7b", "qwen2.5:3b")


@dataclass(frozen=True)
class ModelResidency:
    twin: str
    vision: str
    vram_mib: int
    twin_weight_mib: int
    vision_weight_mib: int
    expected_mib: int
    fits: bool
    max_loaded: int
    vision_keep_alive: str

    @property
    def mode(self) -> str:
        if not self.vision:
            return "ocr"
        return "shared" if self.fits else "exclusive"


def _vram(mib: int | str | None) -> int:
    try:
        return max(0, int(mib))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def weight_mib(tag: str) -> int:
    return WEIGHTS_MIB.get((tag or "").strip().lower(), 0)


def same_model(left: str, right: str) -> bool:
    def norm(value: str) -> str:
        parts = [part for part in value.strip().lower().split(":") if part]
        if parts and parts[-1] == "latest":
            parts = parts[:-1]
        return ":".join(parts)

    folded = norm(left)
    return bool(folded) and folded == norm(right)


def models_fit(twin: str, vision: str, vram_mib: int | str | None) -> bool:
    """True when both weight files plus the headroom sit in ``vram_mib``."""
    if not (vision or "").strip():
        return True
    twin_weight = weight_mib(twin)
    vision_weight = weight_mib(vision)
    if twin_weight <= 0 or vision_weight <= 0:
        return False
    return twin_weight + vision_weight + VRAM_HEADROOM_MIB <= _vram(vram_mib)


def _residency(twin: str, vision: str, vram_mib: int) -> ModelResidency:
    twin_weight = weight_mib(twin)
    vision_weight = weight_mib(vision) if vision else 0
    fits = models_fit(twin, vision, vram_mib)
    if not vision:
        expected = twin_weight
        keep = "0"
        loaded = 1
    elif fits:
        expected = twin_weight + vision_weight + VRAM_HEADROOM_MIB
        keep = "45s"
        loaded = 2
    else:
        expected = max(twin_weight, vision_weight) + VRAM_HEADROOM_MIB
        keep = "0"
        loaded = 1
    return ModelResidency(
        twin=twin,
        vision=vision,
        vram_mib=vram_mib,
        twin_weight_mib=twin_weight,
        vision_weight_mib=vision_weight,
        expected_mib=expected,
        fits=fits,
        max_loaded=loaded,
        vision_keep_alive=keep,
    )


def _fits_alone(tag: str, vram_mib: int) -> bool:
    weight = weight_mib(tag)
    return weight > 0 and weight + VRAM_HEADROOM_MIB <= vram_mib


def observer_pair_for_vram_mib(mib: int | str | None) -> ModelResidency:
    """Chat and vision tags that can be loaded together, or an exclusive fallback.

    The RTX 3090 (24576 MiB) selects ``qwen2.5:14b`` and ``qwen2.5vl:7b``.
    """
    vram = _vram(mib)
    if vram <= 0:
        return _residency("qwen2.5:3b", "", 0)
    for twin, vision in _SHARED_PAIRS:
        plan = _residency(twin, vision, vram)
        if plan.fits:
            return plan
    vision = next((tag for tag in _VISION_ALONE if _fits_alone(tag, vram)), "")
    twin = next((tag for tag in _CHAT_ALONE if _fits_alone(tag, vram)), "qwen2.5:3b")
    return _residency(twin, vision, vram)


def residency_for(twin: str, vision: str, vram_mib: int | str | None) -> ModelResidency:
    """Plan for the tags actually configured, including an operator override."""
    return _residency((twin or "").strip(), (vision or "").strip(), _vram(vram_mib))


def vision_model_for_vram_mib(mib: int | str | None) -> str:
    """Vision-only ladder. The installer uses ``observer_pair_for_vram_mib`` instead."""
    value = _vram(mib)
    if value <= 0:
        return ""
    if value < _SIX_GB:
        return "moondream"
    if value < _TWELVE_GB:
        return "qwen2.5vl:3b"
    return "qwen2.5vl:7b"


def keep_alive_payload(raw: str) -> int | str:
    """Ollama wants ``0`` to unload now, or a duration such as ``45s``."""
    text = (raw or "").strip()
    if text in {"", "0", "0s"}:
        return 0
    return text


def vision_model_license(tag: str) -> str:
    name = (tag or "").strip().lower()
    if not name:
        return "none"
    if name.startswith("moondream") or name.startswith("qwen2.5vl") or name.startswith("qwen3-vl") or name.startswith("qwen2.5:"):
        return "Apache-2.0"
    return "check-before-use"
