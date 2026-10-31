"""Heir and caller memory fence, applied in the retrieval query.

Private text is excluded by the Mongo filter that loads candidates. Nothing
in this module strips a passage after it has already been copied into a
prompt. Hybrid ranking runs only on the rows that filter returned.

Local embeddings are a hashed bag of words and character trigrams. They do
not call a network.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Callable, Iterable, Optional

from owner_pairing import is_owner_audience

EMBED_DIM = 256
OWNER_ONLY = ("owner", "private")
HEIR_LEVEL = ("heir", "family", "caller", "public")
CALLER_LEVEL = ("caller", "public")

_STOP = frozenset({
    "the", "a", "an", "of", "in", "on", "to", "for", "was", "is", "are",
    "what", "where", "when", "who", "why", "how", "my", "me", "i", "did",
    "do", "does", "that", "this", "at", "with", "and", "you", "your",
})


def retrieval_audience(audience: str | None) -> str:
    key = (audience or "owner").strip().lower() or "owner"
    if key not in {"owner", "heir", "caller"}:
        return "caller"
    return key


def visibility_clause(audience: str | None, *, kind: str = "entry") -> dict:
    """Mongo fragment. Empty for the owner, who can read every row.

    Entries and facts with no visibility field stay in the heir gift.
    Episodes are conversation summaries and stay owner-only until marked.
    Callers only receive rows explicitly marked caller or public.
    """
    key = retrieval_audience(audience)
    if is_owner_audience(key):
        return {}
    if key == "heir" and kind == "episode":
        return {"visibility": {"$in": list(HEIR_LEVEL)}}
    if key == "heir":
        return {"visibility": {"$nin": list(OWNER_ONLY)}}
    return {"visibility": {"$in": list(CALLER_LEVEL)}}


def mongo_query(
    user_id: str,
    audience: str | None,
    *,
    kind: str = "entry",
    extra: Optional[dict] = None,
) -> dict:
    """user_id plus the visibility filter, then an optional extra clause.

    Owner queries keep the historical shape `{user_id, ...extra}` so an
    owner search is unchanged. Heir and caller queries always include the
    visibility operator in the document Mongo evaluates.
    """
    base: dict[str, Any] = {"user_id": user_id}
    clause = visibility_clause(audience, kind=kind)
    if extra and clause:
        return {"$and": [base, clause, extra]}
    if extra:
        return {**base, **extra}
    if clause:
        return {"$and": [base, clause]}
    return base


def keywords(text: str) -> list[str]:
    return [
        token
        for token in re.split(r"\W+", (text or "").lower())
        if len(token) > 2 and token not in _STOP
    ]


def keyword_score(text: str, tokens: Iterable[str]) -> int:
    hay = (text or "").lower()
    score = 0
    for token in tokens:
        if token and token in hay:
            score += hay.count(token) + 2
    return score


def embed_local(text: str) -> list[float]:
    """Deterministic local vector. Same text always maps to the same point."""
    vec = [0.0] * EMBED_DIM
    tokens = re.findall(r"[a-z0-9']+", (text or "").lower())
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % EMBED_DIM
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vec[index] += sign
    compact = "".join(tokens)
    for start in range(max(0, len(compact) - 2)):
        gram = compact[start:start + 3]
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % EMBED_DIM
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vec[index] += 0.35 * sign
    norm = math.sqrt(sum(value * value for value in vec)) or 1.0
    return [value / norm for value in vec]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def cosine_unit(left: list[float], right: list[float]) -> float:
    """Map cosine from [-1, 1] onto [0, 1]."""
    value = (cosine(left, right) + 1.0) / 2.0
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def hybrid_rerank(
    docs: list[dict],
    query: str,
    *,
    limit: int = 8,
    text_of: Optional[Callable[[dict], str]] = None,
    keyword_weight: float = 0.45,
    embed_weight: float = 0.55,
) -> list[dict]:
    """Rerank rows already loaded under the visibility filter.

    A paraphrase with almost no keyword overlap can outrank a stray keyword
    hit when the local vectors agree.
    """
    if limit < 1 or not docs:
        return []
    reader = text_of or (lambda doc: str(doc.get("text") or doc.get("content") or ""))
    tokens = keywords(query)
    query_vec = embed_local(query)
    scored: list[tuple[float, int, dict]] = []
    raw_keywords: list[int] = []
    sims: list[float] = []
    texts: list[str] = []
    for doc in docs:
        text = reader(doc)
        texts.append(text)
        raw_keywords.append(keyword_score(text, tokens))
        sims.append(cosine_unit(query_vec, embed_local(text)))
    peak = max(raw_keywords) if raw_keywords else 0
    peak = peak or 1
    for index, doc in enumerate(docs):
        if tokens and raw_keywords[index] == 0 and sims[index] < 0.52:
            continue
        blended = keyword_weight * (raw_keywords[index] / peak) + embed_weight * sims[index]
        scored.append((blended, index, doc))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [doc for _score, _index, doc in scored[:limit]]


def matches_document(query: dict, doc: dict) -> bool:
    """Test double for the operators `mongo_query` emits. Not used at runtime."""
    if not isinstance(query, dict):
        return False
    for key, expected in query.items():
        if key == "$and":
            if not all(matches_document(part, doc) for part in expected):
                return False
            continue
        if key == "$or":
            if not any(matches_document(part, doc) for part in expected):
                return False
            continue
        if str(key).startswith("$"):
            return False
        if not _field_matches(doc, key, expected):
            return False
    return True


def _field_matches(doc: dict, key: str, expected: Any) -> bool:
    present = key in doc
    value = doc.get(key)
    if isinstance(expected, dict):
        if "$nin" in expected:
            if not present:
                return True
            return value not in expected["$nin"]
        if "$in" in expected:
            if not present:
                return False
            return value in expected["$in"]
        if "$regex" in expected:
            flags = re.IGNORECASE if "i" in str(expected.get("$options") or "") else 0
            pattern = str(expected.get("$regex") or "")
            values = value if isinstance(value, list) else [value]
            return any(re.search(pattern, str(item or ""), flags) for item in values)
        if "$exists" in expected:
            return present is bool(expected["$exists"])
        return False
    return present and value == expected
