"""Conversations, questions (streamed answers), feedback and starter questions.

Conversations are private: every query is filtered by the signed-in user's id, so one user
can never read or write another user's conversation - including an admin's.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..answering.service import DEFAULT_TITLE, Event
from ..models import Collection, Conversation, Message, User
from ..schemas import (
    ConversationDetailOut,
    ConversationIn,
    ConversationOut,
    ConversationRename,
    FeedbackIn,
    MessageIn,
    MessageOut,
)
from .deps import ContainerDep, CurrentUser, SessionDep

router = APIRouter(tags=["chat"])


def _own_conversation(session: Session, conversation_id: int, user: User) -> Conversation:
    conversation = session.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .options(selectinload(Conversation.messages).selectinload(Message.citations))
    ).scalar_one_or_none()
    if conversation is None:
        # 404 rather than 403: do not confirm that someone else's conversation exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    return conversation


def _conversation_out(conversation: Conversation, message_count: int) -> ConversationOut:
    out = ConversationOut.model_validate(conversation)
    out.message_count = message_count
    return out


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(session: SessionDep, user: CurrentUser) -> list[ConversationOut]:
    rows = session.execute(
        select(Conversation, func.count(Message.id))
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .where(Conversation.user_id == user.id)
        .group_by(Conversation.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    ).all()
    return [_conversation_out(conversation, count) for conversation, count in rows]


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationIn, session: SessionDep, user: CurrentUser) -> ConversationOut:
    title = (payload.title or "").strip() or DEFAULT_TITLE
    conversation = Conversation(user_id=user.id, title=title)
    session.add(conversation)
    session.commit()
    return _conversation_out(conversation, 0)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(conversation_id: int, session: SessionDep, user: CurrentUser) -> ConversationDetailOut:
    conversation = _own_conversation(session, conversation_id, user)
    return ConversationDetailOut(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=len(conversation.messages),
        messages=[MessageOut.from_message(message) for message in conversation.messages],
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: int, payload: ConversationRename, session: SessionDep, user: CurrentUser
) -> ConversationOut:
    conversation = _own_conversation(session, conversation_id, user)
    conversation.title = payload.title.strip() or conversation.title
    session.commit()
    return _conversation_out(conversation, len(conversation.messages))


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: int, session: SessionDep, user: CurrentUser) -> None:
    conversation = _own_conversation(session, conversation_id, user)
    session.delete(conversation)
    session.commit()


def _sse(events: Iterator[Event]) -> Iterator[str]:
    for name, payload in events:
        yield f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/conversations/{conversation_id}/messages")
def ask(
    conversation_id: int,
    payload: MessageIn,
    session: SessionDep,
    container: ContainerDep,
    user: CurrentUser,
):
    """Ask a question. Streams server-sent events by default; ``"stream": false`` returns JSON."""
    conversation = _own_conversation(session, conversation_id, user)
    collection_ids: list[int] | None = None
    if payload.collection_ids:
        known = set(session.execute(select(Collection.id)).scalars())
        unknown = sorted(set(payload.collection_ids) - known)
        if unknown:
            raise HTTPException(422, f"Unknown collection ids: {unknown}")
        collection_ids = sorted(set(payload.collection_ids))

    conversation_id = conversation.id
    session.close()  # the chat service uses its own session for the lifetime of the stream
    events = container.chat.reply(conversation_id, payload.content, collection_ids)
    if payload.stream:
        return StreamingResponse(
            _sse(events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    final: dict | None = None
    for name, data in events:
        if name == "done":
            final = data["message"]
        elif name == "error":
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, data["message"])
    if final is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No answer was produced.")
    return final


@router.post("/messages/{message_id}/feedback", response_model=MessageOut)
def give_feedback(message_id: int, payload: FeedbackIn, session: SessionDep, user: CurrentUser) -> MessageOut:
    message = session.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(Message.id == message_id, Conversation.user_id == user.id, Message.role == "assistant")
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Answer not found.")
    message.feedback = payload.value or None
    session.commit()
    return MessageOut.from_message(message)


@router.get("/suggestions", response_model=list[str])
def starter_questions(session: SessionDep, _user: CurrentUser, limit: int = 6) -> list[str]:
    """Starter questions for an empty chat, taken in rotation from each collection."""
    collections = session.execute(select(Collection).order_by(Collection.name)).scalars().all()
    pools = [list(collection.starter_questions or []) for collection in collections]
    suggestions: list[str] = []
    while len(suggestions) < limit and any(pools):
        for pool in pools:
            if pool and len(suggestions) < limit:
                suggestions.append(pool.pop(0))
    return suggestions
