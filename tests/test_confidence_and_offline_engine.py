"""The abstention gate and the offline (extractive) answer engine."""

from __future__ import annotations

import pytest

from sourcewise.answering import (
    ABSTAIN_TEXT,
    AnswerRequest,
    CitationAdded,
    Completed,
    ExtractiveEngine,
    Passage,
    TextDelta,
    assess_retrieval,
)
from sourcewise.answering.confidence import UNSEEN_TERM_WEIGHT, informativeness, term_weights
from sourcewise.answering.types import CitationLedger

from .fakes import FakeStats

# Document frequencies in a pretend corpus of 100 chunks.
STATS = FakeStats(
    {
        "annual": 4, "leav": 9, "dai": 30, "employe": 25, "full": 12, "time": 14, "part": 6, "carri": 3,
        "unus": 2, "staff": 20, "clinic": 40, "park": 2, "rookfield": 1, "hotel": 1, "limit": 8, "night": 2,
        "london": 1, "password": 6, "charact": 1, "long": 5, "float": 2, "cash": 5, "bank": 3, "meal": 2,
        "lunch": 1, "even": 3, "alcohol": 2, "abroad": 1, "approv": 9, "countri": 2, "work": 45, "vpn": 3,
        "connect": 5, "polici": 35,
    }
)


def passage(chunk_id: int, text: str, *, section: tuple[str, ...] = (), title: str = "Employee Handbook", score: float = 10.0, page: int | None = None) -> Passage:
    return Passage(
        chunk_id=chunk_id, document_id=1, document_title=title, document_kind="md", collection_name="People",
        heading_path=section, page_start=page, page_end=page, text=text, score=score,
    )


LEAVE = passage(
    1,
    "The leave year runs from 1 January to 31 December. Full-time employees receive 25 days of paid annual "
    "leave each year, plus the eight public holidays. Part-time employees receive the same entitlement pro "
    "rata to their contracted hours. After five years of continuous service your entitlement rises to 27 "
    "days, and after ten years to 30 days. Requests are made in RotaBoard and need approval from a manager "
    "at least two weeks before the first day of absence.",
    section=("Leave", "Annual leave"),
)


def run(engine: ExtractiveEngine, question: str, passages: list[Passage], **kwargs):
    events = list(engine.answer(AnswerRequest(question=question, passages=passages, **kwargs)))
    assert isinstance(events[-1], Completed)
    return events, events[-1].result


# -- the retrieval gate ------------------------------------------------------------------------
def gate(question: str, passages: list[Passage], *, min_coverage: float = 0.55, min_evidence: float = 0.5):
    return assess_retrieval(question, passages, STATS, min_coverage=min_coverage, min_evidence=min_evidence)


def test_full_coverage_when_every_question_term_is_in_the_passage() -> None:
    confidence = gate("How many days of annual leave do full-time employees get?", [LEAVE])
    assert confidence.coverage == 1.0
    assert confidence.missing_terms == ()
    assert set(confidence.matched_terms) == {"dai", "annual", "leav", "full", "time", "employe"}
    assert confidence.sufficient


def test_coverage_and_evidence_are_idf_weighted() -> None:
    confidence = gate("annual leave parking", [LEAVE])
    weights = {term: informativeness(STATS.document_frequencies([term])[term], 100) for term in ("annual", "leav", "park")}
    matched = weights["annual"] + weights["leav"]
    assert confidence.coverage == pytest.approx(matched / sum(weights.values()), abs=1e-4)
    assert confidence.evidence == pytest.approx(matched / informativeness(1, 100), abs=1e-4)
    assert confidence.missing_terms == ("park",)


def test_matching_only_everyday_words_is_not_enough() -> None:
    # "staff" and "clinic" are everywhere; "parking" and "Rookfield" are what the question is about.
    generic = passage(2, "All clinic staff wear their ID badge.", section=("Conduct",))
    confidence = gate("Is there staff parking at the Rookfield clinic?", [generic])
    assert set(confidence.matched_terms) == {"staff", "clinic"}
    assert confidence.coverage < 0.3
    assert not confidence.sufficient


