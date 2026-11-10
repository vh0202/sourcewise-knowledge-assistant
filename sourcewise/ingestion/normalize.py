"""Normalisation between parsing and chunking.

Makes text from different sources look the same to the index: Unicode compatibility forms
are folded (ligatures such as "ﬁ" become "fi"), invisible and control characters are removed,
whitespace is collapsed, and empty or immediately repeated blocks are dropped.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .blocks import Block

# Control characters (except tab/newline), zero-width characters, BOM and the soft hyphen.
_INVISIBLE_RE = re.compile(
    "[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f­​-‏  ⁠﻿]"
)
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([,;:.!?])(?=\s|$)")


@dataclass(frozen=True)
class NormalizationStats:
    blocks_in: int
    blocks_out: int
    dropped_empty: int
    dropped_duplicates: int
    characters: int


def normalize_text(text: str, *, preserve_lines: bool = False) -> str:
    """Return ``text`` in canonical form. ``preserve_lines`` keeps line structure (for code)."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE_RE.sub("", text)
    if preserve_lines:
        lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        return "\n".join(lines).strip("\n")
    text = " ".join(text.split())
    return _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", text)


def normalize_blocks(blocks: list[Block]) -> tuple[list[Block], NormalizationStats]:
    result: list[Block] = []
    dropped_empty = dropped_duplicates = 0
    for block in blocks:
        text = normalize_text(block.text, preserve_lines=block.kind == "code")
        if not text:
            dropped_empty += 1
            continue
        previous = result[-1] if result else None
        if previous is not None and previous.kind == block.kind and previous.text == text:
            dropped_duplicates += 1
            continue
        level = min(max(block.level, 1), 6) if block.kind == "heading" else 0
        result.append(Block(block.kind, text, level=level, page=block.page))
    stats = NormalizationStats(
        blocks_in=len(blocks),
        blocks_out=len(result),
        dropped_empty=dropped_empty,
        dropped_duplicates=dropped_duplicates,
        characters=sum(len(block.text) for block in result),
    )
    return result, stats
