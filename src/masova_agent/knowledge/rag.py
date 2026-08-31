"""Operations manual RAG: chunked markdown + lexical (CI) / embedding (live) search."""

from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CHUNK_WORDS = 400
_OVERLAP_WORDS = 80
_STOP = frozenset(
    "a an the and or of to for in on at is are be with by from as that this it".split()
)

# In-memory chunk cache (CI / single Cloud Run instance)
_CHUNKS: list[dict[str, Any]] | None = None

# In-memory chunk embedding cache, keyed by (model, chunk text) — computed once
# per process instead of once per query, so repeat searches embed only the
# query itself instead of re-embedding the whole corpus every call.
_EMBED_CACHE: dict[tuple[str, str], list[float]] = {}


def _knowledge_dir() -> Path:
    env = os.getenv("OPS_KNOWLEDGE_DIR")
    if env:
        return Path(env)
    # src/masova_agent/knowledge/rag.py → repo root data/knowledge
    return Path(__file__).resolve().parents[3] / "data" / "knowledge"


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9°]+", text.lower()) if t not in _STOP and len(t) > 1]


def _chunk_markdown(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    title = path.stem.replace("_", " ")
    category = path.stem
    # Split on ## headings when present; else whole file
    sections: list[tuple[str, str]] = []
    parts = re.split(r"(?m)^(## .+)$", raw)
    if len(parts) == 1:
        sections.append((title, raw))
    else:
        preamble = parts[0].strip()
        if preamble:
            sections.append((title, preamble))
        for i in range(1, len(parts), 2):
            heading = parts[i].lstrip("# ").strip()
            body = parts[i + 1] if i + 1 < len(parts) else ""
            sections.append((heading, body))

    chunks: list[dict[str, Any]] = []
    for section, body in sections:
        words = body.split()
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(len(words), start + _CHUNK_WORDS)
            text = " ".join(words[start:end]).strip()
            if text:
                chunks.append(
                    {
                        "title": title,
                        "section": section,
                        "category": category,
                        "text": text,
                        "tokens": _tokenize(f"{section} {text}"),
                    }
                )
            if end >= len(words):
                break
            start = max(end - _OVERLAP_WORDS, start + 1)
    return chunks


def load_chunks(force: bool = False) -> list[dict[str, Any]]:
    global _CHUNKS
    if _CHUNKS is not None and not force:
        return _CHUNKS
    root = _knowledge_dir()
    found: list[dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*.md")):
            found.extend(_chunk_markdown(path))
    _CHUNKS = found
    return found


def _lexical_score(query_tokens: list[str], chunk_tokens: list[str]) -> float:
    if not query_tokens or not chunk_tokens:
        return 0.0
    qset = set(query_tokens)
    cset = set(chunk_tokens)
    overlap = len(qset & cset)
    if overlap == 0:
        # soft match on substrings (e.g. temp ↔ temperature)
        soft = 0
        for qt in qset:
            for ct in cset:
                if qt in ct or ct in qt:
                    soft += 1
                    break
        if soft == 0:
            return 0.0
        overlap = soft
    return overlap / math.sqrt(len(qset) * max(1, len(cset) ** 0.25))


async def _embed_search(query: str, chunks: list[dict[str, Any]], top_k: int) -> Optional[list[dict[str, Any]]]:
    """Optional Gemini embedding path. Returns None to fall back to lexical."""
    from ..runtime.ops_llm import llm_available, make_genai_client

    if not llm_available():
        return None
    try:
        client = make_genai_client()
        model = os.getenv("OPS_EMBED_MODEL", "text-embedding-004")
        q_emb = client.models.embed_content(model=model, contents=query)
        q_vec = list(getattr(q_emb, "embeddings", [None])[0].values)  # type: ignore[union-attr]
        nq = math.sqrt(sum(a * a for a in q_vec)) or 1.0

        # Chunk embeddings are stable for a given (model, text) — cache them so
        # repeat queries against the same corpus embed only the query, not
        # every chunk again (this was the ~77s-per-turn latency source).
        uncached = [ch for ch in chunks if (model, ch["text"]) not in _EMBED_CACHE]
        for ch in uncached:
            text = f"{ch['section']}\n{ch['text']}"
            e = client.models.embed_content(model=model, contents=text)
            vec = list(getattr(e, "embeddings", [None])[0].values)  # type: ignore[union-attr]
            _EMBED_CACHE[(model, ch["text"])] = vec

        scored: list[tuple[float, dict[str, Any]]] = []
        for ch in chunks:
            vec = _EMBED_CACHE[(model, ch["text"])]
            dot = sum(a * b for a, b in zip(q_vec, vec))
            nv = math.sqrt(sum(a * a for a in vec)) or 1.0
            scored.append((dot / (nq * nv), ch))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for score, ch in scored[:top_k]:
            hits.append(
                {
                    "title": ch["title"],
                    "section": ch["section"],
                    "text": ch["text"],
                    "score": round(float(score), 4),
                }
            )
        return hits
    except Exception as e:
        logger.warning("embed search failed, lexical fallback: %s", e)
        return None


def _lexical_hits(query: str, chunks: list[dict[str, Any]], top_k: int = 5) -> list[dict[str, Any]]:
    q_tokens = _tokenize(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for ch in chunks:
        score = _lexical_score(q_tokens, ch.get("tokens") or _tokenize(ch["text"]))
        if score > 0:
            scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "title": ch["title"],
            "section": ch["section"],
            "text": ch["text"],
            "score": round(score, 4),
        }
        for score, ch in scored[:top_k]
    ]


async def search_ops_manual(query: str, category: str = "") -> dict[str, Any]:
    """
    Search the checked-in ops manuals.

    Lexical token overlap runs first (no network, sub-millisecond) — for a
    small, fixed corpus like ours it resolves the vast majority of ops
    questions directly. Only falls through to Gemini embeddings when lexical
    finds nothing, since that's a real network round-trip per uncached chunk.
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "empty_query", "hits": []}

    chunks = load_chunks()
    if category:
        cat = category.strip().lower().replace(" ", "_")
        chunks = [c for c in chunks if cat in c.get("category", "").lower() or cat in c.get("title", "").lower()]

    if not chunks:
        return {"ok": True, "hits": [], "mode": "empty_corpus"}

    hits = _lexical_hits(q, chunks, top_k=5)
    if hits:
        return {"ok": True, "hits": hits, "mode": "lexical"}

    embedded = await _embed_search(q, chunks, top_k=5)
    if embedded is not None:
        return {"ok": True, "hits": embedded, "mode": "embedding"}

    return {"ok": True, "hits": [], "mode": "lexical"}
