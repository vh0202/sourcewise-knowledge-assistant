"""Embedding-based retrieval behind the same ``Retriever`` interface.

NOTE: no embedding provider is integrated in this project. ``CosineRetriever`` is a reference
implementation that is unit-tested with a fake embedder; it shows where a real provider
(any function mapping texts to vectors) and a real vector store would plug in. Vectors are
held in memory and scanned linearly, which is fine for thousands of chunks, not millions.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Collection, Sequence
from typing import Protocol

from .base import IndexEntry, SearchHit


class Embedder(Protocol):
    """Anything that turns texts into fixed-length vectors."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _unit(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else [0.0 for _ in vector]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("vectors must have the same dimension")
    return sum(x * y for x, y in zip(_unit(a), _unit(b), strict=True))


class CosineRetriever:
    name = "cosine"
    label = "Cosine similarity (embeddings)"

    def __init__(self, embedder: Embedder, *, min_similarity: float = 0.0) -> None:
        self._embedder = embedder
        self._min_similarity = min_similarity
        self._vectors: dict[int, list[float]] = {}
        self._owner: dict[int, tuple[int, int]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _embedding_text(entry: IndexEntry) -> str:
        """Title and section are embedded with the passage so short chunks keep their context."""
        return "\n".join(part for part in (entry.title, entry.heading, entry.text) if part)

    def add(self, entries: Sequence[IndexEntry]) -> None:
        if not entries:
            return
        vectors = self._embedder.embed([self._embedding_text(entry) for entry in entries])
        if len(vectors) != len(entries):
            raise ValueError("embedder returned a different number of vectors than texts")
        with self._lock:
            for entry, vector in zip(entries, vectors, strict=True):
                self._vectors[entry.chunk_id] = _unit(vector)
                self._owner[entry.chunk_id] = (entry.document_id, entry.collection_id)

    def remove_document(self, document_id: int) -> None:
        with self._lock:
            for chunk_id in [cid for cid, (doc, _) in self._owner.items() if doc == document_id]:
                del self._vectors[chunk_id]
                del self._owner[chunk_id]

    def clear(self) -> None:
        with self._lock:
            self._vectors.clear()
            self._owner.clear()

    def chunk_count(self) -> int:
        return len(self._vectors)

    def search(
        self, query: str, *, top_k: int = 6, collection_ids: Collection[int] | None = None
    ) -> list[SearchHit]:
        if not query.strip():
            return []
        query_vector = _unit(self._embedder.embed([query])[0])
        allowed = set(collection_ids) if collection_ids is not None else None
        with self._lock:
            scored = [
                (chunk_id, sum(x * y for x, y in zip(query_vector, vector, strict=True)))
                for chunk_id, vector in self._vectors.items()
                if allowed is None or self._owner[chunk_id][1] in allowed
            ]
        ranked = sorted(
            (item for item in scored if item[1] > self._min_similarity),
            key=lambda item: (-item[1], item[0]),
        )
        return [SearchHit(chunk_id, score) for chunk_id, score in ranked[:top_k]]
