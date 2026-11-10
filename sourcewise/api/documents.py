"""Document management (admin only): upload, list, inspect chunks, re-index, delete."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..knowledge import KnowledgeError, create_document, delete_document, run_ingestion
from ..models import STATUS_FAILED, STATUS_QUEUED, STATUS_READY, Chunk, Collection, Document
from ..schemas import ChunkingOut, ChunkOut, DocumentChunksOut, DocumentOut
from .collections import get_collection_or_404
from .deps import AdminUser, ContainerDep, SessionDep

router = APIRouter(prefix="/documents", tags=["knowledge base"])


def _document_out(document: Document, collection_name: str) -> DocumentOut:
    out = DocumentOut.model_validate(document)
    out.collection_name = collection_name
    return out


def _get_document_or_404(session: Session, document_id: int) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    return document


@router.get("", response_model=list[DocumentOut])
def list_documents(
    session: SessionDep, _admin: AdminUser, collection_id: int | None = None
) -> list[DocumentOut]:
    query = select(Document, Collection.name).join(Collection, Document.collection_id == Collection.id)
    if collection_id is not None:
        query = query.where(Document.collection_id == collection_id)
    rows = session.execute(query.order_by(Collection.name, Document.title)).all()
    return [_document_out(document, name) for document, name in rows]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
def upload_document(
    background: BackgroundTasks,
    session: SessionDep,
    container: ContainerDep,
    admin: AdminUser,
    file: Annotated[UploadFile, File()],
    collection_id: Annotated[int, Form()],
    title: Annotated[str | None, Form()] = None,
) -> DocumentOut:
    """Store the file and queue it for ingestion; poll the document to follow the pipeline."""
    collection = get_collection_or_404(session, collection_id)
    limit = container.settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)  # one byte past the limit is enough to detect an oversized file
    try:
        document = create_document(
            container,
            session,
            collection=collection,
            filename=file.filename or "document",
            data=data,
            title=title,
            uploaded_by=admin,
        )
    except KnowledgeError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    background.add_task(run_ingestion, container, document.id)
    return _document_out(document, collection.name)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, session: SessionDep, _admin: AdminUser) -> DocumentOut:
    document = _get_document_or_404(session, document_id)
    return _document_out(document, document.collection.name)


@router.get("/{document_id}/chunks", response_model=DocumentChunksOut)
def get_document_chunks(
    document_id: int, session: SessionDep, container: ContainerDep, _admin: AdminUser
) -> DocumentChunksOut:
    """Everything the chunk inspector shows: the document, the chunking settings and each chunk."""
    document = _get_document_or_404(session, document_id)
    chunks = session.execute(
        select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.ordinal)
    ).scalars().all()
    return DocumentChunksOut(
        document=_document_out(document, document.collection.name),
        chunking=ChunkingOut(
            max_chars=container.chunking.max_chars, overlap_chars=container.chunking.overlap_chars
        ),
        chunks=[ChunkOut.model_validate(chunk) for chunk in chunks],
    )


@router.post("/{document_id}/reindex", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
def reindex_document(
    document_id: int,
    background: BackgroundTasks,
    session: SessionDep,
    container: ContainerDep,
    _admin: AdminUser,
) -> DocumentOut:
    document = _get_document_or_404(session, document_id)
    if document.status not in (STATUS_READY, STATUS_FAILED):
        raise HTTPException(status.HTTP_409_CONFLICT, "This document is already being processed.")
    document.status = STATUS_QUEUED
    document.error = None
    session.commit()
    background.add_task(run_ingestion, container, document.id)
    return _document_out(document, document.collection.name)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_document(
    document_id: int, session: SessionDep, container: ContainerDep, _admin: AdminUser
) -> None:
    document = _get_document_or_404(session, document_id)
    delete_document(container, session, document)
