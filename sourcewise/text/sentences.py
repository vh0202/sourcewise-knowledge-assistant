"""Rule-based sentence segmentation that returns character spans.

Spans (rather than strings) are what the rest of the system needs: the chunker packs
sentences without losing their offsets, and the extractive engine cites the exact
``[start, end)`` range of the sentence it quotes.
"""

from __future__ import annotations

import re

# Sentence-final punctuation, optional closing quotes/brackets, whitespace, then something
# that plausibly starts a new sentence.
_BOUNDARY_RE = re.compile(
    r"""[.!?]+["'”’)\]]*(\s+)(?=["'“‘(\[]?[A-Z0-9])"""
)
_ABBREVIATIONS = frozenset(
    {
        "e.g", "i.e", "etc", "mr", "mrs", "ms", "dr", "prof", "st", "vs", "approx",
        "incl", "excl", "fig", "tel", "ext", "dept", "a.m", "p.m", "inc", "ltd", "co",
    }
)
# "No. 12" is an abbreviation; "No. Personal computers cannot ..." is a one-word sentence.
_NUMBER_ABBREVIATIONS = frozenset({"no", "nos"})
_LIST_MARKER_RE = re.compile(r"\(?(\d{1,3}|[A-Za-z])\)?")


def _is_false_boundary(line: str, punct_index: int, next_char: str) -> bool:
    """True when the period at ``punct_index`` does not end a sentence."""
    if line[punct_index] != ".":
        return False
    before = line[:punct_index]
    words = before.split()
    if not words:
        return True
    word = words[-1].lstrip("\"'“‘([")
    abbreviation = word.lower().rstrip(".")
    if abbreviation in _ABBREVIATIONS:
        return True
    if abbreviation in _NUMBER_ABBREVIATIONS and next_char.isdigit():
        return True
    if len(word) == 1 and word.isalpha() and word.isupper():
        return True  # an initial, as in "J. Okafor"
    # "1. Lock the cash drawer" - a list marker at the start of a line is not a sentence.
    return len(words) == 1 and _LIST_MARKER_RE.fullmatch(word) is not None


def _split_line(line: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _BOUNDARY_RE.finditer(line):
        if _is_false_boundary(line, match.start(), line[match.end(1) : match.end(1) + 1]):
            continue
        spans.append((start, match.start(1)))
        start = match.end(1)
    spans.append((start, len(line)))
    return spans


def split_sentences(text: str) -> list[tuple[int, int]]:
    """Return ``(start, end)`` spans of the sentences in ``text``.

    Line breaks are always boundaries (list items and table rows live on their own lines).
    Spans exclude surrounding whitespace and never overlap; empty lines produce no span.
    """
    spans: list[tuple[int, int]] = []
    offset = 0
    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if stripped:
            lead = len(raw_line) - len(raw_line.lstrip())
            for start, end in _split_line(stripped):
                segment = stripped[start:end]
                trimmed = segment.strip()
                if not trimmed:
                    continue
                inner_lead = len(segment) - len(segment.lstrip())
                absolute = offset + lead + start + inner_lead
                spans.append((absolute, absolute + len(trimmed)))
        offset += len(raw_line) + 1
    return spans
