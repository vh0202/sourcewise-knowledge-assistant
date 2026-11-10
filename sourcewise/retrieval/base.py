"""The retriever contract.

Everything above this layer (the chat service, the answer engines, the evaluation script)
depends only on ``Retriever``. Lexical BM25 is what ships; a vector or hybrid retriever
plugs in by implementing the same three methods - see ``vector.py`` and ``fusion.py``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class IndexEntry:
    """What a retriever needs to know about one chunk."""

    chunk_id: int
    document_id: int
    collection_id: int
    text: str
    heading: str = ""  # section heading path, e.g. "Leave > Annual leave"
    title: str = ""  # document title


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    score: float  # higher is better; only comparable within one retriever


@dataclass(frozen=True)
class FieldWeights:
    """Relative weight of a term match in each indexed field."""

    text: float = 1.0
    heading: float = 2.0
    title: float = 1.0


DEFAULT_WEIGHTS = FieldWeights()


@runtime_checkable
class Retriever(Protocol):
    name: str
    label: str

    def add(self, entries: Sequence[IndexEntry]) -> None:
        """Index chunks, replacing any existing entry with the same ``chunk_id``."""

    def remove_document(self, document_id: int) -> None:
        """Remove every chunk of a document from the index."""

    def clear(self) -> None:
        """Remove everything from the index."""

    def search(
        self, query: str, *, top_k: int = 6, collection_ids: Collection[int] | None = None
    ) -> list[SearchHit]:
        """Return the best ``top_k`` chunks for ``query``, best first, optionally limited to some collections."""


@runtime_checkable
class TermStatistics(Protocol):
    """Corpus statistics used to weigh how informative a query term is."""

    def chunk_count(self) -> int: ...

    def document_frequencies(self, terms: Iterable[str]) -> dict[str, int]:
        """Number of indexed chunks containing each analysed term (terms absent from the index map to 0)."""
