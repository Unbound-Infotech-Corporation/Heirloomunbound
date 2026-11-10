"""Local embeddings for dedup and retrieval. No network of its own."""
from __future__ import annotations

import hashlib
import math
import re

DUPLICATE_COSINE = 0.92


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_u = _unit(left)
    right_u = _unit(right)
    return sum(a * b for a, b in zip(left_u, right_u))


def is_duplicate_vector(vector: list[float], existing: list[list[float]], threshold: float = DUPLICATE_COSINE) -> bool:
    return any(cosine(vector, other) >= threshold for other in existing)


class OllamaEmbedder:
    """mxbai, then nomic, on the dedicated Ollama. A down server leaves the lexical gate in charge."""

    def __init__(self, endpoint: str, models: tuple[str, ...]):
        self.endpoint = endpoint.rstrip("/")
        self.models = models
        self._cache: dict[str, list[float]] = {}
        self._model: str | None = None
        self._down = False

    def __call__(self, text: str) -> list[float] | None:
        if self._down:
            return None
        key = (text or "")[:2000]
        if key in self._cache:
            return self._cache[key]
        import httpx

        order = ([self._model] if self._model else []) + [name for name in self.models if name != self._model]
        for model in order:
            try:
                response = httpx.post(
                    f"{self.endpoint}/api/embed",
                    json={"model": model, "input": key},
                    timeout=8.0,
                )
            except Exception:
                continue
            if response.status_code != 200:
                continue
            rows = (response.json() or {}).get("embeddings") or []
            if rows and isinstance(rows[0], list) and rows[0]:
                self._model = model
                vector = [float(value) for value in rows[0]]
                self._cache[key] = vector
                return vector
        self._down = True
        return None


def keyword_overlap(query: str, text: str) -> int:
    stops = {
        "the", "and", "for", "with", "that", "this", "from", "your", "about",
        "into", "what", "when", "where", "which", "have", "has", "was", "were",
        "are", "not", "but", "its", "their", "they", "you", "how", "can", "all",
    }
    def tokens(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", (value or "").lower())
            if len(token) > 3 and token not in stops
        }

    return len(tokens(query) & tokens(text))
