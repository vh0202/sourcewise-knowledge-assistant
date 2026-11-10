"""Asking questions over the API: answers, citations, abstention, streaming, history, feedback."""

from __future__ import annotations

from collections.abc import Iterator

import anthropic
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sourcewise.answering import ABSTAIN_TEXT, ClaudeEngine
from sourcewise.answering.service import EMPTY_QUERY_TEXT, has_follow_up_cue, make_title
from sourcewise.container import Container, build_container
from sourcewise.main import create_app
from sourcewise.models import Chunk, Collection, Document, Message
from sourcewise.seed import seed

from .conftest import MEMBER, make_settings, parse_sse, sign_in
from .fakes import FakeAnthropic, api_error, char_citation, wire_message

LEAVE_QUESTION = "How many days of annual leave do full-time employees get?"
UNANSWERABLE = "Can I bring my pet iguana to the office?"
# Answerable (the travel policy sets a hotel limit per night) but worded differently from it.
PARAPHRASED = "What's the most I can spend on a hotel for one night on a work trip?"
# Nothing in the knowledge base matches these beyond, at most, an everyday word.
NO_EVIDENCE_QUESTIONS = (
    "What is the airspeed velocity of an unladen swallow?",
    "How long do we keep patient X-ray images?",
)


def new_conversation(client: TestClient, **body) -> int:
    response = client.post("/api/conversations", json=body)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def ask(client: TestClient, conversation_id: int, content: str, **extra) -> dict:
    response = client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": content, "stream": False, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


# -- answers with citations (offline engine) -------------------------------------------------
def test_an_answer_carries_numbered_citations_back_to_the_source(seeded_member: TestClient) -> None:
    answer = ask(seeded_member, new_conversation(seeded_member), LEAVE_QUESTION)

    assert answer["role"] == "assistant" and not answer["abstained"]
    assert "25 days of paid annual leave" in answer["content"]
    assert "[1]" in answer["content"]
    assert (answer["engine"], answer["engine_label"], answer["model"]) == ("offline", "Extractive (offline) mode", None)
    assert 0.55 <= answer["confidence"] <= 1.0
    assert answer["latency_ms"] >= 0 and answer["feedback"] is None and answer["notice"] is None

    assert [c["number"] for c in answer["citations"]] == list(range(1, len(answer["citations"]) + 1))
    citation = answer["citations"][0]
    assert citation["document_title"] == "Employee Handbook"
    assert citation["document_kind"] == "md"
    assert citation["collection_name"] == "People & Workplace"
    assert citation["heading_path"] == ["Leave", "Annual leave"]
    assert citation["page_start"] is None
    # The highlight span points at the quoted text inside the stored passage.
    assert citation["passage"][citation["start_char"] : citation["end_char"]] == citation["quote"]
    assert "25 days" in citation["quote"]
    # Every marker in the text refers to a citation that exists.
    numbers = {c["number"] for c in answer["citations"]}
    import re

    assert {int(n) for n in re.findall(r"\[(\d+)\]", answer["content"])} == numbers


def test_citations_from_a_pdf_carry_the_page_number(seeded_member: TestClient) -> None:
    answer = ask(seeded_member, new_conversation(seeded_member), "How much cash can the front desk accept per transaction?")
    assert not answer["abstained"]
    citation = answer["citations"][0]
    assert citation["document_title"] == "Front Desk Standard Operating Procedure"
    assert citation["document_kind"] == "pdf"
    assert citation["page_start"] == 2
    assert citation["heading_path"] == ["5. Taking payments", "5.1 Payment methods"]
    assert "£200" in citation["quote"]


def test_a_citation_matches_the_chunk_it_came_from(seeded_member: TestClient, seeded: Container) -> None:
    answer = ask(seeded_member, new_conversation(seeded_member), "How long must a password be?")
    citation = answer["citations"][0]
    with seeded.session_factory() as session:
        chunk = session.get(Chunk, citation["chunk_id"])
        document = session.get(Document, citation["document_id"])
    assert chunk.text == citation["passage"]
    assert chunk.document_id == document.id and document.title == citation["document_title"]
    assert "14 characters" in chunk.text[citation["start_char"] : citation["end_char"]]