def test_evidence_measures_how_much_was_matched_in_absolute_terms() -> None:
    clinics = passage(3, "Our clinics are Eastmere and Rookfield.")
    specific = gate("Rookfield?", [clinics])
    assert specific.coverage == 1.0
    assert specific.evidence == pytest.approx(1.0, abs=1e-4)  # exactly one rare term's worth
    assert specific.sufficient
    # Full coverage of a question that consists of one ubiquitous word is still not a match.
    ubiquitous = gate("Clinics?", [clinics])
    assert ubiquitous.coverage == 1.0
    assert ubiquitous.evidence < 0.5
    assert not ubiquitous.sufficient
    assert gate("Clinics?", [clinics], min_evidence=0.0).sufficient


def test_terms_unknown_to_the_corpus_count_at_reduced_weight() -> None:
    weights = term_weights(["annual", "zeppelin"], STATS)
    assert weights["annual"] == pytest.approx(informativeness(4, 100))
    assert weights["zeppelin"] == pytest.approx(informativeness(0, 100) * UNSEEN_TERM_WEIGHT)
    with_unknown = gate("annual leave zeppelin", [LEAVE])
    assert 0.55 < with_unknown.coverage < 1.0
    assert with_unknown.missing_terms == ("zeppelin",)


def test_headings_and_title_count_towards_coverage() -> None:
    body_only = passage(4, "Twenty-five days are granted each year.", section=())
    under_heading = passage(4, "Twenty-five days are granted each year.", section=("Leave", "Annual leave"))
    assert gate("annual leave days", [body_only]).coverage < gate("annual leave days", [under_heading]).coverage == 1.0


def test_the_best_of_the_top_passages_is_used() -> None:
    weak = passage(5, "Policy documents are reviewed annually.", score=12.0)
    confidence = gate("annual leave for full-time employees", [weak, LEAVE])
    assert confidence.coverage == 1.0 and confidence.sufficient
    assert not assess_retrieval(
        "annual leave for full-time employees", [weak, LEAVE], STATS, min_coverage=0.55, min_evidence=0.5, consider=1
    ).sufficient


def test_nothing_to_search_for_or_nothing_found_is_insufficient() -> None:
    assert not gate("Hello, thanks!", [LEAVE]).sufficient
    empty = gate("annual leave", [])
    assert (empty.coverage, empty.evidence, empty.sufficient) == (0.0, 0.0, False)
    assert empty.missing_terms == ("annual", "leav")


# -- citations ---------------------------------------------------------------------------------
def test_citation_ledger_numbers_spans_in_order_of_first_use() -> None:
    ledger = CitationLedger()
    first, new_first = ledger.cite(LEAVE, 0, 50)
    second, new_second = ledger.cite(LEAVE, 51, 100)
    again, new_again = ledger.cite(LEAVE, 0, 50)
    assert (first.number, second.number, again.number) == (1, 2, 1)
    assert (new_first, new_second, new_again) == (True, True, False)
    assert first.quote == LEAVE.text[0:50]
    assert [c.number for c in ledger.citations] == [1, 2]


def test_citation_ledger_clamps_spans_to_the_passage() -> None:
    citation, _ = CitationLedger().cite(LEAVE, -5, 10**6)
    assert (citation.start, citation.end) == (0, len(LEAVE.text))


# -- the extractive engine ---------------------------------------------------------------------
@pytest.fixture
def engine() -> ExtractiveEngine:
    return ExtractiveEngine(STATS)


def test_answer_quotes_the_best_sentence_and_cites_its_exact_span(engine: ExtractiveEngine) -> None:
    _, result = run(engine, "How many days of annual leave do full-time employees get?", [LEAVE])
    assert not result.abstained
    assert "Full-time employees receive 25 days of paid annual leave each year" in result.text
    assert result.text.endswith("[1]")
    (citation,) = result.citations
    assert citation.passage is LEAVE
    assert LEAVE.text[citation.start : citation.end] == citation.quote
    # Everything in the answer is a verbatim quotation of the cited span.
    assert result.text.removesuffix(" [1]") == citation.quote


def test_streamed_deltas_add_up_to_the_final_answer(engine: ExtractiveEngine) -> None:
    events, result = run(engine, "How many days of annual leave do full-time employees get?", [LEAVE])
    assert "".join(event.text for event in events if isinstance(event, TextDelta)) == result.text
    kinds = [type(event) for event in events]
    # The citation is announced before its marker is written.
    marker = next(i for i, event in enumerate(events) if isinstance(event, TextDelta) and event.text == "[1]")
    assert kinds.index(CitationAdded) < marker
    assert sum(1 for kind in kinds if kind is Completed) == 1


