"""Deciding when *not* to answer.

Before any engine runs, the retrieval result is checked: how much of the question is
actually present in the best passage? Two numbers are computed from the question's terms,
each weighted by how informative it is in this corpus (inverse document frequency):

    coverage = weight of the question terms found in the passage
               / weight of all question terms                      (0..1)

    evidence = weight of the question terms found in the passage
               / weight of one term that occurs in a single chunk  (roughly "how many rare
                                                                    terms' worth matched")

Coverage asks whether the passage is about the *whole* question; evidence asks whether
enough was matched in absolute terms, so that one shared everyday word ("staff", "clinic")
is never treated as a match. The assistant answers only when both clear their thresholds and
otherwise abstains.

Words that appear nowhere in the knowledge base are a special case: they may be the very
thing an unanswerable question is about ("is there a *gym* discount?"), or just a
paraphrase of something that is covered ("what is the *dinner* allowance?" when the policy
says "evening meal"). Lexically the two cannot be told apart, so such terms count against
coverage at a reduced weight rather than in full or not at all.

All of this is lexical. It cannot know that "holiday" and "annual leave" mean the same
thing, and the evaluation in the README reports the resulting wrong decisions in both
directions.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..retrieval.base import TermStatistics
from ..text.analyzer import analyze, query_terms
from .types import Passage

# Weight of a question term that occurs nowhere in the corpus, relative to its nominal IDF.
UNSEEN_TERM_WEIGHT = 0.25


@dataclass(frozen=True)
class RetrievalConfidence:
    coverage: float
    evidence: float
    matched_terms: tuple[str, ...]
    missing_terms: tuple[str, ...]
    sufficient: bool


def informativeness(document_frequency: int, chunk_count: int) -> float:
    """Smoothed inverse document frequency; always positive."""
    return math.log(1 + (chunk_count - document_frequency + 0.5) / (document_frequency + 0.5))


def term_weights(terms: Sequence[str], stats: TermStatistics) -> dict[str, float]:
    """Weight of each question term: its IDF, discounted if the corpus does not contain it at all."""
    count = max(stats.chunk_count(), 1)
    frequencies = stats.document_frequencies(terms)
    weights: dict[str, float] = {}
    for term in terms:
        frequency = frequencies.get(term, 0)
        weight = informativeness(frequency, count)
        weights[term] = weight if frequency else weight * UNSEEN_TERM_WEIGHT
    return weights


def passage_terms(passage: Passage) -> set[str]:
    """Everything a passage can 'say' lexically: its text, its section headings and its document title."""
    return set(analyze(passage.text)) | set(analyze(" ".join(passage.heading_path))) | set(analyze(passage.document_title))


def assess_retrieval(
    query: str,
    passages: Sequence[Passage],
    stats: TermStatistics,
    *,
    min_coverage: float,
    min_evidence: float,
    consider: int = 3,
) -> RetrievalConfidence:
    """Measure how well the best of the top ``consider`` passages matches the query's terms."""
    terms = query_terms(query)
    if not terms or not passages:
        return RetrievalConfidence(0.0, 0.0, (), tuple(terms), False)

    weights = term_weights(terms, stats)
    total = sum(weights.values()) or 1.0
    rare_term = informativeness(1, max(stats.chunk_count(), 1))

    best: tuple[float, float, tuple[str, ...]] = (-1.0, 0.0, ())
    for passage in passages[:consider]:
        present = passage_terms(passage)
        matched = tuple(term for term in terms if term in present)
        mass = sum(weights[term] for term in matched)
        candidate = (mass / total, mass / rare_term, matched)
        if candidate[:2] > best[:2]:
            best = candidate
    coverage, evidence, matched = best
    return RetrievalConfidence(
        coverage=round(coverage, 4),
        evidence=round(evidence, 4),
        matched_terms=matched,
        missing_terms=tuple(term for term in terms if term not in matched),
        sufficient=coverage >= min_coverage and evidence >= min_evidence,
    )