def test_questions_outside_the_knowledge_base_are_declined(seeded_member: TestClient) -> None:
    answer = ask(seeded_member, new_conversation(seeded_member), UNANSWERABLE)
    assert answer["abstained"] is True
    assert answer["abstain_reason"] == "weak_retrieval"
    assert answer["content"] == ABSTAIN_TEXT and answer["content"].startswith("Not found in the knowledge base")
    assert answer["citations"] == []
    assert answer["engine_label"] == "Extractive (offline) mode"


def test_small_talk_gets_a_prompt_rather_than_a_search(seeded_member: TestClient) -> None:
    answer = ask(seeded_member, new_conversation(seeded_member), "Hi, thanks!")
    assert answer["abstained"] and answer["abstain_reason"] == "empty_query"
    assert answer["content"] == EMPTY_QUERY_TEXT


def test_search_can_be_limited_to_collections(seeded_member: TestClient, seeded: Container) -> None:
    with seeded.session_factory() as session:
        collections = {c.name: c.id for c in session.execute(select(Collection)).scalars()}
    conversation = new_conversation(seeded_member)

    scoped = ask(seeded_member, conversation, LEAVE_QUESTION, collection_ids=[collections["People & Workplace"]])
    assert not scoped["abstained"]
    assert {c["collection_name"] for c in scoped["citations"]} == {"People & Workplace"}

    elsewhere = ask(seeded_member, conversation, LEAVE_QUESTION, collection_ids=[collections["IT & Security"]])
    assert elsewhere["abstained"] or all(c["collection_name"] == "IT & Security" for c in elsewhere["citations"])

    unknown = seeded_member.post(
        f"/api/conversations/{conversation}/messages", json={"content": "x", "stream": False, "collection_ids": [9999]}
    )
    assert unknown.status_code == 422 and "9999" in unknown.json()["detail"]


@pytest.mark.parametrize("content", ["", "   ", "x" * 2001])
def test_invalid_questions_are_rejected(seeded_member: TestClient, content: str) -> None:
    conversation = new_conversation(seeded_member)
    response = seeded_member.post(f"/api/conversations/{conversation}/messages", json={"content": content, "stream": False})
    assert response.status_code == 422
    assert seeded_member.get(f"/api/conversations/{conversation}").json()["messages"] == []


# -- streaming ---------------------------------------------------------------------------------
def test_the_answer_is_streamed_as_server_sent_events(seeded_member: TestClient) -> None:
    conversation = new_conversation(seeded_member)
    with seeded_member.stream("POST", f"/api/conversations/{conversation}/messages", json={"content": LEAVE_QUESTION}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        body = "".join(response.iter_text())
    events = parse_sse(body)
    names = [name for name, _ in events]

    assert names[0] == "start" and names[1] == "retrieval" and names[-1] == "done"
    assert names.count("done") == 1 and "error" not in names
    assert names.count("delta") > 5  # word by word, not one blob
    assert names.index("citation") < names.index("done")

    start = events[0][1]
    assert start["user_message"]["content"] == LEAVE_QUESTION and start["user_message"]["role"] == "user"
    assert start["engine"] == {"name": "offline", "label": "Extractive (offline) mode", "model": None}
    assert events[1][1]["sufficient"] is True and events[1][1]["passages"] > 0

    final = events[-1][1]["message"]
    streamed = "".join(data["text"] for name, data in events if name == "delta")
    assert streamed == final["content"]
    assert [data["number"] for name, data in events if name == "citation"] == [c["number"] for c in final["citations"]]
    # What was streamed is what was stored.
    stored = seeded_member.get(f"/api/conversations/{conversation}").json()["messages"]
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1] == final


