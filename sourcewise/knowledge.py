"""Knowledge-base operations shared by the API and the seed script."""

from __future__ import annotations

import contextlib
import hashlib
import re
from pathlib import Path, PurePath

from sqlalchemy import select
from sqlalchemy.orm import Session

from .container import Container
from .ingestion import DocumentParseError, UnsupportedDocumentError, detect_kind, ingest_document
from .models import STATUS_QUEUED, Collection, Document, User

_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


class KnowledgeError(Exception):
    """A knowledge-base request that cannot be fulfilled; maps to an HTTP error."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def safe_filename(name: str) -> str:
    """Reduce an uploaded file name to a harmless base name."""
    base = PurePath(name.replace("\\", "/")).name
    cleaned = _UNSAFE_FILENAME_RE.sub("_", base).strip(" .")
    return cleaned[:120] or "document"


def title_from_filename(filename: str) -> str:
    stem = PurePath(filename).stem
    words = re.sub(r"[_\-]+", " ", stem).split()
    return " ".join(word if word.isupper() else word.capitalize() for word in words) or "Untitled document"


def create_document(
    container: Container,
    session: Session,
    *,
    collection: Collection,
    filename: str,
    data: bytes,
    title: str | None = None,
    uploaded_by: User | None = None,
) -> Document:
    """Validate and store an upload and create its (queued) document row."""
    settings = container.settings
    filename = safe_filename(filename)
    if not data:
        raise KnowledgeError(400, "The file is empty.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise KnowledgeError(413, f"The file is larger than the {settings.max_upload_mb} MB upload limit.")
    try:
        kind = detect_kind(filename, data)
    except (UnsupportedDocumentError, DocumentParseError) as exc:
        raise KnowledgeError(415, str(exc)) from exc

    digest = hashlib.sha256(data).hexdigest()
    duplicate = session.execute(
        select(Document).where(Document.collection_id == collection.id, Document.sha256 == digest)
    ).scalar_one_or_none()
    if duplicate is not None:
        raise KnowledgeError(
            409, f"This file is already in the collection as “{duplicate.title}”."
        )

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    storage_path = settings.upload_dir / f"{digest[:16]}_{filename}"
    storage_path.write_bytes(data)

    title = (title or "").strip()
    document = Document(
        collection_id=collection.id,
        title=title[:300] if title else title_from_filename(filename),
        title_locked=bool(title),
        filename=filename,
        kind=kind,
        size_bytes=len(data),
        sha256=digest,
        storage_path=str(storage_path),
        status=STATUS_QUEUED,
        stages=[],
        uploaded_by_id=uploaded_by.id if uploaded_by else None,
    )
    session.add(document)
    session.commit()
    return document


def run_ingestion(container: Container, document_id: int) -> None:
    """Run the ingestion pipeline for a stored document (called in a background task)."""
    ingest_document(
        container.session_factory,
        document_id,
        retriever=container.retriever,
        chunking=container.chunking,
    )


def delete_document(container: Container, session: Session, document: Document) -> None:
    """Remove a document, its chunks, its index entries and its stored file."""
    storage_path = Path(document.storage_path)
    document_id = document.id
    session.delete(document)
    session.commit()
    container.retriever.remove_document(document_id)
    with contextlib.suppress(OSError):  # a leftover file is harmless; the row and index entries are what matter
        storage_path.unlink(missing_ok=True)
