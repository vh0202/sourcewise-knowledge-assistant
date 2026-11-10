"""The Claude engine, exercised against a faked Anthropic SDK client.

These tests never reach the network. The fake replays wire-format events through the SDK's
real stream classes (see ``tests/fakes.py``), so request construction, streaming, citation
mapping, abstention and error handling are all covered - but the live API is not.
"""

from __future__ import annotations

import anthropic
import pytest

from sourcewise.answering import (
    ABSTAIN_TEXT,
    AnswerRequest,
    CitationAdded,
    ClaudeEngine,
    Completed,
    EngineError,
    Passage,
    TextDelta,
    Turn,
    build_answer_engine,
)
from sourcewise.answering.claude import (
    NOT_FOUND_SENTINEL,
    REFUSAL_FALLBACK_BETA,
    REFUSAL_TEXT,
    SYSTEM_PROMPT,
    build_messages,
    document_block,
    resolve_citation,
)
from sourcewise.answering.offline import ExtractiveEngine

from .conftest import make_settings
from .fakes import FakeAnthropic, FakeStats, api_error, char_citation, connection_error, wire_message

LEAVE = Passage(
    chunk_id=11, document_id=1, document_title="Employee Handbook", document_kind="md", collection_name="People & Workplace",
    heading_path=("Leave", "Annual leave"), page_start=None, page_end=None, score=9.1,
    text="Full-time employees receive 25 days of paid annual leave each year. Part-time employees receive the same entitlement pro rata.",
)
CARRY = Passage(
    chunk_id=12, document_id=1, document_title="Employee Handbook", document_kind="md", collection_name="People & Workplace",
    heading_path=("Leave", "Annual leave"), page_start=None, page_end=None, score=7.4,
    text="You may carry over up to five unused days. Carried-over days must be used by 31 March.",
)
SOP = Passage(
    chunk_id=13, document_id=2, document_title="Front Desk SOP", document_kind="pdf", collection_name="Clinic Operations",
    heading_path=("5. Taking payments",), page_start=2, page_end=2, score=3.0,
    text="Cash is accepted up to £200 per transaction.",
)
PASSAGES = [LEAVE, CARRY, SOP]
QUESTION = "How much annual leave do I get, and can I carry any over?"

FIRST = "Full-time employees receive 25 days of paid annual leave each year."
SECOND = "You may carry over up to five unused days."


def cite(passage_index: int, sentence: str) -> dict:
    text = PASSAGES[passage_index].text
    start = text.index(sentence)
    return char_citation(passage_index, start, start + len(sentence), sentence, PASSAGES[passage_index].document_title)


def grounded_answer(**kwargs) -> list[dict]:
    return wire_message(
        [
            ("Full-time staff get ", []),
            ("25 days of paid annual leave a year", [cite(0, FIRST)]),
            (", and ", []),
            ("up to five unused days can be carried over", [cite(1, SECOND)]),
            (".", []),
        ],
        **kwargs,
    )


def make_engine(*script, **kwargs) -> tuple[ClaudeEngine, FakeAnthropic]:
    client = FakeAnthropic(*script)
    return ClaudeEngine(model="claude-opus-5-5", client=client, **kwargs), client


def run(engine: ClaudeEngine, question: str = QUESTION, passages=PASSAGES, history=()):
    events = list(engine.answer(AnswerRequest(question=question, passages=passages, history=history)))
    assert isinstance(events[-1], Completed)
    return events, events[-1].result


# -- the request -------------------------------------------------------------------------------
def test_request_follows_current_api_guidance() -> None:
    engine, client = make_engine(grounded_answer(), max_tokens=16000, effort="medium")
    run(engine)
    endpoint, request = client.calls[0]
    assert endpoint == "messages.stream"
    assert request["model"] == "claude-opus-5-5"
    assert request["max_tokens"] == 16000
    assert request["system"] == SYSTEM_PROMPT
    assert request["output_config"] == {"effort": "medium"}
    # Parameters that current models reject or that this app must not send.
    for forbidden in ("temperature", "top_p", "top_k", "thinking", "tools", "tool_choice"):
        assert forbidden not in request
    assert set(request) == {"model", "max_tokens", "system", "output_config", "messages"}