def test_an_abstention_is_streamed_as_a_single_final_message(seeded_member: TestClient) -> None:
    conversation = new_conversation(seeded_member)
    with seeded_member.stream("POST", f"/api/conversations/{conversation}/messages", json={"content": UNANSWERABLE}) as response:
        events = parse_sse("".join(response.iter_text()))
    assert [name for name, _ in events] == ["start", "retrieval", "done"]
    assert events[1][1]["sufficient"] is False
    assert events[2][1]["message"]["abstained"] is True


# -- conversations -----------------------------------------------------------------------------
def test_multi_turn_conversation_history(seeded_member: TestClient) -> None:
    conversation = new_conversation(seeded_member)
    first = ask(seeded_member, conversation, LEAVE_QUESTION)
    second = ask(seeded_member, conversation, "What is the late cancellation fee for an appointment?")

    detail = seeded_member.get(f"/api/conversations/{conversation}").json()
    assert detail["title"] == LEAVE_QUESTION  # named after the first question
    assert detail["message_count"] == 4
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert [m["id"] for m in detail["messages"]][1::2] == [first["id"], second["id"]]
    assert "50%" in second["content"]
    assert detail["messages"][3]["citations"][0]["document_title"] == "Patient Cancellation and Refund Policy"
    assert detail["updated_at"] >= detail["created_at"]


def test_a_follow_up_is_understood_in_the_context_of_the_previous_question(seeded_member: TestClient, seeded: Container) -> None:
    conversation = new_conversation(seeded_member)
    ask(seeded_member, conversation, LEAVE_QUESTION)
    follow_up = ask(seeded_member, conversation, "And for part-time employees?")
    assert not follow_up["abstained"]
    assert "pro rata" in follow_up["content"]
    with seeded.session_factory() as session:
        retrieval = session.get(Message, follow_up["id"]).retrieval
    assert retrieval["expanded_with_previous_turn"] is True
    assert retrieval["query"] == f"{LEAVE_QUESTION} And for part-time employees?"


def test_a_new_unanswerable_question_is_not_answered_with_the_previous_topic(seeded_member: TestClient, seeded: Container) -> None:
    conversation = new_conversation(seeded_member)
    ask(seeded_member, conversation, LEAVE_QUESTION)
    unrelated = ask(seeded_member, conversation, UNANSWERABLE)
    assert unrelated["abstained"]
    with seeded.session_factory() as session:
        assert session.get(Message, unrelated["id"]).retrieval["expanded_with_previous_turn"] is False


def test_follow_up_cues() -> None:
    assert has_follow_up_cue("And for part-time employees?")
    assert has_follow_up_cue("What about contractors?")
    assert has_follow_up_cue("Is it paid?")
    assert not has_follow_up_cue("How long must a password be?")
    assert not has_follow_up_cue("Is there staff parking at the Rookfield clinic?")
    assert not has_follow_up_cue("thanks")


