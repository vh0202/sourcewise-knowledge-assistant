"""Test doubles for the Anthropic SDK.

No test talks to the network. Instead of hand-rolling event objects, the fake client replays
events written in the documented *wire format* (plain dicts, exactly as they appear in the
API reference) through the SDK's own ``MessageStream`` / ``BetaMessageStream`` classes. The
engine under test therefore consumes real SDK event and citation types, and a mistake in how
it reads them shows up here rather than in production.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
from anthropic.lib.streaming import BetaMessageStream, MessageStream
from anthropic.types import RawMessageStreamEvent
from anthropic.types.beta import BetaRawMessageStreamEvent
from pydantic import TypeAdapter

_RAW = TypeAdapter(RawMessageStreamEvent)
_BETA_RAW = TypeAdapter(BetaRawMessageStreamEvent)
_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


# -- wire-format builders ----------------------------------------------------------------------
def char_citation(document_index: int, start: int, end: int, cited_text: str, title: str = "Doc") -> dict[str, Any]:
    return {
        "type": "char_location",
        "cited_text": cited_text,
        "document_index": document_index,
        "document_title": title,
        "start_char_index": start,
        "end_char_index": end,
    }


def wire_message(
    blocks: list[tuple[str, list[dict[str, Any]]]],
    *,
    stop_reason: str = "end_turn",
    model: str = "claude-opus-5-5",
    with_thinking: bool = True,
    extra_blocks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Server-sent events for a response made of text blocks, each with optional citations."""
    events: list[dict[str, Any]] = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 321, "output_tokens": 1},
            },
        }
    ]
    index = 0
    if with_thinking:  # adaptive thinking is on by default; its text is omitted
        events += [
            {"type": "content_block_start", "index": index, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
            {"type": "content_block_delta", "index": index, "delta": {"type": "signature_delta", "signature": "sig"}},
            {"type": "content_block_stop", "index": index},
        ]
        index += 1
    for block in extra_blocks or []:
        events += [
            {"type": "content_block_start", "index": index, "content_block": block},
            {"type": "content_block_stop", "index": index},
        ]
        index += 1
    for text, citations in blocks:
        events.append({"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": "", "citations": [] if citations else None}})
        middle = len(text) // 2
        for piece in (text[:middle], text[middle:]):  # two deltas per block, as a real stream would send several
            if piece:
                events.append({"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": piece}})
        for citation in citations:
            events.append({"type": "content_block_delta", "index": index, "delta": {"type": "citations_delta", "citation": citation}})
        events.append({"type": "content_block_stop", "index": index})
        index += 1
    events += [
        {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": {"output_tokens": 57}},
        {"type": "message_stop"},
    ]
    return events


# -- SDK errors --------------------------------------------------------------------------------
def api_error(cls: type[anthropic.APIStatusError], status: int, message: str = "error") -> anthropic.APIStatusError:
    response = httpx2.Response(status, request=_REQUEST)
    return cls(message, response=response, body={"type": "error", "error": {"type": "error", "message": message}})


def connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=_REQUEST)


# -- the fake client ---------------------------------------------------------------------------
class _RawStream:
    """Stands in for the SDK's low-level ``Stream``: an iterator of raw events plus a response."""

    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self.response = SimpleNamespace(request=SimpleNamespace(headers=httpx2.Headers()), headers=httpx2.Headers())
        self.closed = False

    def __iter__(self):
        return iter(self._events)

    def close(self) -> None:
        self.closed = True


class _StreamManager:
    def __init__(self, scripted: list[dict[str, Any]] | Exception, *, beta: bool) -> None:
        self._scripted = scripted
        self._beta = beta
        self._stream: MessageStream | BetaMessageStream | None = None

    def __enter__(self):
        if isinstance(self._scripted, Exception):
            raise self._scripted  # the real SDK raises HTTP errors when the stream is opened
        adapter, stream_class = (_BETA_RAW, BetaMessageStream) if self._beta else (_RAW, MessageStream)
        raw = _RawStream([adapter.validate_python(event) for event in self._scripted])
        self._stream = stream_class(raw, output_format=anthropic.NOT_GIVEN)  # type: ignore[arg-type]
        return self._stream

    def __exit__(self, *exc_info) -> None:
        if self._stream is not None:
            self._stream.close()


class _Messages:
    def __init__(self, client: FakeAnthropic, *, beta: bool) -> None:
        self._client = client
        self._beta = beta

    def stream(self, **kwargs: Any) -> _StreamManager:
        self._client.calls.append(("beta.messages.stream" if self._beta else "messages.stream", kwargs))
        if not self._client.script:
            raise AssertionError("FakeAnthropic was called more times than it has scripted responses")
        scripted = self._client.script.pop(0)
        if callable(scripted):
            scripted = scripted(kwargs)
        return _StreamManager(scripted, beta=self._beta)


class FakeAnthropic:
    """Replays scripted responses.

    Each entry is a list of wire events, an exception to raise when the stream is opened, or a
    function that receives the request and returns one of those (for responses that have to
    refer to what was actually sent, such as citations of the retrieved passages).
    """

    def __init__(self, *script: list[dict[str, Any]] | Exception) -> None:
        self.script = list(script)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.messages = _Messages(self, beta=False)
        self.beta = SimpleNamespace(messages=_Messages(self, beta=True))

    @property
    def last_request(self) -> dict[str, Any]:
        return self.calls[-1][1]


# -- other small fakes -------------------------------------------------------------------------
class FakeStats:
    """Term statistics from a literal table: ``{"term": document_frequency}``."""

    def __init__(self, frequencies: dict[str, int], chunks: int = 100) -> None:
        self._frequencies = frequencies
        self._chunks = chunks

    def chunk_count(self) -> int:
        return self._chunks

    def document_frequencies(self, terms):
        return {term: self._frequencies.get(term, 0) for term in terms}


class KeywordEmbedder:
    """A deterministic stand-in for an embedding model: one dimension per known keyword."""

    def __init__(self, vocabulary: list[str]) -> None:
        self.vocabulary = vocabulary
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[float(text.lower().count(word)) for word in self.vocabulary] for text in texts]