def test_each_passage_is_sent_as_a_citable_plain_text_document() -> None:
    engine, client = make_engine(grounded_answer())
    run(engine)
    (message,) = client.last_request["messages"]
    assert message["role"] == "user"
    *documents, question = message["content"]
    assert question == {"type": "text", "text": QUESTION}
    assert len(documents) == len(PASSAGES)
    assert documents[0] == {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": LEAVE.text},
        "title": "Employee Handbook",
        "context": "Collection: People & Workplace. Section: Leave > Annual leave",
        "citations": {"enabled": True},
    }
    assert documents[2]["context"] == "Collection: Clinic Operations. Section: 5. Taking payments. Page: 2"
    # Citations must be enabled on all documents or none.
    assert all(document["citations"] == {"enabled": True} for document in documents)


def test_document_block_truncates_very_long_titles() -> None:
    long_title = Passage(**{**LEAVE.__dict__, "document_title": "T" * 500, "heading_path": ()})
    block = document_block(long_title)
    assert len(block["title"]) == 200
    assert block["context"] == "Collection: People & Workplace"


def test_history_is_sent_as_plain_text_without_citation_markers_or_documents() -> None:
    history = [
        Turn("assistant", "A stray assistant turn at the start is dropped."),
        Turn("user", "How long is probation?"),
        Turn("assistant", "Probation lasts six months [1]. It can be extended once [2]."),
    ]
    messages = build_messages(AnswerRequest(question="And the notice period?", passages=[LEAVE], history=history))
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "How long is probation?"
    assert messages[1]["content"] == "Probation lasts six months. It can be extended once."
    # Documents appear only in the final user turn, so document_index maps straight onto the passages.
    assert [block["type"] for block in messages[2]["content"]] == ["document", "text"]
    assert all(isinstance(m["content"], str) for m in messages[:2])


def test_only_recent_history_is_sent() -> None:
    history = [Turn("user" if i % 2 == 0 else "assistant", f"turn {i}") for i in range(20)]
    messages = build_messages(AnswerRequest(question="next", passages=[LEAVE], history=history))
    assert [m["content"] for m in messages[:-1]] == [f"turn {i}" for i in range(14, 20)]


def test_effort_can_be_omitted_for_models_that_do_not_support_it() -> None:
    engine, client = make_engine(grounded_answer(), effort="none")
    run(engine)
    assert "output_config" not in client.last_request


def test_system_prompt_states_the_grounding_rules() -> None:
    assert NOT_FOUND_SENTINEL in SYSTEM_PROMPT
    assert "only" in SYSTEM_PROMPT.lower() and "cite" in SYSTEM_PROMPT.lower()


# -- streaming and citations -------------------------------------------------------------------
def test_answer_is_streamed_with_markers_after_each_cited_statement() -> None:
    engine, _ = make_engine(grounded_answer())
    events, result = run(engine)

    assert result.text == (
        "Full-time staff get 25 days of paid annual leave a year [1], and up to five unused days can be "
        "carried over [2]."
    )
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == result.text
    assert not result.abstained and not result.truncated
    assert result.model == "claude-opus-5-5"
    assert result.usage == {"input_tokens": 321, "output_tokens": 57}
    # Text arrives in several deltas, not in one piece at the end.
    assert sum(isinstance(e, TextDelta) for e in events) >= 6


