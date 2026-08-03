"""Embeddings client — provider-agnostic wrapper around the user's configured
`embeddings` provider (from /api/providers).

The user's provider MUST be an OpenAI-compatible /v1/embeddings endpoint:
    * OpenAI itself (base_url=https://api.openai.com/v1, api_key=sk-…)
    * Ollama at 127.0.0.1:11434/v1 with nomic-embed-text
    * LM Studio, LocalAI, any Ollama-shaped server

Emergent Universal Key does NOT cover embeddings, so we don't ship a hosted
fallback — semantic features degrade to keyword search when no provider is
configured, and the UI nudges the user to set one up.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Optional

import httpx
import numpy as np

from deps import db

log = logging.getLogger("embeddings")


class NoProviderError(RuntimeError):
    """The user hasn't enabled an embeddings provider yet."""


async def get_config(user_id: str) -> Optional[dict]:
    """Return the enabled embeddings subsystem config for this user, or None."""
    doc = await db.user_providers.find_one(
        {"user_id": user_id}, {"_id": 0, "embeddings": 1}
    )
    if not doc:
        return None
    emb = doc.get("embeddings") or {}
    if not emb.get("enabled"):
        return None
    if not (emb.get("base_url") and emb.get("model")):
        return None
    return emb


async def has_provider(user_id: str) -> bool:
    return (await get_config(user_id)) is not None


def content_sha(text: str, model: str) -> str:
    """Stable hash used to skip re-embedding unchanged entries."""
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"\x1f")
    h.update((text or "").encode("utf-8"))
    return h.hexdigest()[:24]


def cosine_scores(query: list[float], docs: list[list[float]]) -> np.ndarray:
    """Batch cosine similarity — vectorised via numpy."""
    if not docs:
        return np.zeros(0, dtype=np.float32)
    q = np.asarray(query, dtype=np.float32)
    x = np.asarray(docs, dtype=np.float32)
    q_norm = float(np.linalg.norm(q))
    if q_norm == 0.0:
        return np.zeros(len(x), dtype=np.float32)
    x_norm = np.linalg.norm(x, axis=1)
    return (x @ q) / np.maximum(x_norm * q_norm, 1e-12)


async def embed_texts(user_id: str, texts: list[str]) -> list[list[float]]:
    """Batch-embed a list of texts using the user's configured provider.

    Preserves input order. Batches of 100 (OpenAI is comfortable with much
    more; we're conservative for local runtimes that may OOM).
    """
    cfg = await get_config(user_id)
    if cfg is None:
        raise NoProviderError("No embeddings provider is configured for this user")
    base = (cfg["base_url"] or "").rstrip("/")
    # Auto-add /v1 if missing so users can paste http://127.0.0.1:11434 and it just works
    if not base.endswith("/v1") and "/embeddings" not in base:
        base = base + "/v1"
    url = base + "/embeddings"
    model = cfg["model"]
    api_key = cfg.get("api_key") or ""

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for start in range(0, len(texts), 100):
            chunk = texts[start:start + 100]
            attempt = 0
            while True:
                try:
                    r = await client.post(url, headers=headers, json={
                        "model": model,
                        "input": chunk,
                    })
                    if r.status_code == 429 and attempt < 3:
                        attempt += 1
                        await asyncio.sleep(2 ** attempt)
                        continue
                    r.raise_for_status()
                    data = r.json()
                    items = data.get("data") or []
                    items.sort(key=lambda x: x.get("index", 0))
                    out.extend([item["embedding"] for item in items])
                    break
                except (httpx.HTTPError, KeyError) as exc:
                    log.warning("embed batch failed for user=%s: %s", user_id, exc)
                    raise
    return out
