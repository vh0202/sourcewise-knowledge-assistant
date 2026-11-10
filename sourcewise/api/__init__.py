"""HTTP API (everything under ``/api``)."""

from fastapi import APIRouter

from . import auth, chat, collections, documents, insights, meta

api_router = APIRouter(prefix="/api")
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(collections.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(insights.router)

__all__ = ["api_router"]
