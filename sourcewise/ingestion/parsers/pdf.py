"""PDF -> blocks with page numbers, using pypdf.

PDF has no logical structure, so it is reconstructed from layout:

* text fragments are grouped into lines using the positions pypdf reports;
* running headers/footers (lines repeated in the page margins of most pages) are dropped;
* a line set in a larger font than the body text - or a short all-bold line - is a heading,
  and distinct heading sizes map to heading levels;
* consecutive lines at the normal line spacing form one paragraph; a wider gap starts a new one;
* bullet glyphs mark list items, and fragments sharing a baseline are joined as table cells.

Every block records the 1-based page it starts on, which is what lets a citation say "p. 3".
Scanned PDFs without a text layer yield no blocks; the pipeline reports that as an error.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from ..blocks import Block, ParsedDocument
from .plaintext import numbered_heading

_BULLETS = frozenset("•◦▪●‣⁃·\x7f*-–")
_LIST_MARKER_RE = re.compile(r"^\(?(\d{1,2}|[a-zA-Z])[.)]?$")
_MARGIN_BAND = 0.12  # top/bottom share of the page in which running headers and footers live
_TERMINAL = (".", "!", "?", ":", ";")


class PdfParseError(ValueError):
    """Raised when a PDF cannot be read at all (corrupt or password-protected)."""


@dataclass
class _Line:
    text: str
    page: int
    x: float
    y: float
    size: float
    bold: bool
    in_margin: bool
    list_start: bool = False


def _page_lines(page, page_number: int) -> list[_Line]:
    fragments: list[tuple[str, float, float, float, bool]] = []

    def visitor(text, cm, tm, font_dict, font_size) -> None:
        if not text:
            return
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        scale = abs(tm[3] * cm[3]) or 1.0
        font_name = str(font_dict.get("/BaseFont", "")).lower() if font_dict else ""
        bold = any(marker in font_name for marker in ("bold", "black", "heavy", "semibold"))
        fragments.append((text, float(x), float(y), float(font_size or 0) * scale, bold))

    page.extract_text(visitor_text=visitor)

    height = float(page.mediabox.height) or 1.0
    bottom = float(page.mediabox.bottom)
    lines: list[_Line] = []
    pieces: list[tuple[str, float, float, float, bool]] = []

    def flush() -> None:
        if not pieces:
            return
        text = " ".join("".join(p[0] for p in pieces).split())
        if text:
            visible = [p for p in pieces if p[0].strip()]
            sizes: Counter[float] = Counter()
            for piece in visible:
                sizes[round(piece[3], 1)] += len(piece[0].strip())
            relative = (visible[0][2] - bottom) / height
            lines.append(
                _Line(
                    text=text,
                    page=page_number,
                    x=visible[0][1],
                    y=visible[0][2],
                    size=sizes.most_common(1)[0][0],
                    bold=all(p[4] for p in visible),
                    in_margin=relative < _MARGIN_BAND or relative > 1 - _MARGIN_BAND,
                )
            )
        pieces.clear()

    for text, x, y, size, bold in fragments:
        parts = text.split("\n")
        for index, part in enumerate(parts):
            if part:
                pieces.append((part, x, y, size, bold))
            if index < len(parts) - 1:
                flush()
    flush()
    return _merge_rows(_mark_list_items(lines))


def _mark_list_items(lines: list[_Line]) -> list[_Line]:
    """Fold bullet glyphs into a ``list_start`` flag on the line they introduce."""
    result: list[_Line] = []
    pending_bullet = False
    for line in lines:
        if line.text in _BULLETS:
            pending_bullet = True
            continue
        if len(line.text) > 2 and line.text[0] in _BULLETS and line.text[1] == " ":
            line.text = line.text[2:].strip()
            line.list_start = True
        elif pending_bullet:
            line.list_start = True
        pending_bullet = False
        result.append(line)
    return result


def _merge_rows(lines: list[_Line]) -> list[_Line]:
    """Join consecutive fragments that share a baseline into one line.

    A lone "3" or "b)" followed by text on the same baseline is the marker of a numbered list
    item; any other fragments sharing a baseline are the cells of a table row.
    """
    merged: list[_Line] = []
    for line in lines:
        previous = merged[-1] if merged else None
        if previous is not None and not line.list_start and line.x > previous.x:
            if _LIST_MARKER_RE.match(previous.text) and abs(previous.y - line.y) <= 2.5:
                marker = previous.text.strip("().")
                line.text = f"{marker}. {line.text}"
                line.list_start = True
                merged[-1] = line
                continue
            if abs(previous.y - line.y) <= 1.0:
                previous.text = f"{previous.text} | {line.text}"
                continue
        merged.append(line)
    return merged


def _strip_running_lines(pages: list[list[_Line]]) -> int:
    """Remove headers and footers: margin lines whose digit-masked text repeats on most pages."""
    if len(pages) < 2:
        return 0
    seen: Counter[str] = Counter()
    for lines in pages:
        for key in {re.sub(r"\d+", "#", line.text) for line in lines if line.in_margin and len(line.text) <= 120}:
            seen[key] += 1
    threshold = max(2, round(len(pages) * 0.6))
    running = {key for key, count in seen.items() if count >= threshold}
    removed = 0
    for lines in pages:
        kept = [
            line for line in lines if not (line.in_margin and re.sub(r"\d+", "#", line.text) in running)
        ]
        removed += len(lines) - len(kept)
        lines[:] = kept
    return removed


def _body_size(lines: list[_Line]) -> float:
    weights: Counter[float] = Counter()
    for line in lines:
        weights[line.size] += len(line.text)
    return weights.most_common(1)[0][0] if weights else 0.0


def _typical_leading(lines: list[_Line], size: float) -> float:
    """Most common baseline-to-baseline distance between consecutive body lines."""
    gaps: Counter[float] = Counter()
    for previous, line in pairwise(lines):
        if previous.page != line.page or previous.size != size or line.size != size:
            continue
        gap = previous.y - line.y
        if 0 < gap < size * 3 and abs(previous.x - line.x) <= 3:
            gaps[round(gap * 2) / 2] += 1
    return gaps.most_common(1)[0][0] if gaps else size * 1.45


def _join_wrapped(parts: list[str]) -> str:
    text = ""
    for part in parts:
        if not text:
            text = part
        elif (
            text.endswith("-")
            and len(text) >= 2
            and text[-2].isalpha()
            and part[:1].islower()
        ):
            text = text[:-1] + part  # undo an end-of-line hyphenation
        else:
            text = f"{text} {part}"
    return text


def parse_pdf(data: bytes) -> ParsedDocument:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise PdfParseError("The PDF is password-protected and cannot be read.")
        pages = [_page_lines(page, number) for number, page in enumerate(reader.pages, start=1)]
        metadata_title = (reader.metadata.title if reader.metadata else None) or None
    except PdfParseError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError) as exc:
        raise PdfParseError(f"The PDF could not be read: {exc}") from exc

    notes: list[str] = []
    removed = _strip_running_lines(pages)
    if removed:
        notes.append(f"removed {removed} repeated header/footer lines")

    lines = [line for page_lines in pages for line in page_lines]
    body = _body_size(lines)
    leading = _typical_leading(lines, body)

    def is_heading(line: _Line) -> bool:
        if line.list_start or " | " in line.text or len(line.text) > 120:
            return False
        if line.size >= body * 1.08:
            return True
        short_bold = line.bold and line.size >= body and len(line.text) <= 90 and not line.text.endswith(_TERMINAL)
        return short_bold or (body == 0 and numbered_heading(line.text) is not None)

    heading_sizes = sorted({line.size for line in lines if is_heading(line)}, reverse=True)
    level_of = {size: min(index + 1, 6) for index, size in enumerate(heading_sizes)}

    blocks: list[Block] = []
    parts: list[str] = []
    kind = "paragraph"
    start_page = 1
    previous: _Line | None = None
    previous_heading: _Line | None = None

    def flush() -> None:
        if parts:
            blocks.append(Block(kind, _join_wrapped(parts), page=start_page))  # type: ignore[arg-type]
            parts.clear()

    for line in lines:
        if is_heading(line):
            flush()
            continues_heading = (
                previous_heading is not None
                and previous is previous_heading
                and previous_heading.page == line.page
                and previous_heading.size == line.size
                and 0 < previous_heading.y - line.y <= line.size * 1.6
            )
            if continues_heading:
                blocks[-1].text = f"{blocks[-1].text} {line.text}"
            else:
                blocks.append(Block("heading", line.text, level=level_of[line.size], page=line.page))
            previous = previous_heading = line
            continue

        gap = previous.y - line.y if previous is not None and previous.page == line.page else None
        starts_block = (
            not parts
            or line.list_start
            or gap is None
            or gap <= 0
            or gap > max(leading * 1.3, line.size * 1.15)
            or abs(line.size - previous.size) > 0.6
            or (kind == "list_item" and line.x < previous.x - 3)
            or kind == "table_row"
            or " | " in line.text
        )
        if starts_block:
            flush()
            start_page = line.page
            if line.list_start:
                kind = "list_item"
            elif " | " in line.text:
                kind = "table_row"
            else:
                kind = "paragraph"
        parts.append(line.text)
        previous = line
    flush()

    blocks = _merge_across_pages(blocks)
    title = metadata_title.strip() if metadata_title and metadata_title.strip() else None
    if title is None or title.lower() in {"untitled", "(anonymous)"}:
        title = next((b.text for b in blocks if b.kind == "heading" and b.level == 1), None)
    return ParsedDocument(blocks=blocks, title=title, page_count=len(pages), notes=notes)


def _merge_across_pages(blocks: list[Block]) -> list[Block]:
    """Re-join a paragraph that was split by a page break (no terminal punctuation, lower-case restart)."""
    merged: list[Block] = []
    for block in blocks:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.kind == "paragraph"
            and block.kind == "paragraph"
            and previous.page is not None
            and block.page == previous.page + 1
            and not previous.text.endswith(_TERMINAL)
            and block.text[:1].islower()
        ):
            previous.text = _join_wrapped([previous.text, block.text])
            continue
        merged.append(block)
    return merged
