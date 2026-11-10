"""The ingestion pipeline: parse -> normalise -> chunk -> index.

Each stage records its outcome and timing on the document row and commits, so the admin UI
can show where a document is in the pipeline (and where it failed, if it did).
Re-running the pipeline for a document replaces its chunks and index entries.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from ..db import utcnow
from ..models import (
    STATUS_CHUNKING,
    STATUS_FAILED,
    STATUS_INDEXING,
    STATUS_NORMALIZING,
    STATUS_PARSING,
    STATUS_READY,
    Chunk,
    Document,
)
from ..retrieval import Retriever, index_entry
from .chunker import ChunkingConfig, chunk_document
from .normalize import normalize_blocks
from .parsers import DocumentParseError, UnsupportedDocumentError, parse_document

logger = logging.getLogger(__name__)
T = TypeVar("T")

STAGES: tuple[tuple[str, str, str], ...] = (
    # (name, label, document status while running)
    ("parse", "Parse", STATUS_PARSING),
    ("normalize", "Normalise", STATUS_NORMALIZING),
    ("chunk", "Chunk", STATUS_CHUNKING),
    ("index", "Index", STATUS_INDEXING),
)


class IngestionError(Exception):
    """A document could not be ingested; the message is safe to show to an admin."""


_MINOR_WORDS = frozenset({"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with"})


def tidy_title(title: str) -> str:
    """Normalise whitespace, and turn a SHOUTED TITLE into Title Case."""
    title = " ".join(title.split())
    if not title.isupper():
        return title
    words = title.lower().split(" ")
    return " ".join(
        word if index and word in _MINOR_WORDS else word[:1].upper() + word[1:]
        for index, word in enumerate(words)
    )


def _blank_stages() -> list[dict[str, Any]]:
    return [
        {"name": name, "label": label, "status": "pending", "duration_ms": None, "detail": None}
        for name, label, _ in STAGES
    ]


def ingest_document(
    session_factory: sessionmaker[Session],
    document_id: int,
    *,
    retriever: Retriever,
    chunking: ChunkingConfig,
) -> None:
    """Run the full pipeline for one stored document. Never raises: failures are recorded on the row."""
    with session_factory() as session:
        document = session.get(Document, document_id)
        if document is None:
            return

        stages = _blank_stages()

        def run_stage(index: int, work: Callable[[], tuple[T, str]]) -> T:
            _, _, status = STAGES[index]
            stages[index]["status"] = "running"
            document.status = status
            document.stages = [dict(stage) for stage in stages]
            session.commit()
            started = time.perf_counter()
            try:
                result, detail = work()
            except Exception:
                stages[index]["status"] = "failed"
                stages[index]["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
                raise
            stages[index]["status"] = "done"
            stages[index]["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
            stages[index]["detail"] = detail
            return result

        try:
            # Start from a clean slate so that re-indexing is idempotent.
            retriever.remove_document(document.id)
            session.execute(delete(Chunk).where(Chunk.document_id == document.id))
            document.error = None
            document.chunk_count = 0
            session.commit()

            def parse():
                data = Path(document.storage_path).read_bytes()
                parsed = parse_document(document.kind, data)
                if not any(block.kind != "heading" for block in parsed.blocks):
                    raise IngestionError(
                        "No extractable text was found. If this is a scanned PDF, it needs OCR before upload."
                    )
                detail = f"{len(parsed.blocks)} blocks"
                if parsed.page_count:
                    detail += f" from {parsed.page_count} page{'s' if parsed.page_count != 1 else ''}"
                for note in parsed.notes:
                    detail += f" · {note}"
                return parsed, detail

            parsed = run_stage(0, parse)

            def normalize():
                blocks, stats = normalize_blocks(parsed.blocks)
                detail = f"{stats.characters:,} characters"
                dropped = stats.dropped_empty + stats.dropped_duplicates
                if dropped:
                    detail += f" · dropped {dropped} empty or repeated block{'s' if dropped != 1 else ''}"
                return blocks, detail

            blocks = run_stage(1, normalize)

            def chunk():
                chunked = chunk_document(blocks, chunking)
                if not chunked.chunks:
                    raise IngestionError("The document contains headings but no body text to index.")
                sizes = [len(c.text) for c in chunked.chunks]
                overlapping = sum(1 for c in chunked.chunks if c.overlap_chars)
                detail = (
                    f"{len(sizes)} chunk{'s' if len(sizes) != 1 else ''} · "
                    f"avg {round(sum(sizes) / len(sizes))} chars · {overlapping} with overlap"
                )
                return chunked, detail

            chunked = run_stage(2, chunk)

            def index():
                rows = [
                    Chunk(
                        document_id=document.id,
                        collection_id=document.collection_id,
                        ordinal=draft.ordinal,
                        text=draft.text,
                        heading_path=list(draft.heading_path),
                        page_start=draft.page_start,
                        page_end=draft.page_end,
                        start_char=draft.start_char,
                        end_char=draft.end_char,
                        overlap_chars=draft.overlap_chars,
                        token_estimate=draft.token_estimate,
                    )
                    for draft in chunked.chunks
                ]
                if not document.title_locked and parsed.title:
                    document.title = tidy_title(parsed.title)[:300]
                document.normalized_text = chunked.text
                document.char_count = len(chunked.text)
                document.page_count = parsed.page_count
                session.add_all(rows)
                # Commit before touching the index: the FTS5 retriever writes through its own
                # connection, and SQLite allows only one writer at a time.
                session.commit()
                retriever.add([index_entry(row, document) for row in rows])
                return rows, f"{len(rows)} chunk{'s' if len(rows) != 1 else ''} indexed · {retriever.label}"

            rows = run_stage(3, index)

            document.chunk_count = len(rows)
            document.status = STATUS_READY
            document.indexed_at = utcnow()
            document.stages = [dict(stage) for stage in stages]
            session.commit()
        except Exception as exc:  # noqa: BLE001 - every failure must end up on the document row
            session.rollback()
            known = isinstance(exc, (IngestionError, DocumentParseError, UnsupportedDocumentError))
            if not known:
                logger.exception("Ingestion of document %s failed", document_id)
            retriever.remove_document(document_id)
            document = session.get(Document, document_id)
            if document is None:
                return
            session.execute(delete(Chunk).where(Chunk.document_id == document_id))
            document.status = STATUS_FAILED
            document.chunk_count = 0
            document.error = str(exc) if known else f"Unexpected error during ingestion: {exc}"
            document.stages = [dict(stage) for stage in stages]
            session.commit()
