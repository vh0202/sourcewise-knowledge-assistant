"""Answer engines and the question-answering workflow."""

from __future__ import annotations

from ..config import Settings
from ..retrieval.base import TermStatistics
from .claude import REFUSAL_FALLBACK_MODELS, ClaudeEngine
from .confidence import RetrievalConfidence, assess_retrieval
from .offline import ExtractiveEngine
from .service import ChatService, RetrievalPlan, has_follow_up_cue
from .types import (
    ABSTAIN_TEXT,
    AnswerEngine,
    AnswerEvent,
    AnswerRequest,
    AnswerResult,
    CitationAdded,
    CitationRef,
    Completed,
    EngineError,
    Passage,
    TextDelta,
    Turn,
)


def build_offline_engine(settings: Settings, stats: TermStatistics) -> ExtractiveEngine:
    return ExtractiveEngine(stats, stream_delay=settings.stream_delay_ms / 1000)


def build_answer_engine(settings: Settings, stats: TermStatistics) -> AnswerEngine:
    """Claude when an API key is configured (or ``SOURCEWISE_ENGINE=claude``), otherwise offline."""
    if settings.resolved_engine != "claude":
        return build_offline_engine(settings, stats)
    if settings.claude_refusal_fallback == "auto":
        refusal_fallback = settings.claude_model in REFUSAL_FALLBACK_MODELS
    else:
        refusal_fallback = settings.claude_refusal_fallback == "on"
    return ClaudeEngine(
        model=settings.claude_model,
        max_tokens=settings.claude_max_tokens,
        effort=settings.claude_effort,
        refusal_fallback=refusal_fallback,
        api_key=settings.anthropic_api_key,
        timeout=settings.claude_timeout_seconds,
    )


__all__ = [
    "ABSTAIN_TEXT",
    "AnswerEngine",
    "AnswerEvent",
    "AnswerRequest",
    "AnswerResult",
    "ChatService",
    "CitationAdded",
    "CitationRef",
    "ClaudeEngine",
    "Completed",
    "EngineError",
    "ExtractiveEngine",
    "Passage",
    "RetrievalConfidence",
    "RetrievalPlan",
    "TextDelta",
    "Turn",
    "assess_retrieval",
    "build_answer_engine",
    "build_offline_engine",
    "has_follow_up_cue",
]
