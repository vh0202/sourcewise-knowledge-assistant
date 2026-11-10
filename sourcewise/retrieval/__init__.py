"""Retrieval: a small interface with interchangeable implementations."""

from __future__ import annotations

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from ..models import STATUS_READY, Chunk, Document
from .base import DEFAULT_WEIGHTS, FieldWeights, IndexEntry, Retriever, SearchHit, TermStatistics
from .bm25 import BM25Retriever
from .fts5 import Fts5Retriever, fts5_available
from .fusion import ReciprocalRankFusion
from .vector import CosineRetriever, Embedder

HEADING_SEPARATOR = " > "


def index_entry(chunk: Chunk, document: Document) -> IndexEntry:
    return IndexEntry(
        chunk_id=chunk.id,
        document_id=document.id,
        collection_id=document.collection_id,
        text=chunk.text,
        heading=HEADING_SEPARATOR.join(chunk.heading_path or []),
        title=document.title,
    )


def build_lexical_retriever(preference: str, engine: Engine) -> BM25Retriever | Fts5Retriever:
    """Pick the lexical retriever: FTS5 when SQLite has it (``auto``), otherwise pure-Python BM25."""
    if preference == "bm25":
        return BM25Retriever()
    if fts5_available(engine):
        return Fts5Retriever(engine)
    if preference == "fts5":
        raise RuntimeError("SOURCEWISE_RETRIEVER=fts5 but this SQLite build has no FTS5 extension")
    return BM25Retriever()


def sync_index(retriever: Retriever, session_factory: sessionmaker[Session]) -> int:
    """Bring a retriever in line with the chunks table.

    The in-memory BM25 index is always rebuilt at start-up; the persistent FTS5 index is
    rebuilt only if its row count disagrees with the database (for example after switching
    retrievers). Returns the number of chunks indexed, or 0 if nothing had to be done.
    """
    with session_factory() as session:
        rows = session.execute(
            select(Chunk, Document).join(Document, Chunk.document_id == Document.id).where(
                Document.status == STATUS_READY
            )
        ).all()
    if isinstance(retriever, Fts5Retriever) and retriever.chunk_count() == len(rows):
        return 0
    retriever.clear()
    retriever.add([index_entry(chunk, document) for chunk, document in rows])
    return len(rows)


__all__ = [
    "DEFAULT_WEIGHTS",
    "BM25Retriever",
    "CosineRetriever",
    "Embedder",
    "FieldWeights",
    "Fts5Retriever",
    "IndexEntry",
    "ReciprocalRankFusion",
    "Retriever",
    "SearchHit",
    "TermStatistics",
    "build_lexical_retriever",
    "fts5_available",
    "index_entry",
    "sync_index",
]
