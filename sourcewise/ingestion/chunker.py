"""Heading-aware chunking with sentence-aligned overlap.

Rules, in order of priority:

1. A chunk never crosses a heading. Every chunk therefore belongs to exactly one section and
   carries that section's heading path ("Leave > Annual leave"), which is indexed alongside
   the text and shown in citations.
2. Inside a section, whole sentences (or whole list items / table rows) are packed greedily
   up to ``max_chars``. Sentences are never cut unless a single one exceeds the limit.
3. Consecutive chunks of a section overlap: the next chunk starts with the last sentences of
   the previous one, up to ``overlap_chars``, so a fact that straddles a boundary is fully
   present in at least one chunk.
4. A short tail is merged into the previous chunk instead of becoming a fragment.

Chunks are exact slices of the document's normalised text (``text[start_char:end_char]``),
which makes overlap measurable and lets the chunk inspector show precisely how a document
was split.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..text.sentences import split_sentences
from .blocks import Block

_ENUMERATED_RE = re.compile(r"^(\d{1,3}|[a-z])\. ")


@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int = 700
    overlap_chars: int = 150
    min_chars: int = 150

    def __post_init__(self) -> None:
        if self.max_chars < 100:
            raise ValueError("max_chars must be at least 100")
        if not 0 <= self.overlap_chars < self.max_chars:
            raise ValueError("overlap_chars must be between 0 and max_chars")


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    text: str
    heading_path: tuple[str, ...]
    start_char: int
    end_char: int
    overlap_chars: int
    page_start: int | None
    page_end: int | None

    @property
    def token_estimate(self) -> int:
        """Rough token count (about four characters per token for English prose)."""
        return max(1, round(len(self.text) / 4))


@dataclass
class ChunkedDocument:
    text: str
    chunks: list[ChunkDraft] = field(default_factory=list)


@dataclass(frozen=True)
class _Unit:
    """An indivisible span of the normalised text: a sentence, a list item or a table row."""

    start: int
    end: int
    page: int | None


def _title_heading_index(blocks: list[Block]) -> int | None:
    """Index of the heading that is the document's own title, if there is exactly one H1 and it comes first."""
    heading_indexes = [i for i, block in enumerate(blocks) if block.kind == "heading"]
    top_level = [i for i in heading_indexes if blocks[i].level == 1]
    if len(top_level) == 1 and heading_indexes and heading_indexes[0] == top_level[0]:
        return top_level[0]
    return None


def _split_oversized(unit: _Unit, text: str, limit: int) -> list[_Unit]:
    """Cut a unit longer than ``limit`` at whitespace so that packing can always make progress."""
    if unit.end - unit.start <= limit:
        return [unit]
    pieces: list[_Unit] = []
    start = unit.start
    while unit.end - start > limit:
        cut = text.rfind(" ", start + limit // 2, start + limit)
        if cut == -1:
            cut = start + limit
        pieces.append(_Unit(start, cut, unit.page))
        start = cut + 1 if text[cut : cut + 1] == " " else cut
    if start < unit.end:
        pieces.append(_Unit(start, unit.end, unit.page))
    return pieces


def _pack(units: list[_Unit], config: ChunkingConfig) -> list[tuple[int, int]]:
    """Group units into chunks; returns half-open index ranges that may overlap."""
    ranges: list[tuple[int, int]] = []
    n = len(units)
    i = 0
    while i < n:
        j = i + 1
        while j < n and units[j].end - units[i].start <= config.max_chars:
            j += 1
        ranges.append((i, j))
        if j >= n:
            break
        # Start the next chunk with the trailing sentences of this one (the overlap).
        k = j
        while k - 1 > i:
            budget = config.overlap_chars if k < j else int(config.overlap_chars * 1.5)
            if units[j - 1].end - units[k - 1].start > budget:
                break
            k -= 1
        # The overlap must leave room for at least one new unit, or the next chunk would
        # merely repeat the end of this one.
        while k < j and units[j].end - units[k].start > config.max_chars:
            k += 1
        i = k

    if len(ranges) >= 2:
        (prev_start, prev_end), (_, tail_end) = ranges[-2], ranges[-1]
        new_content = units[tail_end - 1].end - units[prev_end].start
        merged_size = units[tail_end - 1].end - units[prev_start].start
        if new_content < config.min_chars and merged_size <= int(config.max_chars * 1.25):
            ranges[-2:] = [(prev_start, tail_end)]
    return ranges


def chunk_document(blocks: list[Block], config: ChunkingConfig | None = None) -> ChunkedDocument:
    """Split normalised blocks into overlapping, heading-scoped chunks."""
    config = config or ChunkingConfig()
    title_index = _title_heading_index(blocks)

    parts: list[str] = []
    position = 0
    sections: list[tuple[tuple[str, ...], list[_Unit]]] = []
    stack: list[tuple[int, str]] = []
    current_units: list[_Unit] = []
    current_path: tuple[str, ...] = ()
    previous_kind: str | None = None

    def close_section() -> None:
        nonlocal current_units
        if current_units:
            sections.append((current_path, current_units))
        current_units = []

    for index, block in enumerate(blocks):
        if previous_kind is not None:
            same_run = block.kind == previous_kind and block.kind in ("list_item", "table_row")
            separator = "\n" if same_run else "\n\n"
            parts.append(separator)
            position += len(separator)

        # Bullet items are rendered with a dash; ordered items already begin with "3. " or "b. ".
        is_bullet = block.kind == "list_item" and not _ENUMERATED_RE.match(block.text)
        rendered = f"- {block.text}" if is_bullet else block.text
        start = position
        parts.append(rendered)
        position += len(rendered)
        previous_kind = block.kind

        if block.kind == "heading":
            close_section()
            if index != title_index:
                while stack and stack[-1][0] >= block.level:
                    stack.pop()
                stack.append((block.level, block.text))
            current_path = tuple(text for _, text in stack)
        elif block.kind == "paragraph":
            for s, e in split_sentences(rendered):
                current_units.append(_Unit(start + s, start + e, block.page))
        else:
            current_units.append(_Unit(start, position, block.page))
    close_section()

    text = "".join(parts)
    chunks: list[ChunkDraft] = []
    for path, raw_units in sections:
        units = [piece for unit in raw_units for piece in _split_oversized(unit, text, config.max_chars)]
        previous_end: int | None = None
        for first, last in _pack(units, config):
            start_char, end_char = units[first].start, units[last - 1].end
            overlap = max(0, previous_end - start_char) if previous_end is not None else 0
            chunks.append(
                ChunkDraft(
                    ordinal=len(chunks),
                    text=text[start_char:end_char],
                    heading_path=path,
                    start_char=start_char,
                    end_char=end_char,
                    overlap_chars=overlap,
                    page_start=units[first].page,
                    page_end=units[last - 1].page,
                )
            )
            previous_end = end_char
    return ChunkedDocument(text=text, chunks=chunks)
