"""Lightweight semantic archive search.

Uses OpenAI embeddings when EMERGENT_LLM_KEY is available, with an in-process
cache + Mongo-stored vectors. Falls back to improved TF-IDF cosine similarity
(numpy) when embeddings are unavailable — still far better than bare regex.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from deps import EMERGENT_LLM_KEY, db

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_STOP = frozenset({
    "the", "a", "an", "of", "in", "on", "to", "for", "was", "is", "are", "be",
    "what", "where", "when", "who", "why", "how", "my", "me", "i", "did", "do",
    "does", "that", "this", "at", "with", "and", "you", "your", "or", "as",
    "it", "from", "by", "we", "they", "he", "she", "his", "her", "our",
})


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) > 2 and t not in _STOP]


def _tfidf_vec(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(tokens)
    n = len(tokens) or 1
    return {t: (c / n) * idf.get(t, 1.0) for t, c in counts.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b[t] for t in a if t in b)
    na = math.sqrt(sum(v * v for v in a.values())) or 1.0
    nb = math.sqrt(sum(v * v for v in b.values())) or 1.0
    return dot / (na * nb)


async def _load_entries(user_id: str, limit: int = 400) -> list[dict]:
    cursor = (
        db.entries.find(
            {"user_id": user_id},
            {"_id": 0, "entry_id": 1, "type": 1, "title": 1, "content": 1, "tags": 1, "created_at": 1},
        )
        .sort("created_at", -1)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


async def semantic_search(
    user_id: str,
    query: str,
    *,
    limit: int = 12,
) -> list[dict]:
    """Return top archive entries ranked by semantic/TF-IDF similarity."""
    q = (query or "").strip()
    if not q:
        return []
    entries = await _load_entries(user_id)
    if not entries:
        return []

    # Try OpenAI embeddings first
    embedded = await _embed_rank(user_id, q, entries, limit=limit)
    if embedded is not None:
        return embedded

    # TF-IDF fallback
    docs_tokens = []
    df: Counter = Counter()
    for e in entries:
        blob = f"{e.get('title','')} {e.get('content','')} {' '.join(e.get('tags') or [])}"
        toks = _tokens(blob)
        docs_tokens.append(toks)
        df.update(set(toks))
    n_docs = len(entries) or 1
    idf = {t: math.log((n_docs + 1) / (c + 1)) + 1.0 for t, c in df.items()}
    q_vec = _tfidf_vec(_tokens(q), idf)
    scored = []
    for e, toks in zip(entries, docs_tokens):
        score = _cosine(q_vec, _tfidf_vec(toks, idf))
        # slight boost for title hits
        title_l = (e.get("title") or "").lower()
        if any(t in title_l for t in _tokens(q)[:6]):
            score += 0.08
        if score > 0.02:
            scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


async def _embed_rank(
    user_id: str,
    query: str,
    entries: list[dict],
    *,
    limit: int,
) -> Optional[list[dict]]:
    if not EMERGENT_LLM_KEY:
        return None
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=EMERGENT_LLM_KEY)
        q_resp = await client.embeddings.create(
            model="text-embedding-3-small",
            input=query[:8000],
        )
        q_vec = q_resp.data[0].embedding
    except Exception:
        return None

    # Batch embed entries missing stored vectors (cap work per call)
    to_embed: list[tuple[int, str]] = []
    vectors: list[Optional[list[float]]] = [None] * len(entries)
    for i, e in enumerate(entries):
        cached = await db.entry_embeddings.find_one(
            {"user_id": user_id, "entry_id": e["entry_id"]},
            {"_id": 0, "vector": 1},
        )
        if cached and cached.get("vector"):
            vectors[i] = cached["vector"]
        else:
            blob = f"{e.get('title','')}\n{(e.get('content') or '')[:1500]}"
            to_embed.append((i, blob))

    if to_embed:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=EMERGENT_LLM_KEY)
            # Chunk to stay under request limits
            for start in range(0, len(to_embed), 64):
                chunk = to_embed[start : start + 64]
                resp = await client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[t[1][:8000] for t in chunk],
                )
                for (idx, _), row in zip(chunk, resp.data):
                    vectors[idx] = row.embedding
                    await db.entry_embeddings.update_one(
                        {"user_id": user_id, "entry_id": entries[idx]["entry_id"]},
                        {"$set": {
                            "user_id": user_id,
                            "entry_id": entries[idx]["entry_id"],
                            "vector": row.embedding,
                            "model": "text-embedding-3-small",
                        }},
                        upsert=True,
                    )
        except Exception:
            return None

    def cos(a, b):
        if not a or not b:
            return 0.0
        import numpy as np
        va = np.asarray(a, dtype=float)
        vb = np.asarray(b, dtype=float)
        denom = (np.linalg.norm(va) * np.linalg.norm(vb)) or 1.0
        return float(va.dot(vb) / denom)

    scored = []
    for e, vec in zip(entries, vectors):
        if not vec:
            continue
        scored.append((cos(q_vec, vec), e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]