def test_the_answer_comes_from_the_passage_that_matches_not_just_the_first(engine: ExtractiveEngine) -> None:
    hotels = passage(7, "Hotel rooms are booked through the travel desk. The limit is £120 a night, or £165 a night in London.", section=("Hotels",), title="Travel and Expense Policy", score=6.0)
    _, result = run(engine, "What is the hotel limit per night in London?", [LEAVE, hotels])
    assert "£165 a night in London" in result.text
    assert [c.passage.chunk_id for c in result.citations] == [7]


def test_a_short_paragraph_is_quoted_whole(engine: ExtractiveEngine) -> None:
    hotels = passage(7, "Hotel rooms are booked through the travel desk. The limit is £120 a night.", section=("Hotels",))
    _, result = run(engine, "Who books hotel rooms?", [hotels])
    assert result.text == "Hotel rooms are booked through the travel desk. The limit is £120 a night. [1]"
    assert (result.citations[0].start, result.citations[0].end) == (0, len(hotels.text))


def test_only_the_paragraph_that_answers_is_quoted(engine: ExtractiveEngine) -> None:
    two = passage(
        18,
        "Requests for long breaks need a manager's approval.\n\n"
        "You may carry over up to five unused days. Carried-over days must be used by 31 March.",
        section=("Leave",),
    )
    _, result = run(engine, "How many unused days can I carry over?", [two])
    assert result.text == "You may carry over up to five unused days. Carried-over days must be used by 31 March. [1]"
    citation = result.citations[0]
    assert two.text[citation.start : citation.end] == result.text.removesuffix(" [1]")


def test_a_pronoun_sentence_brings_its_antecedent() -> None:
    abroad = passage(
        8,
        "Working from outside the United Kingdom is limited to 10 working days in a calendar year. It needs "
        "approval from your head of department before you travel to another country, and some countries are "
        "blocked. " + "Unrelated filler sentence about meeting rooms and calendars that pads the passage out. " * 4,
        section=("Working abroad",),
    )
    _, result = run(ExtractiveEngine(STATS, whole_block_chars=0), "Do I need approval to work in another country?", [abroad])
    assert result.text.startswith("Working from outside the United Kingdom is limited to 10 working days")
    assert "It needs approval from your head of department" in result.text
    assert "filler" not in result.text
    assert len(result.citations) == 1


def test_a_lead_in_sentence_brings_the_list_it_introduces() -> None:
    meals = passage(
        9,
        "When you stay overnight you may claim meals. The meal limits are:\n\n"
        "Meal: Breakfast; Limit: £8\nMeal: Lunch; Limit: £12\nMeal: Evening meal; Limit: £25\n\n"
        "Alcohol is not reimbursed. " + "Padding sentence about receipts and statements to make the passage long. " * 4,
        section=("Meals",),
    )
    _, result = run(ExtractiveEngine(STATS, whole_block_chars=0), "What are the meal limits?", [meals])
    assert result.text == (
        "The meal limits are:\nMeal: Breakfast; Limit: £8\nMeal: Lunch; Limit: £12\nMeal: Evening meal; Limit: £25 [1]"
    )
    assert result.citations[0].quote.startswith("The meal limits are:")
    assert result.citations[0].quote.endswith("Limit: £25")


def test_faq_questions_frame_the_answer_but_are_never_quoted(engine: ExtractiveEngine) -> None:
    faq = passage(10, "How do I connect to the VPN? Open CalderLink from the system tray and sign in.", section=("Remote",), title="IT FAQ")
    _, result = run(engine, "How do I connect to the VPN?", [faq])
    assert not result.abstained
    assert result.text == "Open CalderLink from the system tray and sign in. [1]"


def test_a_list_item_is_quoted_without_its_dash_and_with_its_lead_in() -> None:
    rules = passage(11, "At home:\n\n- Connect through the VPN before opening ClinicDesk.\n- Lock your screen.", section=("Security",))
    _, result = run(ExtractiveEngine(STATS, whole_block_chars=0), "When do I connect to the VPN?", [rules])
    assert result.text == "At home:\nConnect through the VPN before opening ClinicDesk. [1]"
    # The citation covers the same stretch of the passage, exactly as it is stored.
    assert result.citations[0].quote == "At home:\n\n- Connect through the VPN before opening ClinicDesk."


