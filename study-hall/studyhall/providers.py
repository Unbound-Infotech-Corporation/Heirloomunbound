"""Optional ChatGPT and Gemini seats. Keys stay in the data folder and are never logged."""
from __future__ import annotations

import time
from pathlib import Path

import httpx

from studyhall.discover import Seat

DEFAULTS = {
    "openai": {
        "enabled": False,
        "model": "gpt-4.1-mini",
        "moderator": False,
        "cap_hour": 20,
        "cap_day": 100,
        "choices": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o"],
    },
    "gemini": {
        "enabled": False,
        "model": "gemini-2.5-flash",
        "moderator": False,
        "cap_hour": 20,
        "cap_day": 100,
        "choices": ["gemini-2.5-flash", "gemini-2.5-pro"],
    },
}


def _blank() -> dict:
    return {
        "openai": {**DEFAULTS["openai"], "key": "", "uses": []},
        "gemini": {**DEFAULTS["gemini"], "key": "", "uses": []},
    }


def secrets_path(root: Path) -> Path:
    return Path(root) / "secrets.json"


def load_providers(root: Path) -> dict:
    path = secrets_path(root)
    stored = _blank()
    if path.is_file():
        try:
            import json
            loaded = json.loads(path.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            loaded = {}
        if isinstance(loaded, dict):
            for name in ("openai", "gemini"):
                row = loaded.get(name)
                if isinstance(row, dict):
                    stored[name].update({k: v for k, v in row.items() if k in stored[name] or k == "key" or k == "uses" or k == "choices"})
                    if not isinstance(stored[name].get("uses"), list):
                        stored[name]["uses"] = []
    return stored


def save_providers(root: Path, providers: dict) -> None:
    import json
    path = secrets_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(providers, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def mask_key(key: str) -> str:
    text = key or ""
    if not text:
        return ""
    tail = text[-4:] if len(text) >= 4 else text
    return "••••" + tail


def public_provider(name: str, row: dict) -> dict:
    now = time.time()
    uses = [float(item) for item in row.get("uses") or []]
    return {
        "name": name,
        "enabled": bool(row.get("enabled")),
        "model": row.get("model") or DEFAULTS[name]["model"],
        "moderator": bool(row.get("moderator")),
        "cap_hour": int(row.get("cap_hour") or DEFAULTS[name]["cap_hour"]),
        "cap_day": int(row.get("cap_day") or DEFAULTS[name]["cap_day"]),
        "choices": list(row.get("choices") or DEFAULTS[name]["choices"]),
        "key_set": bool(row.get("key")),
        "key_mask": mask_key(str(row.get("key") or "")),
        "used_hour": sum(1 for item in uses if now - item < 3600),
        "used_day": sum(1 for item in uses if now - item < 86400),
    }


def public_view(root: Path) -> dict:
    rows = load_providers(root)
    return {name: public_provider(name, row) for name, row in rows.items()}


def _trim(uses: list) -> list[float]:
    now = time.time()
    return [float(item) for item in uses if now - float(item) < 86400]


def within_cap(row: dict) -> bool:
    now = time.time()
    uses = _trim(row.get("uses") or [])
    hour = int(row.get("cap_hour") or 0)
    day = int(row.get("cap_day") or 0)
    if hour and sum(1 for item in uses if now - item < 3600) >= hour:
        return False
    if day and sum(1 for item in uses if now - item < 86400) >= day:
        return False
    return True


def record_use(root: Path, name: str) -> None:
    rows = load_providers(root)
    row = rows[name]
    row["uses"] = _trim(row.get("uses") or [])
    row["uses"].append(time.time())
    save_providers(root, rows)


def update_provider(root: Path, name: str, patch: dict) -> dict:
    if name not in DEFAULTS:
        raise KeyError(name)
    rows = load_providers(root)
    row = rows[name]
    for field in ("enabled", "model", "moderator", "cap_hour", "cap_day"):
        if field in patch and patch[field] is not None:
            row[field] = patch[field]
    if isinstance(patch.get("choices"), list) and patch["choices"]:
        row["choices"] = [str(item) for item in patch["choices"][:40]]
    if patch.get("key"):
        row["key"] = str(patch["key"]).strip()
    if patch.get("clear_key"):
        row["key"] = ""
    row["cap_hour"] = max(1, min(int(row.get("cap_hour") or 20), 500))
    row["cap_day"] = max(1, min(int(row.get("cap_day") or 100), 5000))
    row["uses"] = _trim(row.get("uses") or [])
    save_providers(root, rows)
    return public_provider(name, row)


def cloud_seats(root: Path) -> tuple[list[Seat], Seat | None]:
    """Enabled providers under their cap. No key means the seat does not exist."""
    readers: list[Seat] = []
    moderator: Seat | None = None
    for name, row in load_providers(root).items():
        if not row.get("enabled") or not str(row.get("key") or "").strip():
            continue
        if not within_cap(row):
            continue
        seat = Seat(str(row.get("model") or DEFAULTS[name]["model"]), name, name, name, "reader")
        readers.append(seat)
        if row.get("moderator"):
            moderator = Seat(seat.model, name, name, name, "moderator")
    return readers, moderator


async def list_models(name: str, key: str) -> list[str]:
    timeout = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        if name == "openai":
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
            response.raise_for_status()
            names = [str(item.get("id") or "") for item in response.json().get("data") or []]
            picked = [item for item in names if item.startswith(("gpt-4.1", "gpt-4o", "gpt-5"))]
            return picked[:30] or DEFAULTS["openai"]["choices"]
        response = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": key},
        )
        response.raise_for_status()
        names = []
        for item in response.json().get("models") or []:
            model = str(item.get("name") or "").split("/")[-1]
            if model.startswith("gemini"):
                names.append(model)
        return names[:30] or DEFAULTS["gemini"]["choices"]


async def provider_complete(seat: Seat, messages: list[dict], root: Path) -> str:
    rows = load_providers(root)
    row = rows.get(seat.kind) or {}
    key = str(row.get("key") or "")
    if not key or not within_cap(row):
        raise RuntimeError("cap")
    timeout = httpx.Timeout(90.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        if seat.kind == "openai":
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": seat.model, "messages": messages, "temperature": 0.2},
            )
            response.raise_for_status()
            record_use(root, "openai")
            choice = (response.json().get("choices") or [{}])[0]
            return str((choice.get("message") or {}).get("content") or "")
        contents = []
        system = ""
        for message in messages:
            if message.get("role") == "system":
                system = str(message.get("content") or "")
                continue
            contents.append({"role": "user", "parts": [{"text": str(message.get("content") or "")}]})
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{seat.model}:generateContent",
            headers={"x-goog-api-key": key},
            json={"systemInstruction": {"parts": [{"text": system}]}, "contents": contents},
        )
        response.raise_for_status()
        record_use(root, "gemini")
        parts = (((response.json().get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
        return "".join(str(part.get("text") or "") for part in parts)
