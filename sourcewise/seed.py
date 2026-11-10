"""Demo data: accounts, collections, the synthetic corpus and some illustrative activity.

Everything created here is synthetic. Calderwick Health is a fictional organisation, the
documents in ``corpus/`` were written for this project, and the "activity" is a scripted set
of questions put through the real offline pipeline (never the Claude API) so that the
Insights page has something truthful to show: every answer, abstention and citation in it
was actually produced by the code in this repository.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import security
from .answering import ChatService, ExtractiveEngine
from .config import Settings
from .container import Container, build_container
from .db import utcnow
from .knowledge import KnowledgeError, create_document, run_ingestion
from .models import ROLE_ADMIN, ROLE_MEMBER, Collection, Conversation, Document, Message, User

# Demo credentials. They are shown on the sign-in page (see /api/meta) and are meant to be
# public; they protect nothing but synthetic data.
DEMO_USERS: list[dict[str, str]] = [
    {"name": "Dana Whitlock", "email": "admin@example.com", "password": "sourcewise-admin", "role": ROLE_ADMIN},
    {"name": "Sam Okafor", "email": "member@example.com", "password": "sourcewise-member", "role": ROLE_MEMBER},
]


@dataclass(frozen=True)
class CollectionSeed:
    name: str
    description: str
    folder: str
    starter_questions: tuple[str, ...]


COLLECTIONS: tuple[CollectionSeed, ...] = (
    CollectionSeed(
        name="People & Workplace",
        description="Employee handbook, onboarding, travel and expenses, hybrid working.",
        folder="people",
        starter_questions=(
            "How many days of annual leave do full-time employees get?",
            "What is the hotel limit per night when travelling for work?",
        ),
    ),
    CollectionSeed(
        name="IT & Security",
        description="Information security policy, IT Service Desk FAQ and the records retention schedule.",
        folder="it-security",
        starter_questions=(
            "How long does a password have to be?",
            "How soon must a lost laptop be reported?",
        ),
    ),
    CollectionSeed(
        name="Clinic Operations",
        description="Front-desk procedure, cancellations and refunds, Care Plan membership, complaints.",
        folder="clinic-operations",
        starter_questions=(
            "What is the fee for a late cancellation?",
            "What does the Performance Care Plan include?",
        ),
    ),
)


@dataclass(frozen=True)
class DemoConversation:
    user_email: str
    days_ago: int
    hour: int
    questions: tuple[str, ...]
    feedback: tuple[int | None, ...] = ()


# Scripted demo activity. Questions are asked through the real pipeline; a few are
# deliberately outside the corpus so that the knowledge-gap list is not empty.
DEMO_ACTIVITY: tuple[DemoConversation, ...] = (
    DemoConversation("member@example.com", 13, 9, ("How much annual leave do full-time staff get?", "Can unused leave be carried over?"), (1, None)),
    DemoConversation("admin@example.com", 12, 14, ("What is the hotel limit per night in London?", "Who approves an expense claim over £1,000?"), (1, 1)),
    DemoConversation("member@example.com", 12, 16, ("How long do new starters have a buddy?", "Which mandatory training has to be done in the first week?"), (None, 1)),
    DemoConversation("member@example.com", 11, 10, ("What is the late cancellation fee for patients?", "When is the cancellation fee waived?"), (1, None)),
    DemoConversation("admin@example.com", 10, 11, ("How long must a password be?", "How quickly must a lost laptop be reported?"), (None, 1)),
    DemoConversation("member@example.com", 9, 8, ("Is there staff parking at the Rookfield clinic?",)),
    DemoConversation("member@example.com", 8, 13, ("What mileage rate can I claim for driving my own car?", "What is the deadline for entering expense claims?"), (1, None)),
    DemoConversation("admin@example.com", 7, 15, ("Can employees work from another country?", "What are the core hours for hybrid working?"), (None, None)),
    DemoConversation("member@example.com", 6, 12, ("How long does a follow-up session last?", "Can a member pause the Care Plan?"), (1, 1)),
    DemoConversation("admin@example.com", 5, 9, ("Is there dental insurance for employees?", "How much does the company contribute to the pension?"), (None, 1)),
    DemoConversation("member@example.com", 4, 17, ("What should the front desk do if a patient collapses?", "How much cash is in the float?"), (1, None)),
    DemoConversation("member@example.com", 3, 10, ("Do we close early on Christmas Eve?",)),
    DemoConversation("admin@example.com", 2, 14, ("How much is the Performance plan per month?", "Is there staff parking at the Rookfield clinic?"), (-1, None)),
    DemoConversation("member@example.com", 1, 11, ("How quickly must a complaint be acknowledged?", "Who can approve a refund over £300?"), (None, 1)),
    DemoConversation("admin@example.com", 1, 16, ("How long are adult clinical records kept?", "What is the bonus scheme for clinic managers?"), (1, None)),
    DemoConversation("member@example.com", 0, 9, ("When is the IT Service Desk open?", "How many failed sign-in attempts lock an account?"), (1, None)),
)


def reset_data(settings: Settings) -> None:
    """Delete the database and stored uploads. The server must not be running."""
    if settings.data_dir.exists():
        shutil.rmtree(settings.data_dir)


def _seed_users(session: Session) -> int:
    created = 0
    for spec in DEMO_USERS:
        if session.execute(select(User).where(User.email == spec["email"])).scalar_one_or_none():
            continue
        session.add(
            User(
                email=spec["email"],
                name=spec["name"],
                role=spec["role"],
                password_hash=security.hash_password(spec["password"]),
            )
        )
        created += 1
    session.commit()
    return created


def _seed_corpus(container: Container, session: Session, corpus_dir: Path) -> tuple[int, list[str]]:
    admin = session.execute(select(User).where(User.role == ROLE_ADMIN)).scalars().first()
    ingested, problems = 0, []
    for spec in COLLECTIONS:
        collection = session.execute(select(Collection).where(Collection.name == spec.name)).scalar_one_or_none()
        if collection is None:
            collection = Collection(
                name=spec.name, description=spec.description, starter_questions=list(spec.starter_questions)
            )
            session.add(collection)
            session.commit()
        folder = corpus_dir / spec.folder
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            if not path.is_file():
                continue
            try:
                document = create_document(
                    container,
                    session,
                    collection=collection,
                    filename=path.name,
                    data=path.read_bytes(),
                    uploaded_by=admin,
                )
            except KnowledgeError as exc:
                if exc.status_code != 409:  # 409 = already seeded
                    problems.append(f"{path.name}: {exc.message}")
                continue
            run_ingestion(container, document.id)
            session.refresh(document)
            if document.status != "ready":
                problems.append(f"{path.name}: {document.error}")
            else:
                ingested += 1
    return ingested, problems


def _seed_activity(container: Container, session: Session) -> int:
    """Ask the scripted questions with the offline engine and spread them over the past two weeks."""
    if session.execute(select(func.count(Conversation.id))).scalar_one():
        return 0
    engine = ExtractiveEngine(container.lexical)  # no pacing delay, and never the Claude API
    chat = ChatService(
        session_factory=container.session_factory,
        retriever=container.retriever,
        stats=container.lexical,
        engine=engine,
        offline_engine=engine,
        top_k=container.settings.top_k,
        min_coverage=container.settings.min_coverage,
        min_evidence=container.settings.min_evidence,
    )
    users = {user.email: user for user in session.execute(select(User)).scalars()}
    midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    asked = 0
    for script in DEMO_ACTIVITY:
        user = users.get(script.user_email)
        if user is None:
            continue
        conversation = Conversation(user_id=user.id)
        session.add(conversation)
        session.commit()
        when = min(midnight - timedelta(days=script.days_ago) + timedelta(hours=script.hour), utcnow())
        for index, question in enumerate(script.questions):
            answer_id = None
            for name, payload in chat.reply(conversation.id, question):
                if name == "done":
                    answer_id = payload["message"]["id"]
            if answer_id is None:
                continue
            asked += 1
            answer = session.get(Message, answer_id)
            asked_at = when + timedelta(minutes=3 * index)
            question_row = session.get(Message, answer.reply_to_id)
            question_row.created_at = asked_at
            answer.created_at = asked_at + timedelta(seconds=2)
            if index < len(script.feedback) and not answer.abstained:
                answer.feedback = script.feedback[index]
            if index == 0:
                conversation.created_at = asked_at
            conversation.updated_at = answer.created_at
            session.commit()
    return asked


def seed(container: Container, *, with_activity: bool = True) -> dict[str, object]:
    """Populate an empty (or partly populated) database. Safe to run more than once."""
    with container.session_factory() as session:
        users = _seed_users(session)
        documents, problems = _seed_corpus(container, session, container.settings.corpus_dir)
        questions = _seed_activity(container, session) if with_activity else 0
        totals = {
            "users_created": users,
            "documents_ingested": documents,
            "demo_questions_asked": questions,
            "documents_total": session.execute(select(func.count(Document.id))).scalar_one(),
            "chunks_total": session.execute(select(func.coalesce(func.sum(Document.chunk_count), 0))).scalar_one(),
            "problems": problems,
        }
    return totals


def has_data(settings: Settings) -> bool:
    """True when the database already holds at least one account (so it has been set up before)."""
    if not (settings.data_dir / "sourcewise.db").exists():
        return False
    container = build_container(settings)
    try:
        with container.session_factory() as session:
            return bool(session.execute(select(func.count(User.id))).scalar_one())
    finally:
        container.close()


def seed_from_settings(settings: Settings, *, reset: bool = False, with_activity: bool = True) -> dict[str, object]:
    if reset:
        reset_data(settings)
    container = build_container(settings)
    try:
        return seed(container, with_activity=with_activity)
    finally:
        container.close()