def test_matching_rows_of_a_table_are_quoted_together() -> None:
    approvals = passage(
        17,
        "Value: Up to £250; Approver: Line manager\nValue: £250 to £1,000; Approver: Head of department\n"
        "Value: Over £1,000; Approver: Finance Director\n\n"
        + "Nobody approves their own claim, and a manager's claim goes to their own line manager. " * 4,
        section=("Approval limits",),
    )
    _, result = run(ExtractiveEngine(STATS, whole_block_chars=0), "Who is the approver for £1,000?", [approvals])
    assert result.text == (
        "Value: £250 to £1,000; Approver: Head of department\nValue: Over £1,000; Approver: Finance Director [1]"
    )


def test_a_sentence_seen_twice_through_overlapping_chunks_is_quoted_once(engine: ExtractiveEngine) -> None:
    sentence = "The cash float is counted by two people every morning before the bank run."
    first = passage(12, sentence + " " + "Filler about the waiting room and the hand sanitiser that is long enough. " * 5, score=9.0)
    second = passage(13, sentence + " " + "Different filler about the card terminal and the receipts, also long. " * 5, score=8.0)
    _, result = run(engine, "Who counts the cash float?", [first, second])
    assert result.text.count(sentence) == 1
    assert [c.passage.chunk_id for c in result.citations] == [12]


def test_a_second_quotation_is_added_only_for_a_part_of_the_question_not_yet_covered() -> None:
    engine = ExtractiveEngine(STATS, whole_block_chars=0)
    hotels = passage(14, "The hotel limit is £120 a night. " + "Filler about booking through the travel desk well ahead. " * 6, section=("Hotels",), score=9.0)
    meals = passage(15, "The lunch limit is £12 a day. " + "Filler about itemised receipts and card statements again. " * 6, section=("Meals",), score=8.5)
    _, both = run(engine, "What are the hotel limit and the lunch limit?", [hotels, meals])
    assert both.text == "The hotel limit is £120 a night. [1]\n\nThe lunch limit is £12 a day. [2]"
    assert [c.passage.chunk_id for c in both.citations] == [14, 15]
    _, one = run(engine, "What is the hotel limit?", [hotels, meals])
    assert one.text == "The hotel limit is £120 a night. [1]"


def test_engine_abstains_when_no_sentence_supports_the_question(engine: ExtractiveEngine) -> None:
    events, result = run(engine, "Is there parking at the Rookfield clinic?", [LEAVE])
    assert result.abstained and result.abstain_reason == "unsupported"
    assert result.text == ABSTAIN_TEXT
    assert result.citations == []
    assert not any(isinstance(event, TextDelta) for event in events)


def test_engine_abstains_when_support_is_below_the_threshold() -> None:
    weak = passage(16, "Staff at every clinic wear a badge.", section=("Conduct",))
    question = "Is there staff parking at the Rookfield clinic?"
    assert run(ExtractiveEngine(STATS, min_support=0.5), question, [weak])[1].abstained
    assert not run(ExtractiveEngine(STATS, min_support=0.05), question, [weak])[1].abstained


def test_engine_abstains_without_passages_or_search_terms(engine: ExtractiveEngine) -> None:
    assert run(engine, "annual leave", [])[1].abstained
    assert run(engine, "hello there", [LEAVE])[1].abstained


def test_a_follow_up_is_answered_about_its_own_subject(engine: ExtractiveEngine) -> None:
    _, result = run(
        engine,
        "And for part-time employees?",
        [LEAVE],
        search_query="How many days of annual leave do full-time employees get? And for part-time employees?",
    )
    assert "Part-time employees receive the same entitlement pro rata" in result.text


def test_engine_is_deterministic(engine: ExtractiveEngine) -> None:
    question = "How many days of annual leave do full-time employees get?"
    assert run(engine, question, [LEAVE])[1].text == run(engine, question, [LEAVE])[1].text


def test_engine_identifies_itself_as_offline(engine: ExtractiveEngine) -> None:
    assert (engine.name, engine.label, engine.model) == ("offline", "Extractive (offline) mode", None)
