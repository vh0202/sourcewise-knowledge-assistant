"""Stemmer, analyzer and sentence segmentation."""

from __future__ import annotations

import pytest

from sourcewise.text import STOPWORDS, analyze, query_terms, split_sentences, stem, tokenize

# Reference outputs of the Porter (1980) algorithm, including the examples from the paper.
PORTER_PAIRS = {
    "caresses": "caress", "ponies": "poni", "ties": "ti", "caress": "caress", "cats": "cat",
    "feed": "feed", "agreed": "agre", "plastered": "plaster", "bled": "bled", "motoring": "motor",
    "sing": "sing", "conflated": "conflat", "troubled": "troubl", "sized": "size", "hopping": "hop",
    "tanned": "tan", "falling": "fall", "hissing": "hiss", "fizzed": "fizz", "failing": "fail",
    "filing": "file", "happy": "happi", "sky": "sky", "relational": "relat", "conditional": "condit",
    "rational": "ration", "digitizer": "digit", "vietnamization": "vietnam", "operator": "oper",
    "feudalism": "feudal", "decisiveness": "decis", "hopefulness": "hope", "callousness": "callous",
    "formality": "formal", "sensitivity": "sensit", "sensibility": "sensibl", "triplicate": "triplic",
    "formative": "form", "formalize": "formal", "electricity": "electr", "electrical": "electr",
    "hopeful": "hope", "goodness": "good", "revival": "reviv", "allowance": "allow", "inference": "infer",
    "airliner": "airlin", "gyroscopic": "gyroscop", "adjustable": "adjust", "defensible": "defens",
    "irritant": "irrit", "replacement": "replac", "adjustment": "adjust", "dependent": "depend",
    "adoption": "adopt", "communism": "commun", "activate": "activ", "angularity": "angular",
    "homologous": "homolog", "effective": "effect", "bowdlerize": "bowdler", "probate": "probat",
    "rate": "rate", "cease": "ceas", "controlling": "control", "rolling": "roll",
}


@pytest.mark.parametrize(("word", "expected"), PORTER_PAIRS.items())
def test_porter_stemmer_matches_reference_outputs(word: str, expected: str) -> None:
    assert stem(word) == expected


@pytest.mark.parametrize(
    "family",
    [
        ("refund", "refunds", "refunded", "refunding", "refundable"),
        ("cancel", "cancels", "cancelled", "cancellation", "cancellations"),
        ("policy", "policies"),
        ("encrypt", "encrypted", "encryption"),
        ("reimburse", "reimbursed", "reimbursement"),
    ],
)
def test_inflections_share_a_stem(family: tuple[str, ...]) -> None:
    assert len({stem(word) for word in family}) == 1


def test_stemmer_leaves_short_and_non_alphabetic_tokens_alone() -> None:
    assert stem("it") == "it"
    assert stem("45p") == "45p"
    assert stem("2026") == "2026"


def test_tokenize_folds_case_and_accents_and_joins_thousands() -> None:
    assert tokenize("Café RÉSUMÉ") == ["cafe", "resume"]
    assert tokenize("up to £1,500 or 12,000.50") == ["up", "to", "1500", "or", "12000", "50"]
    # A comma that is not a thousands separator still splits.
    assert tokenize("1,2 and 10,25") == ["1", "2", "and", "10", "25"]


def test_analyze_removes_stopwords_then_stems() -> None:
    assert analyze("The refunds are approved by the clinic managers") == ["refund", "approv", "clinic", "manag"]
    # Stop-words are matched on raw tokens, so "allowed" goes but "allowance" stays.
    assert analyze("Am I allowed a home office allowance?") == ["home", "offic", "allow"]


def test_contraction_fragments_are_not_terms() -> None:
    assert analyze("I'm sure we'd say it's fine, isn't it?") == ["sure", "fine"]
    assert {"m", "d", "s", "t", "ll", "ve", "re"} <= STOPWORDS


def test_query_terms_are_distinct_and_drop_degree_words_after_how() -> None:
    assert query_terms("How long is the probation period, and how long is the notice period?") == [
        "probat", "period", "notic",
    ]
    assert query_terms("How often is cash banked?") == ["cash", "bank"]
    # "long" is only dropped as part of "how long".
    assert "long" in query_terms("Is a long holiday allowed?")


def test_query_terms_of_small_talk_are_empty() -> None:
    assert query_terms("Hi, thanks!") == []


def _sentences(text: str) -> list[str]:
    return [text[start:end] for start, end in split_sentences(text)]


def test_sentences_are_split_on_terminal_punctuation() -> None:
    assert _sentences("Staff get 25 days. Is it paid? Yes! Carry over five.") == [
        "Staff get 25 days.", "Is it paid?", "Yes!", "Carry over five.",
    ]


def test_abbreviations_decimals_and_initials_do_not_end_sentences() -> None:
    text = "Claim 45p per mile, e.g. for clinic visits. Dr. A. Reyes approves claims over £2.50. See No. 4 below."
    assert _sentences(text) == [
        "Claim 45p per mile, e.g. for clinic visits.",
        "Dr. A. Reyes approves claims over £2.50.",
        "See No. 4 below.",
    ]


def test_no_as_a_one_word_sentence_is_split() -> None:
    assert _sentences("No. Personal computers cannot connect.") == ["No.", "Personal computers cannot connect."]


def test_line_breaks_are_boundaries_and_list_markers_stay_attached() -> None:
    text = "The limits are:\n- Lunch: £12\n- Dinner: £25\n\n1. Lock the drawer. Count the float."
    assert _sentences(text) == [
        "The limits are:", "- Lunch: £12", "- Dinner: £25", "1. Lock the drawer.", "Count the float.",
    ]


def test_sentence_spans_are_exact_ordered_and_non_overlapping() -> None:
    text = "  First sentence here.   Second one follows!\n\n   Third, after a blank line.  "
    spans = split_sentences(text)
    assert [text[s:e] for s, e in spans] == ["First sentence here.", "Second one follows!", "Third, after a blank line."]
    assert all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1))
    assert all(text[s:e] == text[s:e].strip() for s, e in spans)


def test_empty_text_has_no_sentences() -> None:
    assert split_sentences("") == []
    assert split_sentences(" \n \n") == []
