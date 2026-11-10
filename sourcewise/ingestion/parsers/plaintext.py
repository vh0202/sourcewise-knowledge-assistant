"""Plain text -> blocks.

Plain text has no markup, so structure is inferred from layout conventions that are common
in policies and procedures: a title line at the top, numbered section headings
("3. Approval limits", "3.2 Hotels"), ALL-CAPS headings, underlined headings, and
bulleted or numbered list lines.
"""

from __future__ import annotations

import re

from ..blocks import Block, ParsedDocument

_NUMBERED_HEADING_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})[.)]?[ \t]+(\S.{1,90})$")
_BULLET_RE = re.compile(r"^[ \t]*(?:[-*•–—]|\(?([a-z]|\d{1,2})[.)])[ \t]+(.*)$")
_UNDERLINE_RE = re.compile(r"^(={3,}|-{3,}|~{3,})$")
_SENTENCE_END = (".", "!", "?", ";", ",", ":")
MAX_HEADING_LENGTH = 90


def numbered_heading(line: str) -> tuple[int, str] | None:
    """Return (depth, text) if ``line`` looks like "2.1 Booking flights"; depth counts the numbers."""
    match = _NUMBERED_HEADING_RE.match(line.strip())
    if not match:
        return None
    rest = match.group(2).strip()
    if rest.endswith(_SENTENCE_END) or not (rest[0].isupper() or rest[0].isdigit()):
        return None
    if len(rest.split()) > 12:
        return None
    return match.group(1).count(".") + 1, line.strip()


def _is_all_caps_heading(line: str) -> bool:
    letters = [ch for ch in line if ch.isalpha()]
    return (
        len(letters) >= 4
        and all(ch.isupper() for ch in letters)
        and len(line) <= MAX_HEADING_LENGTH
        and not line.endswith(_SENTENCE_END)
    )


def parse_plaintext(text: str) -> ParsedDocument:
    lines = [line.rstrip() for line in text.splitlines()]
    blocks: list[Block] = []
    paragraph: list[str] = []
    title: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(Block("paragraph", " ".join(" ".join(paragraph).split())))
            paragraph.clear()

    def is_blank(index: int) -> bool:
        return index < 0 or index >= len(lines) or not lines[index].strip()

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            flush_paragraph()
            i += 1
            continue

        standalone = not paragraph and is_blank(i - 1)
        next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""

        # "Title" followed by a row of ===, --- or ~~~
        if standalone and _UNDERLINE_RE.match(next_line) and len(stripped) <= MAX_HEADING_LENGTH:
            level = 1 if next_line[0] == "=" else 2
            blocks.append(Block("heading", stripped, level=level))
            if title is None and level == 1:
                title = stripped
            i += 2
            continue

        if standalone and is_blank(i + 1):
            # The first line of the file, standing alone, is the document title.
            if not blocks and len(stripped) <= MAX_HEADING_LENGTH and not stripped.endswith(_SENTENCE_END):
                blocks.append(Block("heading", stripped, level=1))
                title = stripped
                i += 1
                continue
            numbered = numbered_heading(stripped)
            if numbered:
                depth, heading_text = numbered
                blocks.append(Block("heading", heading_text, level=min(depth + 1, 6)))
                i += 1
                continue
            if _is_all_caps_heading(stripped):
                blocks.append(Block("heading", stripped, level=2))
                i += 1
                continue

        bullet = _BULLET_RE.match(lines[i])
        if bullet and bullet.group(2).strip():
            flush_paragraph()
            enumerator = bullet.group(1)
            parts = [bullet.group(2).strip()]
            i += 1
            while (
                i < len(lines)
                and lines[i].strip()
                and lines[i][:1] in (" ", "\t")
                and not _BULLET_RE.match(lines[i])
            ):
                parts.append(lines[i].strip())
                i += 1
            item = " ".join(" ".join(parts).split())
            # Ordered items keep their number or letter; plain bullets do not.
            blocks.append(Block("list_item", f"{enumerator}. {item}" if enumerator else item))
            continue

        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    return ParsedDocument(blocks=blocks, title=title)
