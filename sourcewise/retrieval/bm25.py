"""Okapi BM25 in pure Python.

Used when the local SQLite build has no FTS5 extension (or when ``SOURCEWISE_RETRIEVER=bm25``).
The scoring function deliberately mirrors SQLite FTS5's ``bm25()`` - same k1, b, IDF and field
weighting - so both lexical retrievers rank identically and are tested against each other.

    score(q, d) = sum over query terms t of
                  idf(t) * f(t, d) * (k1 + 1) / (f(t, d) + k1 * (1 - b + b * |d| / avgdl))

    idf(t)  = ln((N - n_t + 0.5) / (n_t + 0.5)), floored at 1e-6 for terms in most chunks
    f(t, d) = sum over fields of (occurrences of t in the field) * (field weight)
    |d|     = number of terms in all fields of the chunk
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence

from ..text.analyzer import analyze, query_terms
from .base import DEFAULT_WEIGHTS, FieldWeights, IndexEntry, SearchHit

K1 = 1.2
B = 0.75
_IDF_FLOOR = 1e-6


def bm25_idf(chunk_count: int, document_frequency: int) -> float:
    idf = math.log((chunk_count - document_frequency + 0.5) / (document_frequency + 0.5))
    return idf if idf > 0 else _IDF_FLOOR


class BM25Retriever:
    name = "bm25"
    label = "BM25 (pure Python)"

    def __init__(self, weights: FieldWeights = DEFAULT_WEIGHTS) -> None:
        self._weights = weights
        self._postings: dict[str, dict[int, float]] = defaultdict(dict)  # term -> chunk -> weighted tf
        self._terms: dict[int, tuple[str, ...]] = {}  # chunk -> its distinct terms (for removal)
        self._length: dict[int, int] = {}  # chunk -> |d|
        self._owner: dict[int, tuple[int, int]] = {}  # chunk -> (document_id, collection_id)
        self._total_length = 0
        self._lock = threading.RLock()

    # -- indexing --------------------------------------------------------------------------
    def add(self, entries: Sequence[IndexEntry]) -> None:
        with self._lock:
            for entry in entries:
                self._remove_chunk(entry.chunk_id)
                frequencies: dict[str, float] = defaultdict(float)
                length = 0
                for field_text, weight in (
                    (entry.text, self._weights.text),
                    (entry.heading, self._weights.heading),
                    (entry.title, self._weights.title),
                ):
                    terms = analyze(field_text)
                    length += len(terms)
                    for term in terms:
                        frequencies[term] += weight
                for term, frequency in frequencies.items():
                    self._postings[term][entry.chunk_id] = frequency
                self._terms[entry.chunk_id] = tuple(frequencies)
                self._length[entry.chunk_id] = length
                self._owner[entry.chunk_id] = (entry.document_id, entry.collection_id)
                self._total_length += length

    def _remove_chunk(self, chunk_id: int) -> None:
        if chunk_id not in self._length:
            return
        for term in self._terms.pop(chunk_id):
            postings = self._postings[term]
            postings.pop(chunk_id, None)
            if not postings:
                del self._postings[term]
        self._total_length -= self._length.pop(chunk_id)
        del self._owner[chunk_id]

    def remove_document(self, document_id: int) -> None:
        with self._lock:
            for chunk_id in [cid for cid, (doc, _) in self._owner.items() if doc == document_id]:
                self._remove_chunk(chunk_id)

    def clear(self) -> None:
        with self._lock:
            self._postings.clear()
            self._terms.clear()
            self._length.clear()
            self._owner.clear()
            self._total_length = 0

    # -- statistics ------------------------------------------------------------------------
    def chunk_count(self) -> int:
        return len(self._length)

    def document_frequencies(self, terms: Iterable[str]) -> dict[str, int]:
        with self._lock:
            return {term: len(self._postings.get(term, ())) for term in terms}

    # -- search ----------------------------------------------------------------------------
    def search(
        self, query: str, *, top_k: int = 6, collection_ids: Collection[int] | None = None
    ) -> list[SearchHit]:
        terms = query_terms(query)
        with self._lock:
            count = len(self._length)
            if not terms or not count:
                return []
            average_length = self._total_length / count or 1.0
            allowed = set(collection_ids) if collection_ids is not None else None
            scores: dict[int, float] = defaultdict(float)
            for term in terms:
                postings = self._postings.get(term)
                if not postings:
                    continue
                idf = bm25_idf(count, len(postings))
                for chunk_id, frequency in postings.items():
                    if allowed is not None and self._owner[chunk_id][1] not in allowed:
                        continue
                    norm = K1 * (1 - B + B * self._length[chunk_id] / average_length)
                    scores[chunk_id] += idf * frequency * (K1 + 1) / (frequency + norm)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [SearchHit(chunk_id, score) for chunk_id, score in ranked[:top_k]]
