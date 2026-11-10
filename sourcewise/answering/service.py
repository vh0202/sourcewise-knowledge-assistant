"""The question-answering workflow: retrieve -> check confidence -> answer -> persist.

``ChatService.reply`` is a generator of ``(event, payload)`` pairs that the API turns into a
server-sent event stream:

    start      the stored user message and the engine that will answer
    retrieval  how many passages were found and how well they cover the question
    delta      a piece of answer text
    citation   a source the answer has just cited
    reset      discard the text streamed so far (the engine was switched after a failure)
    done       the stored assistant message, complete with citations
    error      the question could not be answered at all
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Collection as AbstractCollection
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..db import utcnow
from ..models import Chunk, Citation, Collection, Conversation, Document, Message
from ..retrieval.base import Retriever, SearchHit, TermStatistics
from ..schemas import MessageOut, engine_label
from ..text.analyzer import query_terms, tokenize
from .confidence import RetrievalConfidence, assess_retrieval, term_weights
from .types import (
    AnswerEngine,
    AnswerRequest,
    AnswerResult,
    CitationAdded,
    Completed,
    EngineError,
    Passage,
    TextDelta,
    Turn,
    abstain,
)

logger = logging.getLogger(__name__)

Event = tuple[str, dict[str, Any]]

EMPTY_QUERY_TEXT = (
    "I can answer questions about the documents in the knowledge base - a policy, a procedure, "
    "a product detail. What would you like to know?"
)
DEFAULT_TITLE = "New conversation"
_FOLLOW_UP_OPENING_RE = re.compile(
    r"^\s*(and|but|also|so|what about|how about|what if|same for|does that|is that|is it|are they|do they|does it)\b",
    re.IGNORECASE,
)
_REFERRING_WORDS = frozenset({"it", "that", "this", "they", "them", "those", "these"})


@dataclass(frozen=True)
class RetrievalPlan:
    """What was searched for, what came back, and how far it can be trusted."""

    query: str
    expanded: bool  # True when the previous question was folded into the search
    passages: list[Passage]
    confidence: RetrievalConfidence


def make_title(question: str, limit: int = 60) -> str:
    title = " ".join(question.split())
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def previous_question(history: Sequence[Turn]) -> str | None:
    return next((turn.content for turn in reversed(history) if turn.role == "user"), None)


def has_follow_up_cue(question: str) -> bool:
    """True if the wording itself signals a follow-up: "and for part-time staff?", "is it paid?"."""
    terms = query_terms(question)
    if not terms:
        return False
    if _FOLLOW_UP_OPENING_RE.match(question):
        return True
    return len(terms) <= 4 and bool(_REFERRING_WORDS.intersection(tokenize(question)))


def load_passages(session: Session, hits: Sequence[SearchHit]) -> list[Passage]:
    """Fetch the chunks behind search hits, in ranking order, with their document metadata."""
    if not hits:
        return []
    rows = session.execute(
        select(Chunk, Document, Collection)
        .join(Document, Chunk.document_id == Document.id)
        .join(Collection, Document.collection_id == Collection.id)
        .where(Chunk.id.in_([hit.chunk_id for hit in hits]))
    ).all()
    by_id = {chunk.id: (chunk, document, collection) for chunk, document, collection in rows}
    passages: list[Passage] = []
    for hit in hits:
        row = by_id.get(hit.chunk_id)
        if row is None:  # the index is momentarily ahead of or behind the table
            continue
        chunk, document, collection = row
        passages.append(
            Passage(
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.title,
                document_kind=document.kind,
                collection_name=collection.name,
                heading_path=tuple(chunk.heading_path or ()),
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=chunk.text,
                score=hit.score,
            )
        )
    return passages


class ChatService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        retriever: Retriever,
        stats: TermStatistics,
        engine: AnswerEngine,
        offline_engine: AnswerEngine,
        top_k: int = 6,
        min_coverage: float = 0.55,
        min_evidence: float = 0.5,
        model_min_coverage: float | None = None,
        fallback_to_offline: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._retriever = retriever
        self._stats = stats
        self._engine = engine
        self._offline_engine = offline_engine
        self._top_k = top_k
        self._min_coverage = min_coverage
        self._min_evidence = min_evidence
        # Never stricter than the strict gate: anything the extractive engine may answer,
        # an engine that judges relevance itself may see as well.
        self._model_min_coverage = min_coverage if model_min_coverage is None else min(model_min_coverage, min_coverage)
        self._fallback_to_offline = fallback_to_offline

    @property
    def engine(self) -> AnswerEngine:
        return self._engine

    # -- retrieval (also used by the evaluation script) ------------------------------------
    def _search(
        self, session: Session, query: str, collection_ids: AbstractCollection[int] | None
    ) -> tuple[list[Passage], RetrievalConfidence]:
        hits = self._retriever.search(query, top_k=self._top_k, collection_ids=collection_ids)
        passages = load_passages(session, hits)
        confidence = assess_retrieval(
            query, passages, self._stats, min_coverage=self._min_coverage, min_evidence=self._min_evidence
        )
        return passages, confidence

    def _covers_question(self, question: str, confidence: RetrievalConfidence) -> bool:
        """Does the retrieved passage match the follow-up's own terms, not just the earlier question's?"""
        own = query_terms(question)
        if not own:
            return True
        weights = term_weights(own, self._stats)
        matched = set(confidence.matched_terms)
        return sum(w for term, w in weights.items() if term in matched) >= 0.5 * sum(weights.values())

    def plan_retrieval(
        self,
        session: Session,
        question: str,
        history: Sequence[Turn] = (),
        collection_ids: AbstractCollection[int] | None = None,
    ) -> RetrievalPlan:
        """Retrieve passages for a question, taking the conversation into account.

        A question is searched on its own first. It is searched together with the previous
        question only when its wording marks it as a follow-up ("and for part-time staff?")
        or when it finds nothing by itself - and the combined search is accepted only if the
        passage it finds also matches what the follow-up itself asks about. That keeps a new,
        unanswerable question from being "answered" with the previous topic.
        """
        previous = previous_question(history)
        cue = previous is not None and has_follow_up_cue(question)
        standalone: tuple[list[Passage], RetrievalConfidence] | None = None
        if not cue:
            standalone = self._search(session, question, collection_ids)
            if previous is None or standalone[1].sufficient or not query_terms(question):
                return RetrievalPlan(question, False, *standalone)

        combined_query = f"{previous} {question}"
        passages, confidence = self._search(session, combined_query, collection_ids)
        if confidence.sufficient and self._covers_question(question, confidence):
            return RetrievalPlan(combined_query, True, passages, confidence)
        if standalone is None:
            standalone = self._search(session, question, collection_ids)
        return RetrievalPlan(question, False, *standalone)

    # -- answering -------------------------------------------------------------------------
    def _passes_gate(self, confidence: RetrievalConfidence, engine: AnswerEngine) -> bool:
        """Is this retrieval result good enough to hand to ``engine``?

        The extractive engine can only copy sentences, so it is given a passage only when it
        lexically covers the question (the strict gate, ``confidence.sufficient``).

        An engine that reads the passages and declines by itself when they do not answer the
        question (``judges_relevance``) is given anything with real lexical evidence. A
        paraphrase shares few words with the passage that answers it; turning it away before
        the model has seen that passage is the commonest wrong refusal of the strict gate.
        The evidence floor still applies, so a question that matches nothing but an everyday
        word never costs an API call.
        """
        if confidence.sufficient:
            return True
        if not getattr(engine, "judges_relevance", False):
            return False
        return confidence.evidence >= self._min_evidence and confidence.coverage >= self._model_min_coverage

    def _gate(self, plan: RetrievalPlan, engine: AnswerEngine) -> AnswerResult | None:
        """Abstain before ``engine`` runs if there is nothing to search for or retrieval is too weak for it."""
        if not query_terms(plan.query):
            return abstain("empty_query", EMPTY_QUERY_TEXT)
        if not self._passes_gate(plan.confidence, engine):
            return abstain("weak_retrieval")
        return None

    def dry_run(
        self,
        session: Session,
        question: str,
        history: Sequence[Turn] = (),
        collection_ids: AbstractCollection[int] | None = None,
    ) -> tuple[RetrievalPlan, AnswerResult]:
        """Answer with the offline engine without storing anything (used by the evaluation)."""
        plan = self.plan_retrieval(session, question, history, collection_ids)
        result = self._gate(plan, self._offline_engine)
        if result is None:
            request = AnswerRequest(
                question=question, passages=plan.passages, history=history, search_query=plan.query
            )
            for event in self._offline_engine.answer(request):
                if isinstance(event, Completed):
                    result = event.result
        assert result is not None
        return plan, result

    @staticmethod
    def _relay(engine: AnswerEngine, request: AnswerRequest) -> Generator[Event, None, AnswerResult]:
        """Yield an engine's events for the UI and return its result (use with ``yield from``)."""
        result: AnswerResult | None = None
        for event in engine.answer(request):
            if isinstance(event, TextDelta):
                yield "delta", {"text": event.text}
            elif isinstance(event, CitationAdded):
                citation = event.citation
                yield (
                    "citation",
                    {
                        "number": citation.number,
                        "document_title": citation.passage.document_title,
                        "heading_path": list(citation.passage.heading_path),
                        "page_start": citation.passage.page_start,
                    },
                )
            elif isinstance(event, Completed):
                result = event.result
        if result is None:
            raise EngineError("no_result", "The answer engine returned no result.")
        return result

    def reply(
        self,
        conversation_id: int,
        question: str,
        collection_ids: AbstractCollection[int] | None = None,
    ) -> Iterator[Event]:
        started = time.perf_counter()
        with self._session_factory() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                yield "error", {"message": "Conversation not found."}
                return

            earlier = list(conversation.messages)
            user_message = Message(conversation_id=conversation.id, role="user", content=question)
            session.add(user_message)
            if not earlier and conversation.title == DEFAULT_TITLE:
                conversation.title = make_title(question)
            conversation.updated_at = utcnow()
            session.commit()

            engine: AnswerEngine = self._engine
            yield (
                "start",
                {
                    "user_message": MessageOut.from_message(user_message).model_dump(mode="json"),
                    "conversation": {"id": conversation.id, "title": conversation.title},
                    "engine": {"name": engine.name, "label": engine.label, "model": engine.model},
                },
            )

            history = [Turn(m.role, m.content) for m in earlier if m.role in ("user", "assistant")]  # type: ignore[arg-type]
            plan = self.plan_retrieval(session, question, history, collection_ids)
            search_query, expanded = plan.query, plan.expanded
            passages, confidence = plan.passages, plan.confidence
            yield (
                "retrieval",
                {"passages": len(passages), "coverage": confidence.coverage, "sufficient": confidence.sufficient},
            )

            notice: str | None = None
            gated = self._gate(plan, engine)
            if gated is not None:
                result = gated
            else:
                request = AnswerRequest(
                    question=question, passages=passages, history=history, search_query=search_query
                )
                try:
                    result = yield from self._relay(engine, request)
                except EngineError as exc:
                    logger.warning("Answer engine '%s' failed: %s", engine.name, exc)
                    if not self._fallback_to_offline or engine is self._offline_engine:
                        yield "error", {"message": exc.user_message}
                        return
                    notice = f"{exc.user_message} This answer was produced in extractive (offline) mode instead."
                    engine = self._offline_engine
                    yield "reset", {"engine": {"name": engine.name, "label": engine.label, "model": engine.model}}
                    # The question may have reached the failed engine through the relaxed gate.
                    # The extractive engine is held to the strict one, as it always is.
                    result = self._gate(plan, engine)
                    if result is None:
                        result = yield from self._relay(engine, request)

            model = result.model or engine.model
            assistant = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=result.text,
                reply_to_id=user_message.id,
                engine=engine.name,
                model=model,
                abstained=result.abstained,
                abstain_reason=result.abstain_reason,
                confidence=confidence.coverage,
                latency_ms=round((time.perf_counter() - started) * 1000),
                truncated=result.truncated,
                notice=notice,
                retrieval={
                    "query": search_query,
                    "expanded_with_previous_turn": expanded,
                    "collection_ids": sorted(collection_ids) if collection_ids is not None else None,
                    "evidence": confidence.evidence,
                    "matched_terms": list(confidence.matched_terms),
                    "missing_terms": list(confidence.missing_terms),
                    "usage": result.usage,
                    "hits": [
                        {
                            "chunk_id": p.chunk_id,
                            "document_title": p.document_title,
                            "section": p.section,
                            "score": round(p.score, 4),
                        }
                        for p in passages
                    ],
                },
                citations=[
                    Citation(
                        number=c.number,
                        chunk_id=c.passage.chunk_id,
                        document_id=c.passage.document_id,
                        document_title=c.passage.document_title,
                        document_kind=c.passage.document_kind,
                        collection_name=c.passage.collection_name,
                        heading_path=list(c.passage.heading_path),
                        page_start=c.passage.page_start,
                        page_end=c.passage.page_end,
                        passage=c.passage.text,
                        quote=c.quote,
                        start_char=c.start,
                        end_char=c.end,
                    )
                    for c in result.citations
                ],
            )
            session.add(assistant)
            conversation.updated_at = utcnow()
            session.commit()
            yield "done", {"message": MessageOut.from_message(assistant).model_dump(mode="json")}


__all__ = [
    "ChatService",
    "Event",
    "RetrievalPlan",
    "engine_label",
    "has_follow_up_cue",
    "load_passages",
    "make_title",
    "previous_question",
]
