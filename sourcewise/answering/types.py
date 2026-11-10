"""Types shared by the answer engines.

An engine receives a question plus the retrieved passages and yields a stream of events:
text deltas, citations as they are established, and finally a ``Completed`` event carrying
the whole result. Both engines - Claude and the offline extractive one - speak this
protocol, so the chat service and the UI do not care which one is answering.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

ABSTAIN_TEXT = (
    "Not found in the knowledge base. I can only answer from the documents that have been "
    "added, and none of the passages I found covers this question."
)

AbstainReason = Literal["weak_retrieval", "unsupported", "refused", "empty_query"]


@dataclass(frozen=True)
class Passage:
    """A retrieved chunk together with the metadata needed to cite it."""

    chunk_id: int
    document_id: int
    document_title: str
    document_kind: str
    collection_name: str
    heading_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    text: str
    score: float = 0.0

    @property
    def section(self) -> str:
        return " > ".join(self.heading_path)


@dataclass(frozen=True)
class Turn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class AnswerRequest:
    question: str
    passages: Sequence[Passage]
    history: Sequence[Turn] = ()
    # The text used for retrieval; differs from ``question`` when a follow-up was expanded
    # with the previous turn ("and for part-time staff?").
    search_query: str | None = None

    @property
    def effective_query(self) -> str:
        return self.search_query or self.question


@dataclass(frozen=True)
class CitationRef:
    """A numbered pointer from the answer to an exact span of a passage."""

    number: int
    passage: Passage
    quote: str
    start: int  # offsets into passage.text, end exclusive
    end: int


@dataclass
class AnswerResult:
    text: str
    citations: list[CitationRef] = field(default_factory=list)
    abstained: bool = False
    abstain_reason: AbstainReason | None = None
    truncated: bool = False
    model: str | None = None
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class CitationAdded:
    citation: CitationRef


@dataclass(frozen=True)
class Completed:
    result: AnswerResult


AnswerEvent = TextDelta | CitationAdded | Completed


class AnswerEngine(Protocol):
    name: str  # "offline" or "claude"
    label: str  # shown in the UI next to every answer
    model: str | None

    def answer(self, request: AnswerRequest) -> Iterator[AnswerEvent]:
        """Yield the answer as events; the final event is always ``Completed``."""


class EngineError(Exception):
    """An engine could not produce an answer. ``user_message`` is safe to show in the UI."""

    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


class CitationLedger:
    """Assigns citation numbers in order of first use; the same span always gets the same number."""

    def __init__(self) -> None:
        self._numbers: dict[tuple[int, int, int], int] = {}
        self.citations: list[CitationRef] = []

    def cite(self, passage: Passage, start: int, end: int) -> tuple[CitationRef, bool]:
        """Return the citation for a span and whether it is new."""
        start = max(0, min(start, len(passage.text)))
        end = max(start, min(end, len(passage.text)))
        key = (passage.chunk_id, start, end)
        number = self._numbers.get(key)
        if number is not None:
            return self.citations[number - 1], False
        citation = CitationRef(
            number=len(self.citations) + 1,
            passage=passage,
            quote=passage.text[start:end],
            start=start,
            end=end,
        )
        self._numbers[key] = citation.number
        self.citations.append(citation)
        return citation, True


def abstain(reason: AbstainReason, text: str = ABSTAIN_TEXT, *, model: str | None = None) -> AnswerResult:
    return AnswerResult(text=text, abstained=True, abstain_reason=reason, model=model)
