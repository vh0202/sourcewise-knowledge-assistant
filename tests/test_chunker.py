"""Normalisation and heading-aware chunking with overlap."""

from __future__ import annotations

from itertools import pairwise

import pytest

from sourcewise.ingestion import Block, ChunkingConfig, chunk_document, normalize_blocks, normalize_text
from sourcewise.text import split_sentences


def paragraph(text: str, page: int | None = None) -> Block:
    return Block("paragraph", text, page=page)


def heading(text: str, level: int) -> Block:
    return Block("heading", text, level=level)


def sentences(count: int, prefix: str = "Sentence") -> str:
    return " ".join(f"{prefix} number {i} has exactly these few words in it." for i in range(1, count + 1))


# -- normalisation -----------------------------------------------------------------------------
def test_normalize_text_folds_compatibility_forms_and_strips_invisible_characters() -> None:
    assert normalize_text("ofﬁce   hours are​ 9–5 .") == "office hours are 9–5."
    assert normalize_text("soft­hyphen﻿") == "softhyphen"


def test_normalize_text_keeps_code_layout() -> None:
    assert normalize_text("def f():   \r\n    return 1\n\n", preserve_lines=True) == "def f():\n    return 1"


def test_normalize_blocks_drops_empty_and_repeated_blocks() -> None:
    blocks = [
        heading("  Title ", 1),
        paragraph("Text."),
        paragraph("Text."),
        paragraph("   "),
        Block("heading", "Deep", level=9),
        paragraph("More."),
    ]
    cleaned, stats = normalize_blocks(blocks)
    assert [(b.kind, b.level, b.text) for b in cleaned] == [
        ("heading", 1, "Title"), ("paragraph", 0, "Text."), ("heading", 6, "Deep"), ("paragraph", 0, "More."),
    ]
    assert (stats.blocks_in, stats.blocks_out, stats.dropped_empty, stats.dropped_duplicates) == (6, 4, 1, 1)
    assert stats.characters == len("Title") + len("Text.") + len("Deep") + len("More.")


# -- chunking ----------------------------------------------------------------------------------
def test_each_section_becomes_its_own_chunk_with_its_heading_path() -> None:
    blocks = [
        heading("Employee Handbook", 1),
        paragraph("Welcome to the handbook."),
        heading("Leave", 2),
        heading("Annual leave", 3),
        paragraph("You get 25 days."),
        heading("Sickness", 3),
        paragraph("Phone before 08:00."),
        heading("Pay", 2),
        paragraph("Paid on the 25th."),
    ]
    chunked = chunk_document(blocks)
    assert [(c.heading_path, c.text) for c in chunked.chunks] == [
        ((), "Welcome to the handbook."),
        (("Leave", "Annual leave"), "You get 25 days."),
        (("Leave", "Sickness"), "Phone before 08:00."),
        (("Pay",), "Paid on the 25th."),
    ]
    assert [c.ordinal for c in chunked.chunks] == [0, 1, 2, 3]


def test_a_single_leading_h1_is_the_title_but_several_h1s_are_sections() -> None:
    single = chunk_document([heading("Guide", 1), heading("Part", 2), paragraph("Text.")])
    assert single.chunks[0].heading_path == ("Part",)
    several = chunk_document([heading("One", 1), paragraph("First."), heading("Two", 1), paragraph("Second.")])
    assert [c.heading_path for c in several.chunks] == [("One",), ("Two",)]


def test_chunks_are_exact_slices_of_the_document_text() -> None:
    blocks = [heading("Doc", 1), heading("A", 2), paragraph(sentences(30)), heading("B", 2), paragraph(sentences(12, "Other"))]
    chunked = chunk_document(blocks, ChunkingConfig(max_chars=400, overlap_chars=100, min_chars=80))
    assert len(chunked.chunks) > 4
    for chunk in chunked.chunks:
        assert chunked.text[chunk.start_char : chunk.end_char] == chunk.text
        assert chunk.text == chunk.text.strip()


def test_chunks_respect_the_size_limit_and_never_cut_a_sentence() -> None:
    text = sentences(40)
    config = ChunkingConfig(max_chars=500, overlap_chars=120, min_chars=100)
    chunked = chunk_document([paragraph(text)], config)
    known = {text[s:e] for s, e in split_sentences(text)}
    for chunk in chunked.chunks:
        assert len(chunk.text) <= config.max_chars * 1.25  # only a merged tail may exceed max_chars
        assert all(chunk.text[s:e] in known for s, e in split_sentences(chunk.text))
    assert max(len(c.text) for c in chunked.chunks[:-1]) <= config.max_chars