def test_citations_map_back_to_the_exact_span_of_the_right_chunk() -> None:
    engine, _ = make_engine(grounded_answer())
    events, result = run(engine)

    first, second = result.citations
    assert (first.number, first.passage.chunk_id, first.quote) == (1, 11, FIRST)
    assert (second.number, second.passage.chunk_id, second.quote) == (2, 12, SECOND)
    for citation in result.citations:
        assert citation.passage.text[citation.start : citation.end] == citation.quote
    # Each citation is announced once, before the marker that refers to it.
    announced = [e.citation.number for e in events if isinstance(e, CitationAdded)]
    assert announced == [1, 2]
    order = [("cite", e.citation.number) if isinstance(e, CitationAdded) else ("text", e.text) for e in events[:-1]]
    assert order.index(("cite", 1)) < order.index(("text", " [1]"))
    assert order.index(("cite", 2)) < order.index(("text", " [2]"))


def test_the_same_span_cited_twice_keeps_one_number_and_a_block_may_cite_several_spans() -> None:
    script = wire_message(
        [
            ("You get 25 days", [cite(0, FIRST)]),
            (" and may carry five over", [cite(1, SECOND), cite(0, FIRST)]),
            (". Again: 25 days", [cite(0, FIRST)]),
            (".", []),
        ]
    )
    _, result = run(make_engine(script)[0])
    assert result.text == "You get 25 days [1] and may carry five over [2] [1]. Again: 25 days [1]."
    assert [c.number for c in result.citations] == [1, 2]


def test_markers_attach_to_the_claim_not_to_trailing_whitespace() -> None:
    script = wire_message([("You get 25 days.\n\n", [cite(0, FIRST)]), ("- carry over five days\n", [cite(1, SECOND)])])
    _, result = run(make_engine(script)[0])
    assert result.text == "You get 25 days. [1]\n\n- carry over five days [2]"


def test_thinking_and_fallback_blocks_are_ignored() -> None:
    plain = wire_message([("Answer", [cite(0, FIRST)])], with_thinking=False)
    with_thinking = wire_message([("Answer", [cite(0, FIRST)])], with_thinking=True)
    assert run(make_engine(plain)[0])[1].text == run(make_engine(with_thinking)[0])[1].text == "Answer [1]"


@pytest.mark.parametrize(
    ("citation", "expected_span"),
    [
        # Indices that reproduce cited_text are used as they are (trailing whitespace trimmed).
        ({"type": "char_location", "document_index": 0, "start_char_index": 0, "end_char_index": 68, "cited_text": FIRST + " "}, (0, 67)),
        # Indices that do not reproduce cited_text (for example a different unit) fall back to searching for it.
        ({"type": "char_location", "document_index": 1, "start_char_index": 3, "end_char_index": 9, "cited_text": SECOND}, (0, len(SECOND))),
        # Other location types carry no character range: the quoted text is located in the passage.
        ({"type": "page_location", "document_index": 2, "start_page_number": 1, "end_page_number": 2, "cited_text": "up to £200"}, (17, 27)),
        ({"type": "content_block_location", "document_index": 1, "start_block_index": 0, "end_block_index": 1, "cited_text": "31 March"}, (77, 85)),
        # If the quoted text cannot be found, the whole passage is cited rather than nothing.
        ({"type": "page_location", "document_index": 2, "start_page_number": 1, "end_page_number": 2, "cited_text": "not in the passage"}, (0, len(SOP.text))),
    ],
)
def test_resolve_citation_handles_every_location_type(citation: dict, expected_span: tuple[int, int]) -> None:
    from types import SimpleNamespace

    resolved = resolve_citation(SimpleNamespace(**citation), PASSAGES)
    assert resolved is not None
    passage, start, end = resolved
    assert passage is PASSAGES[citation["document_index"]]
    assert (start, end) == expected_span


def test_a_citation_of_a_document_that_was_not_supplied_is_dropped() -> None:
    from types import SimpleNamespace

    assert resolve_citation(SimpleNamespace(type="char_location", document_index=7, start_char_index=0, end_char_index=5, cited_text="x"), PASSAGES) is None
    assert resolve_citation(SimpleNamespace(type="char_location", document_index=None, cited_text="x"), PASSAGES) is None

    stray = wire_message([("Answer", [char_citation(9, 0, 4, "Full"), cite(0, FIRST)])])
    _, result = run(make_engine(stray)[0])
    assert [c.passage.chunk_id for c in result.citations] == [11]
    assert result.text == "Answer [1]"


