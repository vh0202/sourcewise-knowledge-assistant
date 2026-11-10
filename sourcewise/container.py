"""Wires the application's long-lived objects together.

One ``Container`` is built per process (or per test) and handed to the API, the seed script
and the evaluation script, so all three run exactly the same retrieval and answering code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from .answering import AnswerEngine, ChatService, ExtractiveEngine, build_answer_engine, build_offline_engine
from .config import Settings
from .db import Base, make_engine, make_session_factory
from .ingestion import ChunkingConfig
from .retrieval import (
    BM25Retriever,
    Fts5Retriever,
    ReciprocalRankFusion,
    Retriever,
    build_lexical_retriever,
    sync_index,
)
from .security import LoginThrottle


@dataclass
class Container:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    retriever: Retriever  # what answers are retrieved with: BM25, or BM25 fused with extra retrievers
    lexical: BM25Retriever | Fts5Retriever  # always present; also provides the corpus term statistics
    answer_engine: AnswerEngine
    offline_engine: ExtractiveEngine
    chat: ChatService
    chunking: ChunkingConfig
    throttle: LoginThrottle

    def close(self) -> None:
        self.engine.dispose()


def build_container(
    settings: Settings,
    *,
    answer_engine: AnswerEngine | None = None,
    extra_retrievers: Sequence[Retriever] = (),
) -> Container:
    """Create the database (if needed), the retriever and the answer engines.

    ``answer_engine`` overrides the engine chosen from settings; tests use it to inject a
    Claude engine backed by a fake SDK client.

    ``extra_retrievers`` is the plug-in point for vector search: anything implementing the
    ``Retriever`` protocol (for example ``CosineRetriever`` around an embedding model, or an
    adapter for a vector database) is fused with BM25 by reciprocal rank fusion. Nothing is
    passed here by default - the shipped application is lexical only.
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    lexical = build_lexical_retriever(settings.retriever, engine)
    retriever: Retriever = ReciprocalRankFusion([lexical, *extra_retrievers]) if extra_retrievers else lexical
    sync_index(retriever, session_factory)

    offline_engine = build_offline_engine(settings, lexical)
    primary = answer_engine if answer_engine is not None else build_answer_engine(settings, lexical)
    chat = ChatService(
        session_factory=session_factory,
        retriever=retriever,
        stats=lexical,
        engine=primary,
        offline_engine=offline_engine,
        top_k=settings.top_k,
        min_coverage=settings.min_coverage,
        min_evidence=settings.min_evidence,
        model_min_coverage=settings.claude_min_coverage,
        fallback_to_offline=settings.fallback_to_offline,
    )
    return Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        retriever=retriever,
        lexical=lexical,
        answer_engine=primary,
        offline_engine=offline_engine,
        chat=chat,
        chunking=ChunkingConfig(max_chars=settings.chunk_max_chars, overlap_chars=settings.chunk_overlap_chars),
        throttle=LoginThrottle(),
    )
