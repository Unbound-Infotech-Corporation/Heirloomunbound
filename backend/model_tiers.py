"""Pick the local chat model for the buyer's hardware.

At first run the installer (Linux box or Windows) detects the GPU and its video
memory, then pulls the model from TIERS that fits. The table comes from
``heirloom-box bench-models`` runs (see docs/MODEL-TIERS.md): every candidate
answered the same grounding, recall, normal-chat, tool-call, JSON and latency
checks, and the winner per tier is the best scorer that fits with voice loaded.

Override with HEIRLOOM_MODEL_OVERRIDE (or an explicit OLLAMA_TWIN_MODEL in
box.env, which upgrades keep). Local Ollama tags only; a cloud tag is refused.

CLI (no third-party packages):
  python3 model_tiers.py detect            GPU vendor, name, VRAM, RAM as JSON
  python3 model_tiers.py choose [--vram-mib N] [--ram-mib N] [--no-voice-gpu] [--json]
  python3 model_tiers.py table             the tier table as JSON
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

EMBED_MODEL = "nomic-embed-text"
# Chatterbox voice plus the embed model on the GPU: measured 5764 MiB on the RTX 3090
# before any chat model loads. Kept free when voice runs on the same card.
VOICE_RESERVE_MIB = 5248
BASE_RESERVE_MIB = 512
# Context the box loads chat models with (OLLAMA_CONTEXT_LENGTH). A twin turn
# (system prompt, cards, recent turns) stays under 6k tokens.
DEFAULT_NUM_CTX = 16384


@dataclass(frozen=True)
class Tier:
    name: str
    label: str
    min_vram_mib: int  # GPU memory the card reports; 0 = CPU only
    model: str
    fallback: str  # smaller pick when the main one does not fit after reserves
    num_ctx: int
    loaded_mib: int  # measured on the RTX 3090 at num_ctx (q8_0 KV, flash attention); 0 = not measured
    voice_on_gpu: bool  # Chatterbox shares this card; below 16 GB it runs on the CPU
    license: str
    note: str = ""


# Ordered biggest first. Winners of the November 2026 bench (docs/MODEL-TIERS.md):
# 20 open models, each through grounding, chat, tools, JSON, judged open answers,
# the full eval-grounding pipeline, speed, and VRAM measured beside the voice model.
TIERS: tuple[Tier, ...] = (
    Tier("xl", "32 GB+ GPU (RTX 5090, RTX PRO)", 30720, "gemma4:26b", "gemma4:12b", 16384, 18008, True, "Apache-2.0"),
    Tier("large", "24 GB GPU (RTX 3090/4090, RX 7900 XTX)", 22528, "gemma4:12b", "gemma4:e4b", 16384, 8398, True, "Apache-2.0",
         "gemma4:26b (18 GB) and qwen3.8:27b spill to the CPU beside voice on a 24 GB card; mistral-small3.2 fails eval-grounding."),
    Tier("medium", "16 GB GPU (RTX 4060 Ti 16G/4070 Ti S/4080, RX 7800 XT)", 15360, "gemma4:12b", "qwen3.5:4b", 16384, 8398, True,
         "Apache-2.0"),
    Tier("small", "12 GB GPU (RTX 3060 12G/4070, RX 6700 XT)", 11264, "qwen3.5:4b", "gemma4:e2b", 16384, 4628, True, "Apache-2.0",
         "qwen3.5:4b misses 1 eval-grounding case, gemma4:e4b misses 2."),
    Tier("compact", "8 GB GPU (RTX 3060 Ti/4060, RX 7600)", 7168, "qwen3.5:4b", "gemma4:e2b", 8192, 4358, False, "Apache-2.0",
         "Voice runs on the CPU."),
    Tier("cpu", "No supported GPU (CPU and system RAM)", 0, "gemma4:e4b", "gemma4:e2b", 8192, 0, False, "Apache-2.0",
         "20 tok/s on 8 CPU threads (qwen3.5:4b manages 10); under 16 GB of RAM uses gemma4:e2b (28 tok/s)."),
)

_CLOUD_MARKERS = ("gpt-4", "gpt-5", "claude", "gemini", "openai/", "anthropic/", "-cloud", ":cloud")


@dataclass
class Hardware:
    vendor: str = "none"  # nvidia | amd | intel | none
    gpu: str = ""
    vram_mib: int = 0
    ram_mib: int = 0
    os: str = field(default_factory=lambda: platform.system().lower())
    source: str = ""


@dataclass
class Choice:
    model: str
    tier: str
    label: str
    reason: str
    num_ctx: int
    fallback: str = ""
    override: bool = False
    hardware: Optional[dict] = None


def _run(argv: list[str], timeout: float = 8.0) -> str:
    if not shutil.which(argv[0]):
        return ""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _int(text: Any) -> int:
    match = re.search(r"\d+", str(text or ""))
    return int(match.group(0)) if match else 0


def parse_nvidia_smi(text: str) -> tuple[str, int]:
    """'NVIDIA GeForce RTX 3090, 24576' lines. Biggest card wins."""
    best = ("", 0)
    for line in (text or "").splitlines():
        if "," not in line:
            continue
        name, _, mib = line.rpartition(",")
        value = _int(mib)
        if value > best[1]:
            best = (name.strip(), value)
    return best


def parse_rocm_smi(text: str) -> tuple[str, int]:
    """rocm-smi --showmeminfo vram --json: bytes per card."""
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError:
        return ("", 0)
    best = ("", 0)
    for card, row in (data or {}).items():
        if not isinstance(row, dict):
            continue
        total = 0
        for key, value in row.items():
            if "total" in key.lower() and "vram" in key.lower() and "used" not in key.lower():
                total = _int(value) // (1024 * 1024)
        if total > best[1]:
            best = (str(row.get("Card series") or row.get("Card model") or card), total)
    return best


def _linux_sysfs_vram() -> tuple[str, str, int]:
    """AMD and Intel discrete cards expose mem_info_vram_total in bytes."""
    best = ("", "", 0)
    for path in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
        try:
            mib = int(path.read_text().strip()) // (1024 * 1024)
            vendor_id = (path.parent / "vendor").read_text().strip().lower()
        except (OSError, ValueError):
            continue
        vendor = {"0x1002": "amd", "0x8086": "intel", "0x10de": "nvidia"}.get(vendor_id, "unknown")
        if mib > best[2]:
            best = (vendor, path.parent.name, mib)
    return best


def _windows_video() -> list[tuple[str, int]]:
    """Name and dedicated memory from the display-class registry (AdapterRAM caps at 4 GB)."""
    script = (
        "$k='HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}';"
        "Get-ChildItem $k -ErrorAction SilentlyContinue | ForEach-Object {"
        "$p=Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue;"
        "if($p.DriverDesc){ '{0}|{1}' -f $p.DriverDesc, $p.'HardwareInformation.qwMemorySize' } }"
    )
    text = _run(["powershell", "-NoProfile", "-Command", script], timeout=15)
    rows = []
    for line in text.splitlines():
        name, _, size = line.partition("|")
        if name.strip():
            rows.append((name.strip(), _int(size) // (1024 * 1024)))
    return rows


def _ram_mib() -> int:
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024))
    except (OSError, ValueError):
        pass
    if platform.system().lower() == "windows":
        text = _run(["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory"])
        return _int(text) // (1024 * 1024)
    return 0


def vendor_from_name(name: str) -> str:
    folded = (name or "").lower()
    if any(word in folded for word in ("nvidia", "geforce", "rtx", "quadro", "tesla")):
        return "nvidia"
    if any(word in folded for word in ("amd", "radeon")):
        return "amd"
    if any(word in folded for word in ("intel", "arc")):
        return "intel"
    return "none"


def detect_hardware() -> Hardware:
    """NVIDIA through nvidia-smi, AMD through rocm-smi or sysfs, Windows through the registry."""
    found = Hardware(ram_mib=_ram_mib())
    name, mib = parse_nvidia_smi(_run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]))
    if mib:
        found.vendor, found.gpu, found.vram_mib, found.source = "nvidia", name, mib, "nvidia-smi"
        return found
    name, mib = parse_rocm_smi(_run(["rocm-smi", "--showmeminfo", "vram", "--json"]))
    if mib:
        found.vendor, found.gpu, found.vram_mib, found.source = "amd", name, mib, "rocm-smi"
        return found
    if found.os == "linux":
        vendor, card, mib = _linux_sysfs_vram()
        if mib >= 2048:
            found.vendor, found.gpu, found.vram_mib, found.source = vendor, card, mib, "sysfs"
        return found
    if found.os == "windows":
        rows = [(n, m) for n, m in _windows_video() if vendor_from_name(n) in {"nvidia", "amd", "intel"}]
        if rows:
            n, m = max(rows, key=lambda row: row[1])
            if m >= 2048:
                found.vendor, found.gpu, found.vram_mib, found.source = vendor_from_name(n), n, m, "registry"
    return found


def is_cloud_tag(tag: str) -> bool:
    folded = (tag or "").strip().lower()
    if folded.startswith("gpt-oss"):
        return False
    return any(marker in folded for marker in _CLOUD_MARKERS)


def override_model() -> str:
    raw = (os.environ.get("HEIRLOOM_MODEL_OVERRIDE") or "").strip()
    if raw and is_cloud_tag(raw):
        return ""
    return raw


def tier_for(vram_mib: int, *, ram_mib: int = 0, vendor: str = "nvidia", voice_on_gpu: bool = True) -> tuple[Tier, str]:
    """The tier and model for this card. Voice on the same GPU takes VOICE_RESERVE_MIB."""
    usable_gpu = vendor in {"nvidia", "amd"} and vram_mib >= 4096
    if not usable_gpu:
        cpu = TIERS[-1]
        model = cpu.model if (ram_mib == 0 or ram_mib >= 16384) else cpu.fallback
        return cpu, model
    for tier in TIERS[:-1]:
        if vram_mib < tier.min_vram_mib:
            continue
        reserve = BASE_RESERVE_MIB + (VOICE_RESERVE_MIB if (voice_on_gpu and tier.voice_on_gpu) else 0)
        if tier.loaded_mib and tier.loaded_mib + reserve > vram_mib:
            return tier, tier.fallback
        return tier, tier.model
    cpu = TIERS[-1]
    return cpu, cpu.model if (ram_mib == 0 or ram_mib >= 16384) else cpu.fallback


def choose(hardware: Optional[Hardware] = None, *, voice_on_gpu: bool = True) -> Choice:
    hw = hardware or detect_hardware()
    tier, model = tier_for(hw.vram_mib, ram_mib=hw.ram_mib, vendor=hw.vendor, voice_on_gpu=voice_on_gpu)
    forced = override_model()
    if forced:
        return Choice(forced, tier.name, tier.label, "HEIRLOOM_MODEL_OVERRIDE", tier.num_ctx,
                      tier.fallback, True, asdict(hw))
    why = f"{hw.gpu or 'no GPU'} {hw.vram_mib} MiB -> {tier.name}"
    if model != tier.model:
        why += f" (fallback: {tier.model} does not fit beside voice)"
    return Choice(model, tier.name, tier.label, why, tier.num_ctx, tier.fallback, False, asdict(hw))


def table() -> list[dict]:
    return [asdict(tier) for tier in TIERS]


# ---- request options for thinking models ---------------------------------

_THINKING_PREFIXES = ("qwen3", "gemma4", "deepseek-r1", "magistral", "phi4-reasoning", "glm-4", "nemotron-3", "gpt-oss")


def _guess_thinking(model: str) -> bool:
    folded = (model or "").strip().lower()
    if folded.startswith("qwen3") and "instruct" in folded:
        return False
    return folded.startswith(_THINKING_PREFIXES)


_CAPS: dict[tuple[str, str], Optional[tuple[str, ...]]] = {}


def _capabilities(base_url: str, model: str) -> Optional[tuple[str, ...]]:
    """Ollama's capability list for a tag, cached per process. None when Ollama cannot say."""
    key = (base_url.rstrip("/"), model)
    if key in _CAPS:
        return _CAPS[key]
    found: Optional[tuple[str, ...]] = None
    try:
        body = json.dumps({"model": model}).encode("utf-8")
        request = urllib.request.Request(key[0] + "/api/show", data=body,
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=4) as response:  # noqa: S310 (LAN Ollama only)
            data = json.loads(response.read().decode("utf-8") or "{}")
        caps = data.get("capabilities")
        if isinstance(caps, list):
            found = tuple(str(item) for item in caps)
    except Exception:  # noqa: BLE001
        found = None
    _CAPS[key] = found
    return found


