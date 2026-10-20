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
        "purpose": "The twin's spoken voice. Local clone engines (Voicebox, Qwen3-TTS) first when ready; Windows mixer volume applies here.",
        "backends": (
            {"id": "auto", "label": "Auto (Voicebox / Qwen3-TTS on this PC if ready, else cloned ElevenLabs, else Piper / OpenAI)"},
            {"id": "voicebox", "label": "Voicebox on this PC"},
            {"id": "qwen3_tts", "label": "Qwen3-TTS on this PC"},
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
        "purpose": "Face + voice playback. Local LatentSync lipsync first when the engine is listening; waveform needs no third-party key.",
        "backends": (
            {"id": "auto", "label": "Auto (LatentSync / MuseTalk on this PC if ready, else waveform, else D-ID)"},
            {"id": "latentsync", "label": "LatentSync on this PC"},
            {"id": "musetalk", "label": "MuseTalk on this PC"},
            {"id": "did", "label": "D-ID talking head"},
            {"id": "waveform", "label": "Portrait + waveform (local)"},
        ),
        "default": "auto",
        "local_artifact": None,
    },
    {
        "id": "assist",
        "label": "Assist",
        "purpose": "Do on this PC. Auto classifies each request (code, reasoning, research, quick chat, vision) and runs the local model you set for that category. Cloud stays off until you turn it on.",
        "backends": (
            {"id": "auto", "label": "Auto (task router)"},
            {"id": "manual", "label": "Manual model"},
        ),
        "default": "auto",
        "local_artifact": "qwen2.5-coder:7b",
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


# Where local GPU / Whisper / Piper run, and optionally where Ollama lives.
# - local: the companion PC that most recently checked in (typical dedicated box)
# - network: a specific registered companion device elsewhere on the LAN
# - server: Ollama on a remote URL; Whisper/Piper still use the chosen PC
# Local HTTP engines install standalone (Voicebox MSI/Docker, Qwen3-TTS pip/Docker,
# LatentSync/MuseTalk). Heirloom Unbound probes them like Ollama — no Pinokio.
ENGINE_URL_DEFAULTS: dict[str, str] = {
    "ollama_url": "http://127.0.0.1:11434",
    "llamacpp_url": "http://127.0.0.1:8080/v1",
    "voicebox_url": "http://127.0.0.1:17493",
    "qwen3_tts_url": "http://127.0.0.1:8001",
    "latentsync_url": "http://127.0.0.1:7860",
    "musetalk_url": "http://127.0.0.1:7861",
}

# Assist (Do / PC) task router. Local OpenAI-compatible servers only unless
# the owner opts into cloud. A spec matches an installed name when they are
# equal or the installed name is "<spec>:<tag>". "qwen3" does not match
# "qwen3-coder".
ASSIST_CATEGORIES = ("code", "reasoning", "research", "chat", "vision")
ASSIST_CATEGORY_LABELS = {
    "code": "Code",
    "reasoning": "Reasoning",
    "research": "Research",
    "chat": "Quick chat",
    "vision": "Vision",
}
ASSIST_BACKENDS = ("ollama", "llamacpp", "cloud")
ASSIST_PICKERS = ("auto", "manual")
ASSIST_OPINION_MODES = ("auto", "off", "always")
ASSIST_DEFAULT_CHAINS: dict[str, tuple[tuple[str, str], ...]] = {
    "code": (
        ("ollama", "qwen3-coder"),
        ("ollama", "deepseek-coder-v2"),
        ("ollama", "qwen2.5-coder"),
        ("llamacpp", "qwen3-coder"),
        ("llamacpp", "deepseek-coder"),
    ),
    "reasoning": (
        ("ollama", "deepseek-r1"),
        ("ollama", "qwen3"),
        ("llamacpp", "deepseek-r1"),
        ("ollama", "llama3.1"),
    ),
    "research": (
        ("ollama", "qwen3"),
        ("ollama", "llama3.1"),
        ("llamacpp", "qwen3"),
    ),
    "chat": (
        ("ollama", "qwen2.5:3b"),
        ("ollama", "llama3.2:3b"),
        ("llamacpp", "qwen2.5-3b"),
        ("ollama", "llama3.2"),
    ),
    "vision": (
        ("ollama", "qwen2.5vl"),
        ("ollama", "llava"),
        ("llamacpp", "llava"),
    ),
}

# Which local Assist models each install size pulls. Small pulls none.
ASSIST_TIER_MODELS: dict[str, tuple[str, ...]] = {
    "small": (),
    "medium": ("qwen2.5-coder:7b", "qwen2.5:3b"),
    "large": (
        "qwen2.5-coder:7b",
        "qwen2.5-coder:32b",
        "deepseek-r1:14b",
        "qwen2.5:3b",
        "qwen2.5vl:7b",
    ),
    "dedicated": (
        "qwen2.5-coder:7b",
        "qwen2.5-coder:32b",
        "qwen3-coder",
        "deepseek-coder-v2",
        "deepseek-r1:14b",
        "deepseek-r1:32b",
        "qwen2.5:3b",
        "qwen2.5vl:7b",
    ),
}

COMPUTE_DEFAULTS: dict = {
    "mode": "local",  # local | network | server
    "device_id": None,  # companion_devices.device_id when mode=network
    "remote": {
        "label": "",
        **ENGINE_URL_DEFAULTS,
    },
}


def clamp_compute(raw: dict | None) -> dict:
    """Coerce partial studio_compute onto COMPUTE_DEFAULTS."""
    src = {
        "mode": COMPUTE_DEFAULTS["mode"],
        "device_id": COMPUTE_DEFAULTS["device_id"],
        "remote": dict(COMPUTE_DEFAULTS["remote"]),
    }
    if isinstance(raw, dict):
        if raw.get("mode") in ("local", "network", "server"):
            src["mode"] = raw["mode"]
        if "device_id" in raw:
            did = raw.get("device_id")
            src["device_id"] = str(did).strip()[:64] if did else None
        remote = raw.get("remote")
        if isinstance(remote, dict):
            label = str(remote.get("label") or "").strip()[:120]
            merged_remote = {"label": label}
            for key, default in ENGINE_URL_DEFAULTS.items():
                url = str(remote.get(key) or default).strip()
                if not url.startswith(("http://", "https://")):
                    url = default
                merged_remote[key] = url[:512]
            src["remote"] = merged_remote
    if src["mode"] != "network":
        src["device_id"] = None
    return src


def default_assist_chains() -> dict[str, list[dict[str, str]]]:
    return {
        cat: [{"backend": backend, "model": model} for backend, model in slots]
        for cat, slots in ASSIST_DEFAULT_CHAINS.items()
    }


def _clean_route_slot(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    backend = str(raw.get("backend") or "").strip().lower()
    model = str(raw.get("model") or "").strip()
    if backend not in ASSIST_BACKENDS:
        return None
    if not model or len(model) > 80:
        return None
    if any(ch.isspace() for ch in model):
        return None
    return {"backend": backend, "model": model}


def clamp_assist_settings(raw: dict | None) -> dict:
    """Coerce studio_assist. Unknown categories and slots are dropped."""
    out = {
        "picker": "auto",
        "manual_backend": "ollama",
        "manual_model": "",
        "second_opinion": "auto",
        "cloud": {"enabled": False, "base_url": "", "model": ""},
        "routes": default_assist_chains(),
    }
    if not isinstance(raw, dict):
        return out
    picker = str(raw.get("picker") or "").strip().lower()
    if picker in ASSIST_PICKERS:
        out["picker"] = picker
    manual_backend = str(raw.get("manual_backend") or "").strip().lower()
    if manual_backend in ASSIST_BACKENDS:
        out["manual_backend"] = manual_backend
    manual_model = str(raw.get("manual_model") or "").strip()
    if manual_model and len(manual_model) <= 80 and not any(ch.isspace() for ch in manual_model):
        out["manual_model"] = manual_model
    opinion = str(raw.get("second_opinion") or "").strip().lower()
    if opinion in ASSIST_OPINION_MODES:
        out["second_opinion"] = opinion
    cloud = raw.get("cloud") if isinstance(raw.get("cloud"), dict) else {}
    enabled = bool(cloud.get("enabled"))
    base_url = str(cloud.get("base_url") or "").strip()
    if base_url and not base_url.startswith(("http://", "https://")):
        base_url = ""
    cloud_model = str(cloud.get("model") or "").strip()
    if len(cloud_model) > 80 or any(ch.isspace() for ch in cloud_model):
        cloud_model = ""
    out["cloud"] = {
        "enabled": enabled,
        "base_url": base_url[:512],
        "model": cloud_model,
    }
    routes_raw = raw.get("routes")
    if isinstance(routes_raw, dict):
        routes = default_assist_chains()
        for cat in ASSIST_CATEGORIES:
            if cat not in routes_raw:
                continue
            slots = routes_raw.get(cat)
            if not isinstance(slots, list):
                continue
            cleaned = []
            for slot in slots[:6]:
                item = _clean_route_slot(slot)
                if item:
                    cleaned.append(item)
            routes[cat] = cleaned
        out["routes"] = routes
    return out


def engine_url(compute: dict | None, key: str) -> str:
    """Return a clamped local-engine URL from studio_compute or the default."""
    defaults = ENGINE_URL_DEFAULTS
    if key not in defaults:
        return ""
    remote = (compute or {}).get("remote") if isinstance(compute, dict) else None
    if isinstance(remote, dict):
        url = str(remote.get(key) or defaults[key]).strip()
        if url.startswith(("http://", "https://")):
            return url.rstrip("/")[:512]
    return defaults[key].rstrip("/")
