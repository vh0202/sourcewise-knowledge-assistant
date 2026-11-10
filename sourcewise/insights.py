"""Usage analytics for administrators.

Everything here is derived from the stored conversations: how many questions were asked,
how many were answered versus abstained on, which documents the answers cited most, and -
most useful for whoever maintains the knowledge base - which questions went unanswered.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from .db import utcnow
from .models import Chunk, Citation, Collection, Document, Message
from .schemas import UtcDatetime

# Greetings and other messages with no searchable content are not questions about the
# knowledge base, so they are left out of every figure.
_NOT_A_QUESTION = "empty_query"


class DayCount(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    answered: int
    abstained: int


class CitedDocument(BaseModel):
    document_id: int | None
    title: str
    collection: str
    citations: int
    answers: int
    in_knowledge_base: bool


class KnowledgeGap(BaseModel):
    question: str
    count: int
    last_asked: UtcDatetime
    reason: str


class KnowledgeBaseSize(BaseModel):
    collections: int
    documents: int
    chunks: int


class InsightsOut(BaseModel):
    days: int
    questions: int
    answered: int
    abstained: int
    answer_rate: float | None
    helpful: int
    not_helpful: int
    median_latency_ms: int | None
    engines: dict[str, int]
    daily: list[DayCount]
    most_cited: list[CitedDocument]
    gaps: list[KnowledgeGap]
    knowledge_base: KnowledgeBaseSize


def compute_insights(session: Session, *, days: int = 14, now: datetime | None = None) -> InsightsOut:
    now = now or utcnow()
    first_day = (now - timedelta(days=days - 1)).date()
    since = datetime.combine(first_day, datetime.min.time())
    is_question = or_(Message.abstain_reason.is_(None), Message.abstain_reason != _NOT_A_QUESTION)

    answers = session.execute(
        select(Message).where(Message.role == "assistant", Message.created_at >= since, is_question)
    ).scalars().all()
    answered = [message for message in answers if not message.abstained]
    abstained = [message for message in answers if message.abstained]

    per_day: dict[str, DayCount] = {
        (first_day + timedelta(days=offset)).isoformat(): DayCount(
            date=(first_day + timedelta(days=offset)).isoformat(), answered=0, abstained=0
        )
        for offset in range(days)
    }
    for message in answers:
        bucket = per_day.get(message.created_at.date().isoformat())
        if bucket is None:
            continue
        if message.abstained:
            bucket.abstained += 1
        else:
            bucket.answered += 1

    latencies = [message.latency_ms for message in answered if message.latency_ms is not None]

    cited_rows = session.execute(
        select(
            Citation.document_id,
            Citation.document_title,
            Citation.collection_name,
            func.count(Citation.id),
            func.count(func.distinct(Citation.message_id)),
            func.count(func.distinct(Document.id)),
        )
        .join(Message, Citation.message_id == Message.id)
        .outerjoin(Document, Document.id == Citation.document_id)
        .where(Message.created_at >= since)
        .group_by(Citation.document_id, Citation.document_title, Citation.collection_name)
        .order_by(func.count(Citation.id).desc(), Citation.document_title)
        .limit(8)
    ).all()

    question = aliased(Message)
    gap_rows = session.execute(
        select(question.content, Message.created_at, Message.abstain_reason)
        .join(question, Message.reply_to_id == question.id)
        .where(Message.role == "assistant", Message.abstained.is_(True), Message.created_at >= since, is_question)
        .order_by(Message.created_at.desc())
    ).all()
    gaps: dict[str, KnowledgeGap] = {}
    for text, asked_at, reason in gap_rows:
        key = " ".join(text.lower().split())
        if key in gaps:
            gaps[key].count += 1
        else:
            gaps[key] = KnowledgeGap(question=text, count=1, last_asked=asked_at, reason=reason or "unsupported")

    return InsightsOut(
        days=days,
        questions=len(answers),
        answered=len(answered),
        abstained=len(abstained),
        answer_rate=round(len(answered) / len(answers), 4) if answers else None,
        helpful=sum(1 for message in answers if message.feedback == 1),
        not_helpful=sum(1 for message in answers if message.feedback == -1),
        median_latency_ms=round(statistics.median(latencies)) if latencies else None,
        engines=dict(Counter(message.engine or "unknown" for message in answers)),
        daily=list(per_day.values()),
        most_cited=[
            CitedDocument(
                document_id=document_id,
                title=title,
                collection=collection,
                citations=citations,
                answers=cited_answers,
                in_knowledge_base=bool(existing),
            )
            for document_id, title, collection, citations, cited_answers, existing in cited_rows
        ],
        gaps=list(gaps.values())[:25],
        knowledge_base=KnowledgeBaseSize(
            collections=session.execute(select(func.count(Collection.id))).scalar_one(),
            documents=session.execute(select(func.count(Document.id))).scalar_one(),
            chunks=session.execute(select(func.count(Chunk.id))).scalar_one(),
        ),
    )