def test_conversation_list_rename_and_delete(seeded: Container) -> None:
    client = sign_in(TestClient(create_app(seeded.settings, container=seeded)), MEMBER)
    for existing in client.get("/api/conversations").json():
        client.delete(f"/api/conversations/{existing['id']}")

    older = new_conversation(client)
    newer = new_conversation(client, title="  Pinned topic  ")
    ask(client, older, "How long must a password be?")  # most recently active comes first

    listed = client.get("/api/conversations").json()
    assert [c["id"] for c in listed] == [older, newer]
    assert [c["title"] for c in listed] == ["How long must a password be?", "Pinned topic"]
    assert [c["message_count"] for c in listed] == [2, 0]

    renamed = client.patch(f"/api/conversations/{older}", json={"title": "Passwords"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Passwords"
    assert client.patch(f"/api/conversations/{older}", json={"title": ""}).status_code == 422

    assert client.delete(f"/api/conversations/{older}").status_code == 204
    assert client.get(f"/api/conversations/{older}").status_code == 404
    assert [c["id"] for c in client.get("/api/conversations").json()] == [newer]
    with seeded.session_factory() as session:  # messages and citations go with the conversation
        assert session.execute(select(Message).where(Message.conversation_id == older)).scalars().all() == []


def test_titles_are_shortened() -> None:
    assert make_title("  How   many days? ") == "How many days?"
    long = make_title("word " * 40)
    assert len(long) == 60 and long.endswith("…")


def test_feedback_can_be_given_changed_and_cleared(seeded_member: TestClient) -> None:
    conversation = new_conversation(seeded_member)
    answer = ask(seeded_member, conversation, LEAVE_QUESTION)
    path = f"/api/messages/{answer['id']}/feedback"

    assert seeded_member.post(path, json={"value": 1}).json()["feedback"] == 1
    assert seeded_member.post(path, json={"value": -1}).json()["feedback"] == -1
    assert seeded_member.get(f"/api/conversations/{conversation}").json()["messages"][1]["feedback"] == -1
    assert seeded_member.post(path, json={"value": 0}).json()["feedback"] is None
    assert seeded_member.post(path, json={"value": 5}).status_code == 422

    question_id = seeded_member.get(f"/api/conversations/{conversation}").json()["messages"][0]["id"]
    assert seeded_member.post(f"/api/messages/{question_id}/feedback", json={"value": 1}).status_code == 404  # not an answer
    assert seeded_member.post("/api/messages/999999/feedback", json={"value": 1}).status_code == 404


def test_starter_questions_come_from_the_collections(seeded_member: TestClient) -> None:
    suggestions = seeded_member.get("/api/suggestions").json()
    assert len(suggestions) == 6 and len(set(suggestions)) == 6
    assert "How long does a password have to be?" in suggestions
    assert seeded_member.get("/api/suggestions", params={"limit": 2}).json() == suggestions[:2]


def test_every_starter_question_gets_a_cited_answer(seeded_member: TestClient) -> None:
    for question in seeded_member.get("/api/suggestions").json():
        answer = ask(seeded_member, new_conversation(seeded_member), question)
        assert not answer["abstained"], question
        assert answer["citations"], question


# -- the Claude engine behind the same API (faked SDK client) --------------------------------
def claude_container(tmp_path, *script, **settings) -> tuple[Container, FakeAnthropic]:
    fake = FakeAnthropic(*script)
    engine = ClaudeEngine(model="claude-opus-5-5", client=fake)
    container = build_container(make_settings(tmp_path / "claude", **settings), answer_engine=engine)
    seed(container, with_activity=False)
    return container, fake


@pytest.fixture
def claude_app(tmp_path) -> Iterator[tuple[TestClient, FakeAnthropic, Container]]:
    """A seeded app whose answer engine is Claude backed by a fake SDK client (scripted per test)."""
    container, fake = claude_container(tmp_path)
    client = sign_in(TestClient(create_app(container.settings, container=container)), MEMBER)
    yield client, fake, container
    container.close()


def cite_sentence(documents: list[dict], needle: str) -> dict:
    """Build a wire-format citation for the sentence containing ``needle`` in the documents sent to Claude."""
    for index, document in enumerate(documents):
        text = document["source"]["data"]
        position = text.find(needle)
        if position >= 0:
            start = text.rfind(". ", 0, position) + 2 if ". " in text[:position] else 0
            end = text.find(".", position) + 1
            return char_citation(index, start, end, text[start:end], document["title"])
    raise AssertionError(f"{needle!r} was not among the passages sent to Claude")


def test_claude_answers_are_stored_with_their_citations(claude_app) -> None:
    client, fake, container = claude_app
    conversation = new_conversation(client)

    def respond(request: dict) -> list[dict]:
        # Cite a sentence from the passages that retrieval really sent.
        documents = [block for block in request["messages"][-1]["content"] if block["type"] == "document"]
        return wire_message(
            [("Full-time employees get ", []), ("25 days of paid annual leave", [cite_sentence(documents, "25 days")]), (".", [])]
        )

    fake.script = [respond]
    answer = ask(client, conversation, LEAVE_QUESTION)

    assert answer["content"] == "Full-time employees get 25 days of paid annual leave [1]."
    assert (answer["engine"], answer["model"], answer["engine_label"]) == ("claude", "claude-opus-5-5", "Claude · claude-opus-5-5")
    (citation,) = answer["citations"]
    assert citation["document_title"] == "Employee Handbook"
    assert citation["heading_path"] == ["Leave", "Annual leave"]
    assert "25 days" in citation["quote"]
    assert citation["passage"][citation["start_char"] : citation["end_char"]] == citation["quote"]

    # The request Claude received: retrieved passages as citable documents, then the question.
    content = fake.last_request["messages"][-1]["content"]
    assert content[-1] == {"type": "text", "text": LEAVE_QUESTION}
    assert 1 <= len(content) - 1 <= container.settings.top_k
    assert all(block["citations"] == {"enabled": True} for block in content[:-1])
    assert client.get("/api/meta").json()["engine"] == {"name": "claude", "label": "Claude · claude-opus-5-5", "model": "claude-opus-5-5"}


def test_a_question_with_no_lexical_evidence_never_reaches_claude(claude_app) -> None:
    client, fake, _ = claude_app
    for question in NO_EVIDENCE_QUESTIONS:
        answer = ask(client, new_conversation(client), question)
        assert answer["abstained"] and answer["abstain_reason"] == "weak_retrieval", question
        assert answer["engine"] == "claude"
    assert fake.calls == []  # no tokens were spent


def test_a_related_question_reaches_claude_which_declines_it(claude_app) -> None:
    # "office" and "bring" occur in the handbook, so there is lexical evidence, but no passage
    # is about pets. The strict gate turns this away; with Claude the model reads the passages
    # and says so itself.
    client, fake, _ = claude_app
    fake.script = [wire_message([("[[NOT_FOUND]]", [])])]
    answer = ask(client, new_conversation(client), UNANSWERABLE)
    assert answer["abstained"] and answer["abstain_reason"] == "unsupported"
    assert answer["content"] == ABSTAIN_TEXT and answer["citations"] == []
    assert len(fake.calls) == 1


def test_a_paraphrased_question_is_declined_offline_but_answered_by_claude(claude_app, seeded_member: TestClient) -> None:
    # The right passage is retrieved, but the wording shares too little with it for the strict
    # gate. This was a wrong refusal in the first live run with Claude (2026-11-10).
    offline = ask(seeded_member, new_conversation(seeded_member), PARAPHRASED)
    assert offline["abstained"] and offline["abstain_reason"] == "weak_retrieval"
    assert offline["confidence"] < 0.55

    client, fake, _ = claude_app

    def respond(request: dict) -> list[dict]:
        documents = [block for block in request["messages"][-1]["content"] if block["type"] == "document"]
        return wire_message(
            [
                ("The hotel limit is ", []),
                ("£120 a night, including breakfast, or £165 a night in London", [cite_sentence(documents, "£120")]),
                (".", []),
            ]
        )

    fake.script = [respond]
    answer = ask(client, new_conversation(client), PARAPHRASED)
    assert not answer["abstained"] and answer["engine"] == "claude"
    assert answer["content"] == "The hotel limit is £120 a night, including breakfast, or £165 a night in London [1]."
    (citation,) = answer["citations"]
    assert citation["heading_path"][-1] == "Hotels"
    assert "£120" in citation["quote"]
    assert citation["passage"][citation["start_char"] : citation["end_char"]] == citation["quote"]
    assert answer["confidence"] == offline["confidence"]  # same retrieval, different gate


def test_the_relaxed_gate_can_be_switched_off(tmp_path) -> None:
    container, fake = claude_container(tmp_path, claude_min_coverage=0.55)
    try:
        client = sign_in(TestClient(create_app(container.settings, container=container)), MEMBER)
        answer = ask(client, new_conversation(client), PARAPHRASED)
        assert answer["abstained"] and answer["abstain_reason"] == "weak_retrieval"
        assert fake.calls == []
    finally:
        container.close()


def test_when_claude_fails_on_a_weakly_matched_question_the_offline_engine_declines(claude_app) -> None:
    # The question reached Claude through the relaxed gate. The extractive engine is not
    # allowed to answer from a passage that does not cover the question.
    client, fake, _ = claude_app
    fake.script = [api_error(anthropic.RateLimitError, 429)]
    conversation = new_conversation(client)
    with client.stream("POST", f"/api/conversations/{conversation}/messages", json={"content": PARAPHRASED}) as response:
        events = parse_sse("".join(response.iter_text()))
    names = [name for name, _ in events]

    assert "reset" in names and names[-1] == "done" and "error" not in names
    final = events[-1][1]["message"]
    assert final["engine"] == "offline"
    assert final["abstained"] and final["abstain_reason"] == "weak_retrieval"
    assert final["content"] == ABSTAIN_TEXT and final["citations"] == []
    assert final["notice"].startswith("Claude is rate-limiting requests right now.")


def test_claude_saying_not_found_is_an_abstention(claude_app) -> None:
    client, fake, _ = claude_app
    fake.script = [wire_message([("[[NOT_FOUND]]", [])])]
    answer = ask(client, new_conversation(client), LEAVE_QUESTION)
    assert answer["abstained"] and answer["abstain_reason"] == "unsupported"
    assert answer["content"] == ABSTAIN_TEXT and answer["citations"] == []


def test_conversation_history_is_passed_to_claude(claude_app) -> None:
    client, fake, _ = claude_app
    conversation = new_conversation(client)
    fake.script = [wire_message([("[[NOT_FOUND]]", [])]), wire_message([("[[NOT_FOUND]]", [])])]
    ask(client, conversation, LEAVE_QUESTION)
    ask(client, conversation, "And for part-time employees?")
    messages = fake.last_request["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == LEAVE_QUESTION
    assert messages[1]["content"] == ABSTAIN_TEXT
    assert messages[2]["content"][-1] == {"type": "text", "text": "And for part-time employees?"}


def test_when_claude_fails_the_offline_engine_answers_and_says_so(claude_app) -> None:
    client, fake, _ = claude_app
    fake.script = [api_error(anthropic.RateLimitError, 429)]
    conversation = new_conversation(client)
    with client.stream("POST", f"/api/conversations/{conversation}/messages", json={"content": LEAVE_QUESTION}) as response:
        events = parse_sse("".join(response.iter_text()))
    names = [name for name, _ in events]

    assert "reset" in names and names[-1] == "done" and "error" not in names
    assert events[names.index("reset")][1]["engine"]["name"] == "offline"
    final = events[-1][1]["message"]
    assert (final["engine"], final["engine_label"]) == ("offline", "Extractive (offline) mode")
    assert "25 days" in final["content"] and final["citations"]
    assert final["notice"] == (
        "Claude is rate-limiting requests right now. This answer was produced in extractive (offline) mode instead."
    )
    # Only the text streamed after the reset belongs to the final answer.
    after_reset = "".join(data["text"] for name, data in events[names.index("reset") :] if name == "delta")
    assert after_reset == final["content"]


def test_without_fallback_a_claude_failure_is_reported_as_an_error(tmp_path) -> None:
    container, fake = claude_container(tmp_path, api_error(anthropic.AuthenticationError, 401), api_error(anthropic.AuthenticationError, 401), fallback_to_offline=False)
    try:
        client = sign_in(TestClient(create_app(container.settings, container=container)), MEMBER)
        conversation = new_conversation(client)
        with client.stream("POST", f"/api/conversations/{conversation}/messages", json={"content": LEAVE_QUESTION}) as response:
            events = parse_sse("".join(response.iter_text()))
        assert events[-1] == ("error", {"message": "Claude rejected the API key. Check ANTHROPIC_API_KEY."})

        plain = client.post(f"/api/conversations/{conversation}/messages", json={"content": LEAVE_QUESTION, "stream": False})
        assert plain.status_code == 502
        assert plain.json()["detail"] == "Claude rejected the API key. Check ANTHROPIC_API_KEY."
        # The questions were stored; no answer was invented.
        assert [m["role"] for m in client.get(f"/api/conversations/{conversation}").json()["messages"]] == ["user", "user"]
    finally:
        container.close()