def thinks(model: str, base_url: str = "") -> bool:
    """True when Ollama lists 'thinking' for this tag. A name guess when Ollama cannot be asked."""
    if base_url:
        caps = _capabilities(base_url, model)
        if caps is not None:
            return "thinking" in caps
    return _guess_thinking(model)


def think_value(model: str, base_url: str = "") -> Any:
    """What to send as ``think``. None means leave it out (the model cannot think).

    Twin turns are short and must be fast, so thinking is off. gpt-oss cannot
    turn it off and gets "low".
    """
    if not thinks(model, base_url):
        return None
    if (model or "").strip().lower().startswith("gpt-oss"):
        return "low"
    return False


def _main(argv: list[str]) -> int:
    args = list(argv)
    command = args.pop(0) if args else "choose"
    as_json = "--json" in args
    if command == "detect":
        print(json.dumps(asdict(detect_hardware())))
        return 0
    if command == "table":
        print(json.dumps(table(), indent=2))
        return 0
    if command == "choose":
        hw = None
        if "--vram-mib" in args or "--ram-mib" in args:
            def _arg(flag: str) -> int:
                return _int(args[args.index(flag) + 1]) if flag in args and args.index(flag) + 1 < len(args) else 0
            vram = _arg("--vram-mib")
            hw = Hardware(vendor="nvidia" if vram else "none", gpu="(given)", vram_mib=vram, ram_mib=_arg("--ram-mib"))
        picked = choose(hw, voice_on_gpu="--no-voice-gpu" not in args)
        if as_json:
            print(json.dumps(asdict(picked)))
        else:
            print(picked.model)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
