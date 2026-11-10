"""API request and response models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from .models import Message


def _as_utc_iso(value: datetime) -> str:
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


# The database stores naive UTC datetimes; the API always sends them with an explicit "Z".
UtcDatetime = Annotated[datetime, PlainSerializer(_as_utc_iso, return_type=str)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# -- auth ------------------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class UserOut(ApiModel):
    id: int
    email: str
    name: str
    role: str


class SessionOut(BaseModel):
    user: UserOut | None


# -- knowledge base --------------------------------------------------------------------------
class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class CollectionOut(ApiModel):
    id: int
    name: str
    description: str
    starter_questions: list[str]
    document_count: int = 0
    chunk_count: int = 0
    created_at: UtcDatetime


class StageOut(BaseModel):
    name: str
    label: str
    status: str
    duration_ms: float | None = None
    detail: str | None = None


class DocumentOut(ApiModel):
    id: int
    collection_id: int
    collection_name: str = ""
    title: str
    filename: str
    kind: str
    size_bytes: int
    status: str
    error: str | None
    stages: list[StageOut]
    page_count: int | None
    chunk_count: int
    char_count: int
    created_at: UtcDatetime
    updated_at: UtcDatetime
    indexed_at: UtcDatetime | None


class ChunkOut(ApiModel):
    id: int
    ordinal: int
    text: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    start_char: int
    end_char: int
    overlap_chars: int
    token_estimate: int


class ChunkingOut(BaseModel):
    max_chars: int
    overlap_chars: int


class DocumentChunksOut(BaseModel):
    document: DocumentOut
    chunking: ChunkingOut
    chunks: list[ChunkOut]


# -- chat ------------------------------------------------------------------------------------
class CitationOut(ApiModel):
    number: int
    chunk_id: int | None
    document_id: int | None
    document_title: str
    document_kind: str
    collection_name: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    passage: str
    quote: str
    start_char: int
    end_char: int


class MessageOut(ApiModel):
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: UtcDatetime
    engine: str | None = None
    engine_label: str | None = None
    model: str | None = None
    abstained: bool = False
    abstain_reason: str | None = None
    confidence: float | None = None
    latency_ms: int | None = None
    truncated: bool = False
    notice: str | None = None
    feedback: int | None = None
    citations: list[CitationOut] = []

    @classmethod
    def from_message(cls, message: Message) -> MessageOut:
        out = cls.model_validate(message)
        out.engine_label = engine_label(message.engine, message.model)
        return out


class ConversationOut(ApiModel):
    id: int
    title: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    message_count: int = 0


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = []


class ConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    collection_ids: list[int] | None = None
    stream: bool = True

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must not be blank")
        return value


class FeedbackIn(BaseModel):
    value: int = Field(ge=-1, le=1)  # 1 helpful, -1 not helpful, 0 clears


# -- meta ------------------------------------------------------------------------------------
class EngineInfo(BaseModel):
    name: str
    label: str
    model: str | None = None


class MetaOut(BaseModel):
    name: str
    version: str
    notice: str
    engine: EngineInfo
    retriever: dict[str, str]
    demo_accounts: list[dict[str, Any]]


def engine_label(engine: str | None, model: str | None) -> str | None:
    if engine == "offline":
        return "Extractive (offline) mode"
    if engine == "claude":
        return f"Claude · {model}" if model else "Claude"
    return None
