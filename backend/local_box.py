"""Heirloom on one Windows (or Linux/macOS) PC, no Twin Box: plan, configure, run, check.

The Windows installer (desktop/installer/local-box/Install-HeirloomLocal.ps1) calls this
after it has Python. Everything is per-user: no admin, no WSL, no reboot.

  python -m local_box plan  --data DIR [--model TAG]
  python -m local_box init  --data DIR --web DIR [--api-port 8001] [--mongo-port 27017]
                            [--ollama http://127.0.0.1:11434] [--model TAG] [--voice auto|on|off]
  python -m local_box set-owner --data DIR --email you@example.com   (password on stdin)
  python -m local_box serve --data DIR
  python -m local_box check --data DIR [--chat]

The data folder holds heirloom.env, the database, the vault, and the owner password hash.
Only local models are configured; there is no cloud key in heirloom.env.
"""
from __future__ import annotations

import getpass
import json
import os
import secrets
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

ENV_FILE = "heirloom.env"
EMBED_MODEL = "nomic-embed-text"
# Download sizes (GB) measured with `ollama list`, November 2026.
MODEL_GB = {
    "gemma4:26b": 17.5, "gemma4:12b": 7.5, "gemma4:e4b": 6.2, "gemma4:e2b": 4.3,
    "qwen3.5:4b": 3.1, "qwen2.5:14b": 9.0, "nomic-embed-text": 0.3,
}
# Python packages, the database, hearing, plus room to grow.
BASE_GB = 6.0
VOICE_GB = 6.0  # Chatterbox with CUDA torch
SECRET_KEYS = ("CONNECTOR_SECRET_KEY",)


def _dirs(data: Path) -> dict[str, Path]:
    return {
        "data": data,
        "mongo": data / "mongo",
        "owner": data / "owner",
        "vault": data / "vault",
        "files": data / "files",
        "skills": data / "skills",
        "whisper": data / "whisper",
        "logs": data / "logs",
        "objects": data / "objects",
    }


