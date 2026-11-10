"""Find local models. The Study Hall Ollama is preferred. Cloud seats stay optional."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from studyhall.config import EMBED_MODELS, load_config

_SIZE = re.compile(r":(\d+(?:\.\d+)?)b\b", re.IGNORECASE)


@dataclass(frozen=True)
class FoundModel:
    model: str
    endpoint: str
    host: str
    kind: str  # ollama | openai


@dataclass(frozen=True)
class Seat:
    model: str
    endpoint: str
    host: str
    kind: str
    role: str

    def public(self) -> dict[str, str]:
        return {
            "model": self.model,
            "endpoint": self.endpoint,
            "host": self.host,
            "kind": self.kind,
            "role": self.role,
        }


def _size_of(name: str) -> float:
    match = _SIZE.search(name or "")
    if not match:
        return 99.0
    return float(match.group(1))


def is_embed_model(name: str) -> bool:
    stem = (name or "").split(":", 1)[0].lower()
    return stem in {item.split(":", 1)[0].lower() for item in EMBED_MODELS} or "embed" in stem


def _match(found: list[FoundModel], model: str, host: str) -> FoundModel | None:
    wanted = model.lower()
    on_host = [item for item in found if item.host == host and item.model.lower() == wanted]
    if on_host:
        return on_host[0]
    anywhere = [item for item in found if item.model.lower() == wanted]
    return anywhere[0] if anywhere else None


def assign_panel(found: list[FoundModel], config: dict | None = None) -> tuple[list[Seat], Seat | None]:
    """Readers from the configured mix, then the lightest moderator that is actually installed."""
    config = config or load_config()
    panel = config.get("panel") or {}
    readers: list[Seat] = []
    used: set[tuple[str, str]] = set()
    for spec in panel.get("readers") or []:
        if not isinstance(spec, dict):
            continue
        hit = _match(found, str(spec.get("model") or ""), str(spec.get("host") or "study"))
        if hit is None or is_embed_model(hit.model):
            continue
        key = (hit.host, hit.model)
        if key in used:
            continue
        used.add(key)
        readers.append(Seat(hit.model, hit.endpoint, hit.host, hit.kind, "reader"))

    moderator: Seat | None = None
    specs = []
    if isinstance(panel.get("moderator"), dict):
        specs.append(panel["moderator"])
    specs.extend(item for item in (panel.get("moderator_fallbacks") or []) if isinstance(item, dict))
    for spec in specs:
        hit = _match(found, str(spec.get("model") or ""), str(spec.get("host") or ""))
        if hit is None or is_embed_model(hit.model):
            continue
        moderator = Seat(hit.model, hit.endpoint, hit.host, hit.kind, "moderator")
        break
    if moderator is None:
        chat = [item for item in found if not is_embed_model(item.model)]
        chat.sort(key=lambda item: (_size_of(item.model), 0 if item.host == "study" else 1))
        if chat:
            hit = chat[0]
            moderator = Seat(hit.model, hit.endpoint, hit.host, hit.kind, "moderator")
    return readers, moderator


def choose_embedder(found: list[FoundModel], config: dict | None = None) -> FoundModel | None:
    config = config or load_config()
    for name in config.get("embed_models") or EMBED_MODELS:
        hit = _match(found, str(name), "study")
        if hit is not None:
            return hit
    for item in found:
        if is_embed_model(item.model):
            return item
    return None


def practice_panel(config: dict | None = None) -> tuple[list[Seat], Seat]:
    config = config or load_config()
    panel = config.get("panel") or {}
    readers = [
        Seat(str(spec["model"]), "practice", str(spec.get("host") or "study"), "practice", "reader")
        for spec in panel.get("readers") or []
        if isinstance(spec, dict) and spec.get("model")
    ]
    mod_spec = panel.get("moderator") or {"model": "llama3.1:8b", "host": "study"}
    moderator = Seat(str(mod_spec.get("model") or "llama3.1:8b"), "practice", str(mod_spec.get("host") or "study"), "practice", "moderator")
    return readers, moderator


async def _ollama_models(client: httpx.AsyncClient, url: str) -> list[str]:
    response = await client.get(url.rstrip("/") + "/api/tags")
    response.raise_for_status()
    payload = response.json()
    names = []
    for item in payload.get("models") or []:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return names


async def _openai_models(client: httpx.AsyncClient, url: str, key: str = "") -> list[str]:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    response = await client.get(url.rstrip("/") + "/v1/models", headers=headers)
    response.raise_for_status()
    payload = response.json()
    names = []
    for item in payload.get("data") or []:
        if isinstance(item, dict) and (item.get("id") or item.get("name")):
            names.append(str(item.get("id") or item.get("name")))
    return names


async def discover(config: dict | None = None, *, timeout: float = 0.8) -> dict[str, Any]:
    config = config or load_config()
    hosts: list[dict] = []
    found: list[FoundModel] = []
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        probes: list[tuple[str, str, str, str]] = []
        for item in config.get("ollama") or []:
            if isinstance(item, dict) and item.get("url"):
                probes.append((str(item.get("name") or "ollama"), str(item["url"]), "ollama", ""))
        local_servers = [url for url in (config.get("local_servers") or []) if isinstance(url, str) and url]
        if not local_servers:
            local_servers = ["http://127.0.0.1:8080"]
        for index, url in enumerate(local_servers):
            probes.append((f"local-{index + 1}", url, "openai", ""))
        for item in config.get("cloud") or []:
            if isinstance(item, dict) and item.get("url"):
                probes.append((str(item.get("name") or "cloud"), str(item["url"]), "cloud", str(item.get("key") or "")))

        for name, url, kind, key in probes:
            try:
                if kind == "ollama":
                    names = await _ollama_models(client, url)
                    listed_kind = "ollama"
                else:
                    names = await _openai_models(client, url, key)
                    listed_kind = "openai"
                hosts.append({"name": name, "url": url, "kind": listed_kind, "ok": True, "models": names})
                for model in names:
                    found.append(FoundModel(model, url.rstrip("/"), name, listed_kind))
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                hosts.append({"name": name, "url": url, "kind": "ollama" if kind == "ollama" else "openai", "ok": False, "models": []})

    readers, moderator = assign_panel(found, config)
    embedder = choose_embedder(found, config)
    return {
        "hosts": hosts,
        "readers": [seat.public() for seat in readers],
        "moderator": moderator.public() if moderator else None,
        "embedder": None if embedder is None else {
            "model": embedder.model,
            "endpoint": embedder.endpoint,
            "host": embedder.host,
        },
        "configured_readers": list((config.get("panel") or {}).get("readers") or []),
        "configured_moderator": (config.get("panel") or {}).get("moderator"),
    }
