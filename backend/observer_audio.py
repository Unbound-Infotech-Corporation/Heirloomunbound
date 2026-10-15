"""Observer audio: two labeled streams, never mixed.

System audio is the capture card's HDMI embed (ALSA, name contains XR1).
The microphone is a Logitech C920 on the box when that card is present.
The companion is the fallback for each stream and posts PCM; this module
keeps those chunks in a short RAM spool and deletes them after a window.

Transcripts are text. Raw audio is not an archive.
"""
from __future__ import annotations

import os
import re
import struct
import time
from pathlib import Path
from typing import Callable, Optional

from observer_privacy import hotkey_detected, redact_stored_text, screen_is_sensitive

SAMPLE_RATE = 16000
MAX_PCM_BYTES = SAMPLE_RATE * 2 * 4
SPOOL_MAX_BYTES = SAMPLE_RATE * 2 * 8
SPOOL_MAX_AGE_S = 30.0
LABEL_MIC = "User said"
LABEL_SYSTEM = "Watching/heard"
_CARD_LINE = re.compile(
    r"^card\s+(\d+):\s*([^[\s]+)\s*\[([^\]]*)\].*?\bdevice\s+(\d+):\s*([^[\n]+)",
    re.MULTILINE,
)


def whisper_model_name(vram_mib: str | int | None = None) -> str:
    """``medium`` when the 3090-class card has room beside vision. Else ``small``."""
    override = (os.environ.get("OBSERVER_WHISPER_MODEL") or "").strip().lower()
    if override in {"tiny", "base", "small", "medium"}:
        return override
    if vram_mib is None:
        vram_mib = os.environ.get("OBSERVER_VRAM_MIB", "0")
    try:
        vram = int(vram_mib or 0)
    except (TypeError, ValueError):
        vram = 0
    if vram >= 20000:
        return "medium"
    return "small"


def whisper_device() -> str:
    raw = (os.environ.get("OBSERVER_WHISPER_DEVICE") or "").strip().lower()
    if raw in {"cuda", "cpu"}:
        return raw
    return "cpu"


def whisper_compute_type(device: str | None = None) -> str:
    choice = device or whisper_device()
    if choice == "cuda":
        return "float16"
    return "int8"


def parse_arecord_listing(text: str) -> list[dict]:
    """Cards from ``arecord -l``. One row per capture device."""
    devices: list[dict] = []
    for match in _CARD_LINE.finditer(text or ""):
        devices.append(
            {
                "card": int(match.group(1)),
                "id": match.group(2).strip(),
                "name": match.group(3).strip(),
                "device": int(match.group(4)),
                "desc": match.group(5).strip(),
            }
        )
    return devices


def _blob(device: dict) -> str:
    return " ".join(
        str(device.get(key) or "") for key in ("id", "name", "desc")
    ).lower()


def pick_system_device(devices: list[dict]) -> dict | None:
    """HDMI embed on the EVGA card. Match XR1 in the ALSA name."""
    for device in devices:
        blob = _blob(device)
        if "xr1" in blob or "evga" in blob:
            return device
    return None


def pick_mic_device(devices: list[dict]) -> dict | None:
    """Logitech C920 when it is plugged into the box. Never the XR1."""
    system = pick_system_device(devices)
    for device in devices:
        if system is not None and device.get("card") == system.get("card") and device.get("device") == system.get("device"):
            continue
        blob = _blob(device)
        if "c920" in blob or "logitech" in blob or "hd pro webcam" in blob:
            return device
    return None


def alsa_device_string(device: dict) -> str:
    """``plughw`` so HDMI 48 kHz stereo becomes 16 kHz mono in arecord."""
    return f"plughw:{int(device['card'])},{int(device['device'])}"


def pcm_samples(pcm: bytes) -> list[int]:
    count = len(pcm) // 2
    if count <= 0:
        return []
    return list(struct.unpack("<" + str(count) + "h", pcm[: count * 2]))


def rms(pcm: bytes) -> float:
    samples = pcm_samples(pcm)
    if not samples:
        return 0.0
    energy = sum(sample * sample for sample in samples) / len(samples)
    return (energy ** 0.5) / 32768.0


def is_silence(pcm: bytes, *, threshold: float | None = None) -> bool:
    """Energy VAD. Silence never reaches Whisper."""
    if threshold is None:
        try:
            threshold = float(os.environ.get("OBSERVER_VAD_RMS", "0.012"))
        except ValueError:
            threshold = 0.012
    return rms(pcm) < threshold


