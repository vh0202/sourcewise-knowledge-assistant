"""The offline answer engine: deterministic, extractive, no network.

It does not generate language. It finds the sentence in the retrieved passages that best
matches the question and returns it verbatim together with the neighbouring sentences that
make it readable, followed by a citation marker. Every word of an offline answer is therefore
traceable to a source by construction, and the whole product (and its tests and evaluation)
runs without an API key.

Sentence scoring, for question terms weighted by informativeness (IDF):

* terms found in the sentence itself count in full;
* terms found only in the sentence's context - its section headings, its document title, or
  the FAQ-style question it directly follows - count half;
* sentences from better-ranked passages get a small boost, as do sentences whose question
  terms sit close together and sentences containing the kind of answer the question asks
  for (a figure for "how many" / "what is the limit", a frequency for "how often").

What is quoted around the best sentence:

* if it sits in a short paragraph, list or table, that whole block;
* otherwise the sentence before it, if the best one opens with a pronoun ("It needs
  approval ...") or the previous one is nearly as relevant; the sentence after it, if that is
  relevant too; and the list or table that follows, if the best sentence ends with a colon.

One further sentence from elsewhere is added when it covers a substantial part of the
question that the first quotation does not. If even the best sentence is supported by too
little of the question, the engine abstains.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass

from ..retrieval.base import TermStatistics
from ..text.analyzer import analyze, query_terms
from ..text.sentences import split_sentences
from .confidence import term_weights
from .types import (
    AnswerEvent,
    AnswerRequest,
    AnswerResult,
    CitationAdded,
    CitationLedger,
    Completed,
    Passage,
    TextDelta,
    abstain,
)

# Expected answer types: (pattern that recognises the kind of question, pattern that
# recognises a sentence containing that kind of answer). The first matching row applies.
_ANSWER_TYPES: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...] = (
    (  # frequency: "how often ...?" -> "every Tuesday", "twice a year"
        re.compile(r"\bhow\s+(often|frequently|regularly)\b", re.IGNORECASE),
        re.compile(
            r"\b(every|each|daily|weekly|fortnightly|monthly|quarterly|annually|yearly|once|twice|times)\b",
            re.IGNORECASE,
        ),
    ),
    (  # a figure: "how many ...?", "what is the limit ...?", "when ...?"
        re.compile(
            r"\b(how\s+(many|much|long|soon|far|late|early|old)|when|what\s+time|deadline|limit|maximum|"
            r"minimum|fee|price|cost|rate|amount|allowance|percentage|percent|hours?|days?|weeks?|months?|"
            r"years?|date|period|number|age)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|half|twice)\b",
            re.IGNORECASE,
        ),
    ),
)
_ENUMERATOR_RE = re.compile(r"^\(?(\d{1,2}|[a-z])[.)]\s+")
_REFERS_BACK_RE = re.compile(r"^(it|this|that|these|those|they|such|he|she)\b", re.IGNORECASE)
_PIECE_RE = re.compile(r"\S+|\s+")

MAX_LIST_LINES = 6


def _smallest_window(tokens: list[str], required: set[str]) -> int:
    """Length of the shortest run of ``tokens`` that contains every term in ``required``."""
    counts: dict[str, int] = {}
    best = len(tokens)
    left = 0
    for right, token in enumerate(tokens):
        if token in required:
            counts[token] = counts.get(token, 0) + 1
        while len(counts) == len(required):
            best = min(best, right - left + 1)
            leaving = tokens[left]
            if leaving in counts:
                counts[leaving] -= 1
                if not counts[leaving]:
                    del counts[leaving]
            left += 1
    return max(best, 1)


@dataclass(frozen=True)
class _Sentence:
    passage: Passage
    passage_rank: int
    index: int
    start: int
    end: int
    # How the sentence is attached to the one before it: "inline" (same paragraph),
    # "line" (next item of the same list or table) or "block" (new paragraph / first sentence).
    joint: str
    own_terms: frozenset[str]
    score: float
    support: float

    @property
    def text(self) -> str:
        return self.passage.text[self.start : self.end]


class ExtractiveEngine:
    name = "offline"
    label = "Extractive (offline) mode"
    model: str | None = None

    def __init__(
        self,
        stats: TermStatistics,
        *,
        min_support: float = 0.2,
        max_groups: int = 2,
        passage_prior: float = 0.25,
        whole_block_chars: int = 350,
        stream_delay: float = 0.0,
    ) -> None:
        """
        min_support          abstain if the best sentence and its context cover less than this
                             share of the question (IDF-weighted)
        max_groups           how many separate quotations an answer may contain
        passage_prior        how much a sentence's score depends on its passage's retrieval rank
        whole_block_chars    paragraphs, lists and tables up to this length are quoted whole
        stream_delay         seconds to wait between words when streaming (purely cosmetic)

        The defaults were chosen on eval/dev_set.json.
        """
        self._stats = stats
        self._min_support = min_support
        self._max_groups = max_groups
        self._passage_prior = passage_prior
        self._whole_block_chars = whole_block_chars
        self._stream_delay = stream_delay

    # -- scoring ---------------------------------------------------------------------------
    def _sentences(self, request: AnswerRequest) -> tuple[list[list[_Sentence]], dict[str, float]]:
        """Every sentence of every passage, scored against the question, plus the term weights used."""
        terms = query_terms(request.effective_query)
        if not terms or not request.passages:
            return [], {}
        weights = term_weights(terms, self._stats)
        if request.search_query and request.search_query != request.question:
            # A follow-up searched together with the previous question: what the follow-up
            # itself asks about matters twice as much as the context it inherited.
            for term in query_terms(request.question):
                if term in weights:
                    weights[term] *= 2
        total = sum(weights.values()) or 1.0
        expected_answer = next(
            (answer for asks, answer in _ANSWER_TYPES if asks.search(request.question)), None
        )
        top_score = max(passage.score for passage in request.passages) or 1.0

        result: list[list[_Sentence]] = []
        for rank, passage in enumerate(request.passages):
            context = set(analyze(" ".join(passage.heading_path))) | set(analyze(passage.document_title))
            asked: set[str] = set()  # terms of an FAQ-style question that the next sentence answers
            sentences: list[_Sentence] = []
            previous_end = 0
            for index, (start, end) in enumerate(split_sentences(passage.text)):
                gap = passage.text[previous_end:start]
                joint = "block" if index == 0 or "\n\n" in gap else "line" if "\n" in gap else "inline"
                previous_end = end
                text = passage.text[start:end]
                ordered_terms = analyze(text)
                sentence_terms = set(ordered_terms)

                matched: list[str] = []
                score = support = 0.0
                if text.endswith("?"):
                    asked = sentence_terms  # a question is never an answer, but it frames the next sentence
                else:
                    inherited, asked = asked, set()
                    own = [term for term in terms if term in sentence_terms]
                    # Terms the sentence does not contain itself but is plainly about: those of the
                    # FAQ question it answers, and - more loosely - those of its headings and title.
                    answered = [term for term in terms if term not in sentence_terms and term in inherited]
                    framed = [
                        term
                        for term in terms
                        if term not in sentence_terms and term not in inherited and term in context
                    ]
                    matched = own + answered
                    # A sentence can qualify on its headings alone: under "Core hours", "Be available
                    # between 10:00 and 15:00." is the answer even though it repeats neither word.
                    if matched or framed:
                        own_weight = sum(weights[term] for term in own)
                        answered_weight = sum(weights[term] for term in answered)
                        framed_weight = sum(weights[term] for term in framed)
                        support = (own_weight + answered_weight + framed_weight) / total
                        score = (own_weight + 0.9 * answered_weight + 0.5 * framed_weight) / total
                        score *= (1 - self._passage_prior) + self._passage_prior * (passage.score / top_score)
                        if len(own) > 1:
                            # Question terms that sit close together ("cash is banked") say more
                            # than the same terms scattered across a long sentence.
                            score *= 1 + 0.15 * len(own) / _smallest_window(ordered_terms, set(own))
                        if expected_answer and expected_answer.search(_ENUMERATOR_RE.sub("", text)):
                            score *= 1.15  # the sentence contains the kind of answer the question asks for
                        elif len(sentence_terms) < 3:
                            score *= 0.6  # fragments such as "See the next section." rarely answer anything
                sentences.append(
                    _Sentence(passage, rank, index, start, end, joint, frozenset(matched), score, support)
                )
            result.append(sentences)
        return result, weights

    def _with_neighbours(self, best: _Sentence, siblings: list[_Sentence]) -> list[_Sentence]:
        """The best sentence together with the sentences around it that belong in the quotation."""
        after = siblings[best.index + 1 :]
        if best.text.endswith(":"):
            # A lead-in such as "The limits are:" - quote the list or table it introduces.
            group = [best]
            for position, sentence in enumerate(after[:MAX_LIST_LINES]):
                if position and sentence.joint != "line":
                    break
                group.append(sentence)
            return group

        # The block - paragraph, list or table - that the best sentence belongs to.
        start = best.index
        while siblings[start].joint != "block":
            start -= 1
        stop = best.index
        while stop + 1 < len(siblings) and siblings[stop + 1].joint != "block":
            stop += 1
        if siblings[stop].end - siblings[start].start <= self._whole_block_chars:
            # A short block is one unit of meaning: quote all of it rather than one sentence,
            # together with the sentence that introduces it, if there is one.
            block = [sentence for sentence in siblings[start : stop + 1] if not sentence.text.endswith("?")]
            if start > 0 and siblings[start - 1].text.endswith(":"):
                block.insert(0, siblings[start - 1])
            return block

        if best.joint == "line" or (after and after[0].joint == "line"):
            # A row of a list or table: keep the neighbouring rows that match about as well,
            # and the sentence that introduces them.
            first = last = best.index
            good_enough = 0.75 * best.score
            while (
                siblings[first].joint == "line"
                and siblings[first - 1].score >= good_enough
                and last - first + 1 < MAX_LIST_LINES
            ):
                first -= 1
            while (
                last + 1 < len(siblings)
                and siblings[last + 1].joint == "line"
                and siblings[last + 1].score >= good_enough
                and last - first + 1 < MAX_LIST_LINES
            ):
                last += 1
            group = siblings[first : last + 1]
            if first > 0 and siblings[first].joint != "line" and siblings[first - 1].text.endswith(":"):
                group = [siblings[first - 1], *group]
            return group

        group = [best]
        if best.index > 0 and best.joint == "inline":
            before = siblings[best.index - 1]
            if not before.text.endswith("?") and (
                _REFERS_BACK_RE.match(best.text) or before.score >= 0.5 * best.score
            ):
                group.insert(0, before)
        if after and after[0].joint == "inline" and after[0].score >= 0.4 * best.score:
            group.append(after[0])
        return group

    def _select(self, passages: list[list[_Sentence]], weights: dict[str, float]) -> list[list[_Sentence]]:
        """Choose the sentences to quote, as groups of consecutive sentences."""
        ranked = sorted(
            (sentence for sentences in passages for sentence in sentences if sentence.score > 0),
            key=lambda s: (-s.score, s.passage_rank, s.index),
        )
        if not ranked or ranked[0].support < self._min_support:
            return []
        best = ranked[0]
        group = self._with_neighbours(best, passages[best.passage_rank])

        # A sentence from elsewhere earns a place only if it is nearly as good as the best one
        # and brings a substantial part of the question that the first group does not cover.
        groups = [group]
        total = sum(weights.values()) or 1.0
        covered = set().union(*(sentence.own_terms for sentence in group))
        quoted = {" ".join(sentence.text.lower().split()) for sentence in group}
        for candidate in ranked[1:]:
            if len(groups) >= self._max_groups:
                break
            key = " ".join(candidate.text.lower().split())
            if key in quoted:  # already quoted, possibly via an overlapping chunk
                continue
            added = sum(weights[term] for term in candidate.own_terms - covered) / total
            if candidate.score >= 0.75 * best.score and added >= 0.2:
                groups.append([candidate])
                covered |= candidate.own_terms
                quoted.add(key)
        groups.sort(key=lambda g: (g[0].passage_rank, g[0].index))
        return groups

    # -- answering -------------------------------------------------------------------------
    @staticmethod
    def _quote(group: list[_Sentence]) -> tuple[str, int, int]:
        """The text to show for a group, and the span of the passage it cites."""
        first = group[0]
        start = first.start + (2 if first.text.startswith("- ") else 0)
        parts: list[str] = []
        for position, sentence in enumerate(group):
            text = sentence.text[2:] if sentence.text.startswith("- ") else sentence.text
            if position:
                parts.append(" " if sentence.joint == "inline" else "\n")
            parts.append(text)
        return "".join(parts), start, group[-1].end

    def answer(self, request: AnswerRequest) -> Iterator[AnswerEvent]:
        groups = self._select(*self._sentences(request))
        if not groups:
            yield Completed(abstain("unsupported"))
            return

        ledger = CitationLedger()
        emitted: list[str] = []

        def emit(text: str) -> Iterator[TextDelta]:
            for piece in _PIECE_RE.findall(text):
                emitted.append(piece)
                yield TextDelta(piece)
                if self._stream_delay and not piece.isspace():
                    time.sleep(self._stream_delay)

        for position, group in enumerate(groups):
            text, start, end = self._quote(group)
            citation, is_new = ledger.cite(group[0].passage, start, end)
            if position:
                yield from emit("\n\n")
            yield from emit(text)
            if is_new:
                yield CitationAdded(citation)
            yield from emit(f" [{citation.number}]")

        yield Completed(AnswerResult(text="".join(emitted), citations=ledger.citations))