def test_consecutive_chunks_overlap_by_whole_sentences() -> None:
    config = ChunkingConfig(max_chars=500, overlap_chars=120, min_chars=100)
    chunked = chunk_document([paragraph(sentences(40))], config)
    assert chunked.chunks[0].overlap_chars == 0
    for previous, current in pairwise(chunked.chunks):
        assert 0 < current.overlap_chars <= config.overlap_chars * 1.5
        assert current.start_char < previous.end_char
        shared = chunked.text[current.start_char : previous.end_char]
        assert previous.text.endswith(shared) and current.text.startswith(shared)
        assert shared == current.text[: current.overlap_chars]
        # The overlap begins at a sentence boundary.
        assert shared.startswith("Sentence number")
        # ...and every chunk still contributes new text.
        assert current.end_char > previous.end_char


def test_no_content_is_lost_between_chunks() -> None:
    text = sentences(40)
    chunked = chunk_document([paragraph(text)], ChunkingConfig(max_chars=500, overlap_chars=120, min_chars=100))
    covered = set()
    for chunk in chunked.chunks:
        covered.update(range(chunk.start_char, chunk.end_char))
    assert all(index in covered for index, char in enumerate(chunked.text) if not char.isspace())


def test_overlap_never_crosses_a_heading() -> None:
    blocks = [heading("A", 2), paragraph(sentences(20)), heading("B", 2), paragraph(sentences(20, "Other"))]
    chunked = chunk_document(blocks, ChunkingConfig(max_chars=400, overlap_chars=100, min_chars=80))
    first_of_b = next(c for c in chunked.chunks if c.heading_path == ("B",))
    assert first_of_b.overlap_chars == 0
    assert first_of_b.text.startswith("Other number 1 ")
    assert all("Other" not in c.text for c in chunked.chunks if c.heading_path == ("A",))


def test_zero_overlap_produces_disjoint_chunks() -> None:
    chunked = chunk_document([paragraph(sentences(30))], ChunkingConfig(max_chars=400, overlap_chars=0, min_chars=50))
    assert all(c.overlap_chars == 0 for c in chunked.chunks)
    assert all(a.end_char <= b.start_char for a, b in pairwise(chunked.chunks))


def test_a_short_tail_is_merged_into_the_previous_chunk() -> None:
    body = sentences(7) + " Tail."
    chunked = chunk_document([paragraph(body)], ChunkingConfig(max_chars=len(sentences(7)), overlap_chars=0, min_chars=60))
    assert len(chunked.chunks) == 1
    assert chunked.chunks[0].text.endswith("Tail.")


def test_a_sentence_longer_than_the_limit_is_split_at_whitespace() -> None:
    long_sentence = " ".join(["word"] * 400) + "."
    chunked = chunk_document([paragraph(long_sentence)], ChunkingConfig(max_chars=300, overlap_chars=0, min_chars=0))
    assert len(chunked.chunks) > 5
    assert all(len(c.text) <= 300 for c in chunked.chunks)
    assert all(not c.text.startswith(" ") and not c.text.endswith(" ") for c in chunked.chunks)
    assert " ".join(c.text for c in chunked.chunks).replace(" ", "") == long_sentence.replace(" ", "")


def test_lists_and_tables_are_rendered_line_by_line() -> None:
    blocks = [
        heading("Limits", 2),
        paragraph("The limits are:"),
        Block("list_item", "Lunch is capped."),
        Block("list_item", "2. Second step"),
        Block("table_row", "Meal: Dinner; Limit: £25"),
        Block("table_row", "Meal: Lunch; Limit: £12"),
        paragraph("Alcohol is excluded."),
    ]
    chunked = chunk_document(blocks)
    assert chunked.chunks[0].text == (
        "The limits are:\n\n- Lunch is capped.\n2. Second step\n\n"
        "Meal: Dinner; Limit: £25\nMeal: Lunch; Limit: £12\n\nAlcohol is excluded."
    )


def test_page_range_follows_the_blocks_in_the_chunk() -> None:
    blocks = [heading("S", 2), paragraph("On page two.", page=2), paragraph("On page three.", page=3)]
    chunk = chunk_document(blocks).chunks[0]
    assert (chunk.page_start, chunk.page_end) == (2, 3)


def test_headings_without_body_produce_no_chunks() -> None:
    assert chunk_document([heading("Only", 1), heading("Headings", 2)]).chunks == []


def test_token_estimate_is_about_a_quarter_of_the_characters() -> None:
    chunk = chunk_document([paragraph("x" * 400 + ".")]).chunks[0]
    assert chunk.token_estimate == 100


@pytest.mark.parametrize("kwargs", [{"max_chars": 50}, {"max_chars": 500, "overlap_chars": 500}, {"overlap_chars": -1}])
def test_invalid_configuration_is_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ChunkingConfig(**kwargs)