def read_env(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return found
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        found[key.strip()] = value.strip()
    return found


def write_env(path: Path, values: dict[str, str]) -> None:
    lines = ["# Heirloom local box. Written by the installer; local models only.", ""]
    lines += [f"{k}={v}" for k, v in values.items()]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
    _private(path)


def _private(path: Path) -> None:
    """Owner-only file. On Windows the per-user profile already limits it; chmod for the rest."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def need_gb(model: str, voice: bool) -> float:
    return round(BASE_GB + MODEL_GB.get(model, 10.0) + MODEL_GB[EMBED_MODEL] + (VOICE_GB if voice else 0.0), 1)


def free_gb(path: Path) -> float:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return round(shutil.disk_usage(probe).free / 1024 ** 3, 1)


def plan(data: Path, model: str = "", voice: str = "auto", hardware=None) -> dict:
    import model_tiers

    picked = model_tiers.choose(hardware)
    tier = next(t for t in model_tiers.TIERS if t.name == picked.tier)
    chosen = model or picked.model
    gpu_voice = tier.voice_on_gpu
    voice_on = voice == "on" or (voice == "auto" and gpu_voice)
    hw = picked.hardware or {}
    whisper_device = "cuda" if hw.get("vendor") == "nvidia" and int(hw.get("vram_mib") or 0) >= 6144 else "cpu"
    need = need_gb(chosen, voice_on)
    have = free_gb(data)
    return {
        "tier": tier.name,
        "label": tier.label,
        "model": chosen,
        "fallback": tier.fallback,
        "num_ctx": tier.num_ctx,
        "reason": picked.reason if not model else f"--model {model}",
        "hardware": hw,
        "voice": voice_on,
        "voice_device": "cuda" if (voice_on and gpu_voice) else "cpu",
        "whisper_device": whisper_device,
        "need_gb": need,
        "free_gb": have,
        "disk_ok": have >= need,
    }


def init(data: Path, web: Path, *, api_port: int = 8001, mongo_port: int = 27017,
         ollama: str = "http://127.0.0.1:11434", model: str = "", voice: str = "auto", chosen: Optional[dict] = None) -> dict:
    for path in _dirs(data).values():
        path.mkdir(parents=True, exist_ok=True)
    env_path = data / ENV_FILE
    old = read_env(env_path)
    picked = chosen or plan(data, model, voice)
    values = {
        "MONGO_URL": f"mongodb://127.0.0.1:{mongo_port}",
        "DB_NAME": "heirloom",
        "HEIRLOOM_BOX": "1",
        "HEIRLOOM_LOCAL_PC": "1",
        "HEIRLOOM_API_PORT": str(api_port),
        "HEIRLOOM_MONGO_PORT": str(mongo_port),
        "HEIRLOOM_DATA_ROOT": str(data),
        "HEIRLOOM_DATA_DIR": str(data),
        "HEIRLOOM_PAUSE_FILE": str(data / "pause.json"),
        "HEIRLOOM_OWNER_PASSWORD_FILE": str(data / "owner" / "owner.pass"),
        # Linux defaults live under /var/lib/heirloom; on a PC everything stays in this data folder.
        "HEIRLOOM_OBSERVER_DIR": str(data / "observer"),
        "HEIRLOOM_PRESENCE_DIR": str(data / "presence"),
        "HEIRLOOM_LAB_DIR": str(data / "lab"),
        "HEIRLOOM_LAB_REPORT_DIR": str(data / "lab-reports"),
        "HEIRLOOM_WEB_DIR": str(web),
        "HEIRLOOM_LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": ollama.rstrip("/"),
        "OLLAMA_TWIN_MODEL": picked["model"],
        "HEIRLOOM_MODEL_TIER": picked["tier"],
        "OLLAMA_CONTEXT_LENGTH": str(picked["num_ctx"]),
        "WHISPER_MODEL": "base",
        "WHISPER_DEVICE": picked["whisper_device"],
        "WHISPER_CACHE": str(data / "whisper"),
        "HEIRLOOM_VOICE": "1" if picked["voice"] else "0",
        "PRESENCE_SPEAK_URL": "http://127.0.0.1:8010/speak",
        "HEIRLOOM_AI_DISCLOSURE": "1",
    }
    for key in SECRET_KEYS:
        values[key] = old.get(key) or secrets.token_urlsafe(48)
    # Keep anything the owner added by hand (for example HEIRLOOM_SEARXNG_URL or OAuth client ids).
    for key, value in old.items():
        values.setdefault(key, value)
    write_env(env_path, values)
    pause = data / "pause.json"
    if not pause.exists():
        pause.write_text('{"paused": false, "reason": ""}\n', encoding="utf-8")
    return {"env": str(env_path), **picked}


def load_env(data: Path) -> dict[str, str]:
    values = read_env(data / ENV_FILE)
    if not values:
        raise SystemExit(f"No {ENV_FILE} in {data}. Run: python -m local_box init --data {data} --web WEB")
    os.environ.update(values)
    return values


def set_owner(data: Path, email: str, password: str) -> None:
    load_env(data)
    from box_owner import set_owner_password

    set_owner_password(email, password, Path(os.environ["HEIRLOOM_OWNER_PASSWORD_FILE"]))
    _private(Path(os.environ["HEIRLOOM_OWNER_PASSWORD_FILE"]))


def _cuda_dll_dirs() -> list[str]:
    """faster-whisper on Windows finds cuBLAS/cuDNN from the nvidia-* pip wheels."""
    found = []
    for base in map(Path, sys.path):
        nvidia = base / "nvidia"
        if nvidia.is_dir():
            for sub in ("cublas", "cudnn"):
                for name in ("bin", "lib"):
                    path = nvidia / sub / name
                    if path.is_dir():
                        found.append(str(path))
    return found


def serve(data: Path) -> None:
    values = load_env(data)
    for path in _cuda_dll_dirs():
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(path)
        os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
    os.chdir(Path(__file__).resolve().parent)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=int(values.get("HEIRLOOM_API_PORT") or 8001), log_level="warning")


def _get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback only
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def _post(url: str, body: dict, timeout: float = 120.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - loopback only
        return json.loads(response.read().decode("utf-8"))


def check(data: Path, chat: bool = False, wait: float = 0.0) -> dict:
    values = load_env(data)
    port = values.get("HEIRLOOM_API_PORT") or "8001"
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + wait
    status, _ = _get(base + "/api/health", 5)
    while status != 200 and time.time() < deadline:
        time.sleep(2)
        status, _ = _get(base + "/api/health", 5)
    rows = {"api": status == 200}
    web_status, page = _get(base + "/", 10)
    rows["web"] = web_status == 200 and "<div id=\"root\"" in page
    route_status, _ = _get(base + "/life-story", 10)
    rows["web_routes"] = route_status == 200
    tags_status, tags = _get(values["OLLAMA_BASE_URL"] + "/api/tags", 10)
    names = [m.get("name", "") for m in json.loads(tags).get("models", [])] if tags_status == 200 else []
    model = values.get("OLLAMA_TWIN_MODEL", "")
    rows["ollama"] = tags_status == 200
    rows["model_pulled"] = any(n == model or n == model + ":latest" for n in names)
    rows["embed_pulled"] = any(n.startswith(EMBED_MODEL) for n in names)
    from box_owner import owner_configured

    rows["owner_set"] = owner_configured(Path(values["HEIRLOOM_OWNER_PASSWORD_FILE"]))
    if chat and rows["model_pulled"]:
        import model_tiers

        started = time.perf_counter()
        try:
            reply = _post(values["OLLAMA_BASE_URL"] + "/api/chat", {
                "model": model, "stream": False, "think": model_tiers.think_value(model, values["OLLAMA_BASE_URL"]),
                "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
                "options": {"num_ctx": int(values.get("OLLAMA_CONTEXT_LENGTH") or 8192)},
            })
            rows["chat"] = "ready" in (reply.get("message", {}).get("content", "").lower())
        except Exception:  # noqa: BLE001
            rows["chat"] = False
        rows["chat_seconds"] = round(time.perf_counter() - started, 2)
    ok = all(v for k, v in rows.items() if not k.endswith("_seconds"))
    return {"ok": ok, "url": base + "/", "model": model, "checks": rows}


def _arg(args: list[str], flag: str, default: str = "") -> str:
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, args = argv[0], argv[1:]
    data = Path(_arg(args, "--data") or os.environ.get("HEIRLOOM_DATA_ROOT") or Path.home() / "HeirloomData").expanduser()
    if command == "plan":
        print(json.dumps(plan(data, _arg(args, "--model"), _arg(args, "--voice", "auto")), indent=2))
        return 0
    if command == "init":
        web = Path(_arg(args, "--web") or Path(__file__).resolve().parent.parent / "web")
        out = init(data, web, api_port=int(_arg(args, "--api-port", "8001")), mongo_port=int(_arg(args, "--mongo-port", "27017")),
                   ollama=_arg(args, "--ollama", "http://127.0.0.1:11434"), model=_arg(args, "--model"), voice=_arg(args, "--voice", "auto"))
        print(json.dumps(out, indent=2))
        return 0
    if command == "set-owner":
        email = _arg(args, "--email")
        if sys.stdin.isatty():
            password = getpass.getpass("Choose an owner password (8 or more characters): ")
            if getpass.getpass("Type it again: ") != password:
                print("The two passwords did not match.", file=sys.stderr)
                return 1
        else:
            password = sys.stdin.readline().rstrip("\r\n")
        try:
            set_owner(data, email, password)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Owner sign-in saved for {email.strip().lower()}.")
        return 0
    if command == "serve":
        serve(data)
        return 0
    if command == "check":
        out = check(data, chat="--chat" in args, wait=float(_arg(args, "--wait", "0")))
        print(json.dumps(out, indent=2))
        return 0 if out["ok"] else 1
    if command == "env":
        for key, value in read_env(data / ENV_FILE).items():
            if key not in SECRET_KEYS:
                print(f"{key}={value}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
