"""Markdown -> blocks.

A deliberately small block-level parser: chunking needs the document *structure* (headings,
paragraphs, list items, table rows, code), not rendered HTML, so a full CommonMark engine
would add a dependency without adding signal. Inline markup is stripped to plain text.
"""

from __future__ import annotations

import re

from ..blocks import Block, ParsedDocument, linearize_table_row

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_ATX_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_LIST_RE = re.compile(r"^[ \t]*(?:[-*+]|(\d{1,3})[.)])[ \t]+(.*)$")
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
_RULE_RE = re.compile(r"^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_SETEXT_RE = re.compile(r"^[ \t]*(=+|-+)[ \t]*$")
_TABLE_SEPARATOR_RE = re.compile(r"^[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
_TASK_RE = re.compile(r"^\[[ xX]\][ \t]+")

_INLINE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),  # images -> alt text
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),  # inline links -> label
    (re.compile(r"\[([^\]]+)\]\[[^\]]*\]"), r"\1"),  # reference links -> label
    (re.compile(r"`([^`]*)`"), r"\1"),  # code spans
    (re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1"), r"\2"),  # bold
    (re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])"), r"\1"),  # *italic*
    (re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)"), r"\1"),  # _italic_
    (re.compile(r"~~(.+?)~~"), r"\1"),  # strikethrough
    (re.compile(r"<br\s*/?>", re.IGNORECASE), " "),
    (re.compile(r"</?[a-zA-Z][^>]*>"), ""),  # stray inline HTML
    (re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])"), r"\1"),  # backslash escapes
)


def clean_inline(text: str) -> str:
    """Strip inline Markdown markup and collapse whitespace."""
    for pattern, replacement in _INLINE_RULES:
        text = pattern.sub(replacement, text)
    return " ".join(text.split())


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [clean_inline(cell.replace("\\|", "|")) for cell in re.split(r"(?<!\\)\|", line)]


def _read_front_matter(lines: list[str]) -> tuple[int, str | None]:
    """Return (index of the first content line, title from YAML front matter if any)."""
    if not lines or lines[0].strip() != "---":
        return 0, None
    for end in range(1, len(lines)):
        if lines[end].strip() in ("---", "..."):
            title = None
            for line in lines[1:end]:
                key, _, value = line.partition(":")
                if key.strip().lower() == "title" and value.strip():
                    title = value.strip().strip("\"'")
            return end + 1, title
    return 0, None


def parse_markdown(text: str) -> ParsedDocument:
    lines = _COMMENT_RE.sub("", text).splitlines()
    i, title = _read_front_matter(lines)
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            cleaned = clean_inline(" ".join(paragraph))
            if cleaned:
                blocks.append(Block("paragraph", cleaned))
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        fence = _FENCE_RE.match(line)
        if fence:
            flush_paragraph()
            marker = fence.group(1)
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith(marker):
                code.append(lines[i].rstrip())
                i += 1
            i += 1  # closing fence
            if any(part.strip() for part in code):
                blocks.append(Block("code", "\n".join(code).strip("\n")))
            continue

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        heading = _ATX_RE.match(line)
        if heading:
            flush_paragraph()
            cleaned = clean_inline(heading.group(2))
            if cleaned:
                blocks.append(Block("heading", cleaned, level=len(heading.group(1))))
            i += 1
            continue

        if paragraph and _SETEXT_RE.match(line):
            cleaned = clean_inline(" ".join(paragraph))
            paragraph.clear()
            if cleaned:
                blocks.append(Block("heading", cleaned, level=1 if stripped[0] == "=" else 2))
            i += 1
            continue

        if _RULE_RE.match(line):
            flush_paragraph()
            i += 1
            continue

        if "|" in line and i + 1 < len(lines) and "-" in lines[i + 1] and _TABLE_SEPARATOR_RE.match(lines[i + 1]):
            flush_paragraph()
            header = _split_row(line)
            i += 2
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                row = linearize_table_row(header, _split_row(lines[i]))
                if row:
                    blocks.append(Block("table_row", row))
                i += 1
            continue

        item = _LIST_RE.match(line)
        if item:
            flush_paragraph()
            number = item.group(1)
            parts = [item.group(2)]
            i += 1
            while (
                i < len(lines)
                and lines[i].strip()
                and lines[i][:1] in (" ", "\t")
                and not _LIST_RE.match(lines[i])
            ):
                parts.append(lines[i].strip())
                i += 1
            cleaned = clean_inline(_TASK_RE.sub("", " ".join(parts)))
            if cleaned:
                # Step numbers carry meaning ("step 3"), so ordered items keep theirs.
                blocks.append(Block("list_item", f"{number}. {cleaned}" if number else cleaned))
            continue

        if stripped.startswith(">"):
            stripped = stripped.lstrip(">").strip()
            if not stripped:
                flush_paragraph()
                i += 1
                continue

        paragraph.append(stripped)
        i += 1

    flush_paragraph()

    if title is None:
        title = next((b.text for b in blocks if b.kind == "heading" and b.level == 1), None)
    return ParsedDocument(blocks=blocks, title=title)