# -- abstention --------------------------------------------------------------------------------
def test_the_not_found_sentinel_becomes_an_abstention_and_is_never_streamed() -> None:
    engine, _ = make_engine(wire_message([(NOT_FOUND_SENTINEL, [])]))
    events, result = run(engine)
    assert result.abstained and result.abstain_reason == "unsupported"
    assert result.text == ABSTAIN_TEXT
    assert result.citations == []
    assert not any(isinstance(e, (TextDelta, CitationAdded)) for e in events)


def test_the_sentinel_is_recognised_across_delta_boundaries_and_after_whitespace() -> None:
    engine, _ = make_engine(wire_message([("\n" + NOT_FOUND_SENTINEL + " The documents do not mention parking.", [])]))
    events, result = run(engine)
    assert result.abstained
    assert not any(isinstance(e, TextDelta) for e in events)


def test_an_answer_without_any_citation_is_treated_as_unsupported() -> None:
    engine, _ = make_engine(wire_message([("You probably get around 28 days, as most employers offer.", [])]))
    events, result = run(engine)
    assert result.abstained and result.abstain_reason == "unsupported"
    assert result.text == ABSTAIN_TEXT and result.citations == []
    # The text was streamed before the stream ended; the final result overrides it.
    assert any(isinstance(e, TextDelta) for e in events)


def test_text_that_merely_starts_like_the_sentinel_is_shown() -> None:
    script = wire_message([("[[", []), ("see note]] You get 25 days", [cite(0, FIRST)])])
    _, result = run(make_engine(script)[0])
    assert result.text == "[[see note]] You get 25 days [1]"


def test_a_refusal_is_reported_as_such_and_partial_text_is_discarded() -> None:
    engine, _ = make_engine(wire_message([("Partial ", [cite(0, FIRST)])], stop_reason="refusal"))
    _, result = run(engine)
    assert result.abstained and result.abstain_reason == "refused"
    assert result.text == REFUSAL_TEXT
    assert result.citations == []


def test_hitting_max_tokens_marks_the_answer_as_truncated() -> None:
    engine, _ = make_engine(grounded_answer(stop_reason="max_tokens"))
    _, result = run(engine)
    assert result.truncated and not result.abstained


def test_no_passages_means_no_api_call() -> None:
    engine, client = make_engine()
    _, result = run(engine, passages=[])
    assert result.abstained and result.abstain_reason == "weak_retrieval"
    assert client.calls == []


# -- refusal fallback (beta) -------------------------------------------------------------------
def test_refusal_fallback_uses_the_beta_endpoint_with_the_documented_parameters() -> None:
    engine, client = make_engine(grounded_answer(model="claude-opus-4-8"), refusal_fallback=True)
    _, result = run(engine)
    endpoint, request = client.calls[0]
    assert endpoint == "beta.messages.stream"
    assert request["betas"] == [REFUSAL_FALLBACK_BETA] == ["server-side-fallback-2026-07-01"]
    assert request["fallbacks"] == "default"
    assert result.model == "claude-opus-4-8"  # the model that actually served the answer
    assert [c.number for c in result.citations] == [1, 2]


def test_a_fallback_switch_block_in_the_stream_is_skipped() -> None:
    # When the requested model declines, the API marks the hand-over with a `fallback` content block.
    switch = {
        "type": "fallback",
        "from": {"model": "claude-opus-5-5"},
        "to": {"model": "claude-opus-4-8"},
        "trigger": {"type": "refusal", "category": None},
    }
    script = wire_message([("Answer", [cite(0, FIRST)])], extra_blocks=[switch])
    engine, _ = make_engine(script, refusal_fallback=True)
    events, result = run(engine)
    assert result.text == "Answer [1]"
    assert [c.passage.chunk_id for c in result.citations] == [11]
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Answer [1]"


