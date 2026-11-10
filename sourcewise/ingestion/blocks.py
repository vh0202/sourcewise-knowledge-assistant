"""The format-neutral document model produced by every parser and consumed by the chunker."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["heading", "paragraph", "list_item", "table_row", "code"]


@dataclass
class Block:
    """One structural unit of a document.

    ``level`` is the heading depth (1-6) for headings and 0 otherwise.
    ``page`` is the 1-based page a block starts on; only PDF parsing sets it.
    """

    kind: BlockKind
    text: str
    level: int = 0
    page: int | None = None


@dataclass
class ParsedDocument:
    blocks: list[Block]
    title: str | None = None
    page_count: int | None = None
    notes: list[str] = field(default_factory=list)


def linearize_table_row(header: list[str], cells: list[str]) -> str:
    """Render a table row as ``Header: value; Header: value``.

    Chunking a table cell-by-cell loses the column meaning, and keeping the raw grid wastes
    the ranker's term statistics on punctuation. Pairing every value with its column header
    keeps each row self-describing for both BM25 and an LLM.
    """
    parts: list[str] = []
    for index, cell in enumerate(cells):
        cell = cell.strip()
        if not cell:
            continue
        label = header[index].strip() if index < len(header) else ""
        parts.append(f"{label}: {cell}" if label else cell)
    return "; ".join(parts)
