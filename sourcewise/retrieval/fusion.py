"""Hybrid retrieval by reciprocal rank fusion (RRF).

Combines any number of retrievers - typically one lexical and one vector - without having to
calibrate their incomparable scores: a chunk earns ``1 / (k + rank)`` from every retriever
that returns it, and the sums are ranked. (Cormack, Clarke & Buettcher, 2009.)
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence

from .base import IndexEntry, Retriever, SearchHit


class ReciprocalRankFusion:
    name = "rrf"

    def __init__(self, retrievers: Sequence[Retriever], *, k: int = 60, depth: int = 20) -> None:
        if not retrievers:
            raise ValueError("at least one retriever is required")
        self._retrievers = list(retrievers)
        self._k = k
        self._depth = depth
        self.label = "Hybrid RRF (" + " + ".join(r.label for r in self._retrievers) + ")"

    def add(self, entries: Sequence[IndexEntry]) -> None:
        for retriever in self._retrievers:
            retriever.add(entries)

    def remove_document(self, document_id: int) -> None:
        for retriever in self._retrievers:
            retriever.remove_document(document_id)

    def clear(self) -> None:
        for retriever in self._retrievers:
            retriever.clear()

    def search(
        self, query: str, *, top_k: int = 6, collection_ids: Collection[int] | None = None
    ) -> list[SearchHit]:
        fused: dict[int, float] = defaultdict(float)
        for retriever in self._retrievers:
            hits = retriever.search(query, top_k=max(top_k, self._depth), collection_ids=collection_ids)
            for rank, hit in enumerate(hits, start=1):
                fused[hit.chunk_id] += 1.0 / (self._k + rank)
        ranked = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
        return [SearchHit(chunk_id, score) for chunk_id, score in ranked[:top_k]]