def test_if_the_beta_is_rejected_the_request_is_retried_without_it() -> None:
    rejected = api_error(anthropic.BadRequestError, 400, "Unexpected value(s) for the anthropic-beta header.")
    engine, client = make_engine(rejected, grounded_answer(), refusal_fallback=True)
    _, result = run(engine)
    assert [endpoint for endpoint, _ in client.calls] == ["beta.messages.stream", "messages.stream"]
    assert "fallbacks" not in client.calls[1][1] and "betas" not in client.calls[1][1]
    assert not result.abstained


# -- errors ------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("error", "code"),
    [
        (api_error(anthropic.AuthenticationError, 401), "authentication"),
        (api_error(anthropic.PermissionDeniedError, 403), "permission"),
        (api_error(anthropic.NotFoundError, 404), "model_not_found"),
        (api_error(anthropic.RateLimitError, 429), "rate_limited"),
        (api_error(anthropic.BadRequestError, 400, "max_tokens is too large"), "bad_request"),
        (api_error(anthropic.InternalServerError, 500), "api_error"),
        (connection_error(), "connection"),
    ],
)
def test_sdk_errors_become_engine_errors_with_a_safe_message(error: Exception, code: str) -> None:
    engine, _ = make_engine(error)
    with pytest.raises(EngineError) as caught:
        list(engine.answer(AnswerRequest(question=QUESTION, passages=PASSAGES)))
    assert caught.value.code == code
    assert caught.value.user_message
    assert "sk-ant" not in caught.value.user_message
    assert caught.value.__cause__ is error


def test_a_bad_request_without_fallback_is_not_retried() -> None:
    engine, client = make_engine(api_error(anthropic.BadRequestError, 400, "invalid"), grounded_answer())
    with pytest.raises(EngineError):
        list(engine.answer(AnswerRequest(question=QUESTION, passages=PASSAGES)))
    assert len(client.calls) == 1


# -- engine selection --------------------------------------------------------------------------
def test_engine_selection_follows_the_api_key(tmp_path) -> None:
    stats = FakeStats({})
    offline = build_answer_engine(make_settings(tmp_path, engine="auto", anthropic_api_key=None), stats)
    assert isinstance(offline, ExtractiveEngine) and offline.label == "Extractive (offline) mode"

    claude = build_answer_engine(make_settings(tmp_path, engine="auto", anthropic_api_key="test-key-not-real"), stats)
    assert isinstance(claude, ClaudeEngine)
    assert (claude.name, claude.model, claude.label) == ("claude", "claude-opus-5-5", "Claude · claude-opus-5-5")

    forced_offline = build_answer_engine(make_settings(tmp_path, engine="offline", anthropic_api_key="test-key-not-real"), stats)
    assert isinstance(forced_offline, ExtractiveEngine)


def test_model_is_configurable_and_fallback_is_enabled_only_where_supported(tmp_path) -> None:
    stats = FakeStats({})

    def engine_for(**overrides) -> ClaudeEngine:
        engine = build_answer_engine(make_settings(tmp_path, engine="claude", anthropic_api_key="test-key-not-real", **overrides), stats)
        assert isinstance(engine, ClaudeEngine)
        return engine

    assert engine_for()._refusal_fallback is True  # claude-opus-5-5 supports it
    haiku = engine_for(claude_model="claude-haiku-5-5")
    assert haiku.model == "claude-haiku-5-5" and haiku._refusal_fallback is False
    assert engine_for(claude_refusal_fallback="off")._refusal_fallback is False
    assert engine_for(claude_model="claude-haiku-5-5", claude_refusal_fallback="on")._refusal_fallback is True
    assert engine_for(claude_effort="none")._effort is None
    assert engine_for(claude_effort="low")._effort == "low"