def correlation(left: bytes, right: bytes) -> float:
    """Absolute Pearson correlation of the overlapping tail. 0 when either side is quiet."""
    a = pcm_samples(left)
    b = pcm_samples(right)
    count = min(len(a), len(b))
    if count < 160:
        return 0.0
    step = max(1, count // 4000)
    xs = a[:count:step]
    ys = b[:count:step]
    limit = min(len(xs), len(ys))
    if limit < 8:
        return 0.0
    xs = xs[:limit]
    ys = ys[:limit]
    mean_x = sum(xs) / limit
    mean_y = sum(ys) / limit
    num = 0.0
    den_x = 0.0
    den_y = 0.0
    for x, y in zip(xs, ys):
        dx = x - mean_x
        dy = y - mean_y
        num += dx * dy
        den_x += dx * dx
        den_y += dy * dy
    denom = (den_x * den_y) ** 0.5
    if denom <= 1e-6:
        return 0.0
    return abs(num / denom)


def mic_is_crosstalk(
    mic: bytes,
    system: bytes,
    *,
    corr_at: float | None = None,
    energy_ratio: float | None = None,
) -> bool:
    """Drop a mic window that is the speakers leaking into the microphone.

    A close voice is louder than the concurrent system window and stays.
    """
    if not mic or not system or is_silence(system) or is_silence(mic):
        return False
    if corr_at is None:
        try:
            corr_at = float(os.environ.get("OBSERVER_CROSSTALK_CORR", "0.62"))
        except ValueError:
            corr_at = 0.62
    if energy_ratio is None:
        try:
            energy_ratio = float(os.environ.get("OBSERVER_CROSSTALK_RATIO", "1.8"))
        except ValueError:
            energy_ratio = 1.8
    if correlation(mic, system) < corr_at:
        return False
    return rms(mic) <= rms(system) * energy_ratio


def validate_pcm(pcm: bytes) -> str:
    if not pcm:
        return "empty"
    if len(pcm) > MAX_PCM_BYTES:
        return "too-large"
    if len(pcm) % 2:
        return "alignment"
    return ""


def spool_dir(raw: str | None = None) -> Path:
    """RAM spool. Override with ``OBSERVER_AUDIO_SPOOL`` in tests."""
    if raw is None:
        raw = os.environ.get("OBSERVER_AUDIO_SPOOL", "")
    text = (raw or "").strip()
    if text:
        return Path(text)
    ram = Path("/run/heirloom-observer/audio")
    try:
        if ram.parent.is_dir():
            ram.mkdir(parents=True, exist_ok=True)
            return ram
    except OSError:
        pass
    shm = Path("/dev/shm/heirloom-observer/audio")
    try:
        if Path("/dev/shm").is_dir():
            shm.mkdir(parents=True, exist_ok=True)
            return shm
    except OSError:
        pass
    from observer_store import observer_dir

    inbox = observer_dir() / "audio-inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


def write_chunk(root: Path, source: str, pcm: bytes) -> Path:
    if source not in {"system", "mic"}:
        raise ValueError("source must be system or mic")
    folder = root / source
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{time.time_ns()}.pcm"
    path.write_bytes(pcm)
    return path


def drain_chunks(root: Path, source: str, *, max_bytes: int = SPOOL_MAX_BYTES) -> bytes:
    """Read and delete one stream. Bytes over the cap are deleted unread into memory."""
    folder = root / source
    if not folder.is_dir():
        return b""
    parts: list[bytes] = []
    total = 0
    for path in sorted(p for p in folder.glob("*.pcm") if p.is_file()):
        try:
            data = path.read_bytes()
        except OSError:
            data = b""
        try:
            path.unlink()
        except OSError:
            pass
        if not data or total >= max_bytes:
            continue
        room = max_bytes - total
        parts.append(data[:room])
        total += len(parts[-1])
    return b"".join(parts)


def sweep_stale(root: Path, *, max_age_s: float = SPOOL_MAX_AGE_S, now: float | None = None) -> int:
    """Delete leftover PCM. A stopped daemon must not leave a recording."""
    moment = time.time() if now is None else now
    removed = 0
    if not root.is_dir():
        return 0
    for path in root.rglob("*.pcm"):
        try:
            age = moment - path.stat().st_mtime
        except OSError:
            continue
        if age < max_age_s:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def accept_companion_chunk(
    *,
    source: str,
    pcm: bytes,
    paused: bool,
    enabled: bool,
    spool: Path,
) -> dict:
    """Park one companion window. Refuses a pause, a disabled stream, and odd PCM."""
    if source not in {"system", "mic"}:
        return {"accepted": False, "reason": "source"}
    if paused:
        return {"accepted": False, "reason": "paused"}
    if not enabled:
        return {"accepted": False, "reason": "off"}
    problem = validate_pcm(pcm)
    if problem:
        return {"accepted": False, "reason": problem}
    write_chunk(spool, source, pcm)
    return {"accepted": True, "reason": "", "bytes": len(pcm)}


def consider_transcript(
    text: str,
    *,
    channel: str,
    paused: bool = False,
    hotkey_phrase: str = "",
) -> dict:
    """Label a transcript or drop it. The returned text is what may be stored."""
    if paused:
        return {"store": False, "dropped": False, "latch_pause": False, "reason": "paused", "text": "", "channel": channel}
    if channel not in {"mic", "system"}:
        return {"store": False, "dropped": False, "latch_pause": False, "reason": "channel", "text": "", "channel": channel}
    cleaned = (text or "").strip()
    if not cleaned:
        return {"store": False, "dropped": False, "latch_pause": False, "reason": "empty", "text": "", "channel": channel}
    if hotkey_detected(cleaned, hotkey_phrase):
        return {"store": False, "dropped": False, "latch_pause": True, "reason": "hotkey", "text": "", "channel": channel}
    decision = screen_is_sensitive(cleaned)
    if decision.drop:
        return {
            "store": False,
            "dropped": True,
            "latch_pause": False,
            "reason": decision.reason,
            "text": "",
            "channel": channel,
        }
    label = LABEL_MIC if channel == "mic" else LABEL_SYSTEM
    activity = "speech" if channel == "mic" else "heard"
    excerpt = redact_stored_text(cleaned, limit=280)
    if not excerpt:
        return {"store": False, "dropped": False, "latch_pause": False, "reason": "empty", "text": "", "channel": channel}
    return {
        "store": True,
        "dropped": False,
        "latch_pause": False,
        "reason": "",
        "text": f"{label}: {excerpt}",
        "activity": activity,
        "channel": channel,
    }


def _stream(
    *,
    enabled: bool,
    paused: bool,
    source: str,
    device: str,
    status: str,
) -> dict:
    if paused and enabled:
        status = "paused"
    if not enabled:
        status = "off"
        source = "off"
        device = ""
    return {"enabled": enabled, "source": source, "status": status, "device": device}


def audio_iteration(
    *,
    devices: list[dict],
    system_enabled: bool,
    mic_enabled: bool,
    paused: bool,
    local_system: bytes = b"",
    local_mic: bytes = b"",
    companion_system: bytes = b"",
    companion_mic: bytes = b"",
    transcribe: Optional[Callable[[bytes], str]] = None,
    hotkey_phrase: str = "",
) -> dict:
    """Choose one source per stream, gate crosstalk, and transcribe each alone.

    ``transcribe`` sees either the system window or the mic window, never both
    concatenated.
    """
    notes: list[dict] = []
    if paused:
        return {
            "model": whisper_model_name(),
            "system": _stream(enabled=system_enabled, paused=True, source="off", device="", status="paused"),
            "mic": _stream(enabled=mic_enabled, paused=True, source="off", device="", status="paused"),
            "notes": notes,
        }

    system_dev = pick_system_device(devices) if system_enabled else None
    mic_dev = pick_mic_device(devices) if mic_enabled else None
    if system_dev is not None:
        system_pcm = local_system
        system_source = "xr1"
        system_device = str(system_dev.get("name") or alsa_device_string(system_dev))
    elif system_enabled and companion_system:
        system_pcm = companion_system
        system_source = "companion"
        system_device = "this PC"
    elif system_enabled:
        system_pcm = b""
        system_source = "waiting"
        system_device = ""
    else:
        system_pcm = b""
        system_source = "off"
        system_device = ""

    if mic_dev is not None:
        mic_pcm = local_mic
        mic_source = "c920"
        mic_device = str(mic_dev.get("name") or alsa_device_string(mic_dev))
    elif mic_enabled and companion_mic:
        mic_pcm = companion_mic
        mic_source = "companion"
        mic_device = "this PC"
    elif mic_enabled:
        mic_pcm = b""
        mic_source = "waiting"
        mic_device = ""
    else:
        mic_pcm = b""
        mic_source = "off"
        mic_device = ""

    system_status = _window_status(system_pcm, system_source)
    mic_status = _window_status(mic_pcm, mic_source)
    suppressed = bool(mic_pcm) and bool(system_pcm) and mic_is_crosstalk(mic_pcm, system_pcm)
    if suppressed:
        mic_status = "suppressed"
        mic_pcm = b""

    if transcribe is not None:
        for channel, pcm in (("system", system_pcm), ("mic", mic_pcm)):
            if not pcm or is_silence(pcm):
                continue
            try:
                heard = transcribe(pcm)
            except Exception:
                if channel == "system":
                    system_status = "error"
                else:
                    mic_status = "error"
                continue
            decision = consider_transcript(heard, channel=channel, paused=False, hotkey_phrase=hotkey_phrase)
            if decision.get("latch_pause") or decision.get("dropped") or decision.get("store"):
                notes.append(decision)
            if decision.get("store"):
                if channel == "system":
                    system_status = "hearing"
                else:
                    mic_status = "hearing"

    return {
        "model": whisper_model_name(),
        "system": _stream(
            enabled=system_enabled,
            paused=False,
            source=system_source,
            device=system_device,
            status=system_status,
        ),
        "mic": _stream(
            enabled=mic_enabled,
            paused=False,
            source=mic_source,
            device=mic_device,
            status=mic_status,
        ),
        "notes": notes,
    }


def _window_status(pcm: bytes, source: str) -> str:
    if source in {"off", "waiting"}:
        return source
    if not pcm or is_silence(pcm):
        return "silent"
    return "hearing"
