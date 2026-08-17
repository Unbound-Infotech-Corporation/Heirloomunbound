"""Shared studio defaults for audio + model routing.

Kept import-light so the desktop companion can copy the same dicts without
pulling FastAPI. The API layer (routers/studio.py) is the source of truth
for persistence; the companion applies whatever poll() ships.
"""
from __future__ import annotations

AUDIO_DEFAULTS: dict = {
    "input_device_id": "default",
    "output_device_id": "default",
    "input_gain": 100,  # 0–200, 100 = unity
    "output_volume": 80,  # 0–100, Heirloom's Windows-mixer session
    "mute_input": False,
    "mute_output": False,
    "noise_gate_db": -45,  # dBFS; below this is treated as silence
    "noise_suppression": True,
    "high_pass_hz": 80,  # rumble filter, 0 disables
    "monitor_input": False,  # listen to mic through selected output
    "sample_rate": 48000,
    "live_listen": False,  # always-on room listening with VAD
    "vad_hangover_ms": 900,
}

FEATURE_MODELS = (
    {
        "id": "stt",
        "label": "Speech to text",
        "purpose": "Transcribe your voice journal, push-to-talk, and live room listening.",
        "backends": (
            {"id": "auto", "label": "Auto (local Whisper if GPU, else cloud)"},
            {"id": "local_whisper", "label": "Local Whisper (this PC)"},
            {"id": "cloud_whisper", "label": "Cloud Whisper"},
        ),
        "default": "auto",
        "local_artifact": "faster-whisper-base",
    },
    {
        "id": "tts",
        "label": "Speech synthesis",
        "purpose": "The twin's spoken voice. Windows mixer volume applies here.",
        "backends": (
            {"id": "auto", "label": "Auto (cloned ElevenLabs if keyed, else OpenAI)"},
            {"id": "elevenlabs", "label": "ElevenLabs cloned voice"},
            {"id": "openai_tts", "label": "OpenAI TTS"},
            {"id": "local_piper", "label": "Local Piper (this PC)"},
        ),
        "default": "auto",
        "local_artifact": "piper-en_US-lessac-medium",
    },
    {
        "id": "twin",
        "label": "Twin LLM",
        "purpose": "The model that *is* you — grounded in the archive.",
        "backends": (
            {"id": "auto", "label": "Auto (Ollama if running, else Claude)"},
            {"id": "cloud_claude", "label": "Claude (cloud)"},
            {"id": "ollama", "label": "Ollama on this PC"},
        ),
        "default": "auto",
        "local_artifact": "llama3.1",
    },
    {
        "id": "vision",
        "label": "Screen vision",
        "purpose": "see_screen — the twin looks at your desktop.",
        "backends": (
            {"id": "auto", "label": "Auto"},
            {"id": "cloud_claude", "label": "Claude vision (cloud)"},
            {"id": "ollama", "label": "Ollama vision (llava)"},
        ),
        "default": "auto",
        "local_artifact": "llava",
    },
    {
        "id": "avatar",
        "label": "Talking head",
        "purpose": "Face + voice playback. Waveform needs no third-party key.",
        "backends": (
            {"id": "auto", "label": "Auto (D-ID if keyed, else waveform)"},
            {"id": "did", "label": "D-ID talking head"},
            {"id": "waveform", "label": "Portrait + waveform (local)"},
        ),
        "default": "auto",
        "local_artifact": None,
    },
)


def clamp_audio(raw: dict | None) -> dict:
    """Coerce a partial update onto AUDIO_DEFAULTS with hard bounds."""
    src = dict(AUDIO_DEFAULTS)
    if isinstance(raw, dict):
        src.update({k: v for k, v in raw.items() if k in AUDIO_DEFAULTS})
    src["input_device_id"] = str(src.get("input_device_id") or "default")[:200]
    src["output_device_id"] = str(src.get("output_device_id") or "default")[:200]
    src["input_gain"] = max(0, min(200, int(src.get("input_gain") or 100)))
    src["output_volume"] = max(0, min(100, int(src.get("output_volume") or 80)))
    src["mute_input"] = bool(src.get("mute_input"))
    src["mute_output"] = bool(src.get("mute_output"))
    src["noise_gate_db"] = max(-80, min(0, int(src.get("noise_gate_db") or -45)))
    src["noise_suppression"] = bool(src.get("noise_suppression"))
    src["high_pass_hz"] = max(0, min(400, int(src.get("high_pass_hz") or 80)))
    src["monitor_input"] = bool(src.get("monitor_input"))
    rate = int(src.get("sample_rate") or 48000)
    src["sample_rate"] = rate if rate in (16000, 44100, 48000) else 48000
    src["live_listen"] = bool(src.get("live_listen"))
    src["vad_hangover_ms"] = max(200, min(3000, int(src.get("vad_hangover_ms") or 900)))
    return src


def default_model_map() -> dict[str, str]:
    return {f["id"]: f["default"] for f in FEATURE_MODELS}


# Which user-managed credential each cloud backend needs (if any).
# None = app admin key or no key (local/waveform/auto).
BACKEND_CREDENTIALS: dict[str, dict] = {
    "elevenlabs": {
        "service": "elevenlabs",
        "label": "ElevenLabs API key",
        "save_path": "/voice-clone/api-key",
        "verify_service": "elevenlabs",
        "placeholder": "sk_…",
        "help": "Required for cloned-voice speech. Get one at elevenlabs.io → Profile → API Keys.",
    },
    "did": {
        "service": "did",
        "label": "D-ID API key",
        "save_path": "/avatar/api-key",
        "verify_service": "did",
        "placeholder": "email:secret",
        "help": "Required for talking-head video. Create at studio.d-id.com → Account → API.",
    },
    "fal": {
        "service": "fal",
        "label": "fal.ai API key",
        "save_path": "/avatar-studio/api-key",
        "verify_service": "fal",
        "placeholder": "key_id:key_secret",
        "help": "Optional — Avatar Studio beautify only, not required for twin speech.",
    },
}


def credential_for_backend(backend_id: str) -> dict | None:
    return BACKEND_CREDENTIALS.get(backend_id)


def backends_for_feature(feature_id: str) -> set[str]:
    for spec in FEATURE_MODELS:
        if spec["id"] == feature_id:
            return {b["id"] for b in spec["backends"]}
    return set()


def clamp_model_map(raw: dict | None) -> dict[str, str]:
    allowed = {f["id"]: {b["id"] for b in f["backends"]} for f in FEATURE_MODELS}
    out = default_model_map()
    if isinstance(raw, dict):
        for fid, backend in raw.items():
            if fid in allowed and str(backend) in allowed[fid]:
                out[fid] = str(backend)
    return out
