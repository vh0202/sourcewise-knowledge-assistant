"""Collections: any signed-in user can list them (to scope a chat); only admins can change them."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..knowledge import delete_document
from ..models import Collection, Document
from ..schemas import CollectionIn, CollectionOut
from .deps import AdminUser, ContainerDep, CurrentUser, SessionDep

router = APIRouter(prefix="/collections", tags=["knowledge base"])


def _collection_out(session: Session, collection: Collection) -> CollectionOut:
    documents, chunks = session.execute(
        select(func.count(Document.id), func.coalesce(func.sum(Document.chunk_count), 0)).where(
            Document.collection_id == collection.id
        )
    ).one()
    out = CollectionOut.model_validate(collection)
    out.document_count, out.chunk_count = int(documents), int(chunks)
    return out


def get_collection_or_404(session: Session, collection_id: int) -> Collection:
    collection = session.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collection not found.")
    return collection


def _ensure_name_is_free(session: Session, name: str, *, except_id: int | None = None) -> None:
    existing = session.execute(
        select(Collection).where(func.lower(Collection.name) == name.lower())
    ).scalar_one_or_none()
    if existing is not None and existing.id != except_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "A collection with this name already exists.")


@router.get("", response_model=list[CollectionOut])
def list_collections(session: SessionDep, _user: CurrentUser) -> list[CollectionOut]:
    collections = session.execute(select(Collection).order_by(Collection.name)).scalars().all()
    return [_collection_out(session, collection) for collection in collections]


@router.post("", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
def create_collection(payload: CollectionIn, session: SessionDep, _admin: AdminUser) -> CollectionOut:
    _ensure_name_is_free(session, payload.name)
    collection = Collection(name=payload.name, description=payload.description.strip(), starter_questions=[])
    session.add(collection)
    session.commit()
    return _collection_out(session, collection)


@router.patch("/{collection_id}", response_model=CollectionOut)
def update_collection(
    collection_id: int, payload: CollectionIn, session: SessionDep, _admin: AdminUser
) -> CollectionOut:
    collection = get_collection_or_404(session, collection_id)
    _ensure_name_is_free(session, payload.name, except_id=collection.id)
    collection.name = payload.name
    collection.description = payload.description.strip()
    session.commit()
    return _collection_out(session, collection)


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(
    collection_id: int, session: SessionDep, container: ContainerDep, _admin: AdminUser
) -> None:
    collection = get_collection_or_404(session, collection_id)
    for document in list(collection.documents):
        delete_document(container, session, document)
    session.expire(collection, ["documents"])  # they are gone; do not let the cascade delete them twice
    session.delete(collection)
    session.commit()
