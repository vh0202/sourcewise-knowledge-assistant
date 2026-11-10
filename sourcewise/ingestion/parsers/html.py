"""HTML -> blocks, using only the standard library's tolerant ``html.parser``.

Navigation, scripts, styles and other page chrome are skipped; headings, paragraphs, list
items and table rows become blocks. Tables are linearised row by row with their column
headers (see ``linearize_table_row``).
"""

from __future__ import annotations

from html.parser import HTMLParser

from ..blocks import Block, ParsedDocument, linearize_table_row

_SKIPPED = frozenset(
    {"script", "style", "noscript", "template", "svg", "nav", "footer", "aside", "form", "button", "select"}
)
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
# Elements whose start or end terminates the text run in progress.
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "section", "article", "main", "header", "blockquote", "dl", "dt", "dd",
        "table", "thead", "tbody", "tfoot", "figure", "figcaption", "hr", "address", "details", "summary",
    }
)


class _BlockExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.title: str | None = None
        self._text: list[str] = []
        self._heading_level = 0
        self._list_depth = 0
        self._lists: list[int | None] = []  # per open list: next item number, or None for <ul>
        self._item_number: int | None = None
        self._skip_depth = 0
        self._in_pre = False
        self._row: list[str] | None = None
        self._row_is_header = False
        self._table_header: list[str] = []

    # -- helpers ---------------------------------------------------------------------------
    def _take_text(self) -> str:
        joined = "".join(self._text)
        self._text.clear()
        if self._in_pre:
            return joined.strip("\n")
        return " ".join(joined.split())

    def _flush(self) -> None:
        """Emit the text collected so far as a block of whatever kind encloses it."""
        text = self._take_text()
        if not text:
            return
        if self._heading_level:
            self.blocks.append(Block("heading", text, level=self._heading_level))
        elif self._in_pre:
            self.blocks.append(Block("code", text))
        elif self._list_depth:
            if self._item_number is not None:  # ordered items keep their number
                text, self._item_number = f"{self._item_number}. {text}", None
            self.blocks.append(Block("list_item", text))
        else:
            self.blocks.append(Block("paragraph", text))

    # -- parser callbacks ------------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._text.clear()
        elif tag in _HEADINGS:
            self._flush()
            self._heading_level = _HEADINGS[tag]
        elif tag in ("ul", "ol"):
            self._flush()
            start = dict(attrs).get("start") or "1"
            self._lists.append((int(start) if start.isdigit() else 1) if tag == "ol" else None)
        elif tag == "li":
            self._flush()
            self._list_depth += 1
            if self._lists and self._lists[-1] is not None:
                self._item_number = self._lists[-1]
                self._lists[-1] += 1
            else:
                self._item_number = None
        elif tag == "pre":
            self._flush()
            self._in_pre = True
        elif tag == "table":
            self._flush()
            self._table_header = []
        elif tag == "tr":
            self._flush()
            self._row, self._row_is_header = [], False
        elif tag in ("td", "th"):
            self._text.clear()
            if tag == "th":
                self._row_is_header = True
        elif tag == "br":
            self._text.append("\n" if self._in_pre else " ")
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self.title = self._take_text() or None
        elif tag in _HEADINGS:
            self._flush()
            self._heading_level = 0
        elif tag in ("ul", "ol"):
            self._flush()
            if self._lists:
                self._lists.pop()
        elif tag == "li":
            self._flush()
            self._list_depth = max(0, self._list_depth - 1)
            self._item_number = None
        elif tag == "pre":
            self._flush()
            self._in_pre = False
        elif tag in ("td", "th"):
            if self._row is not None:
                self._row.append(self._take_text())
        elif tag == "tr":
            self._end_row()
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._text.append(data)

    def _end_row(self) -> None:
        row, self._row = self._row, None
        self._text.clear()
        if not row or not any(row):
            return
        if self._row_is_header or not self._table_header:
            # An explicit <th> row, or failing that the first row, supplies the column names.
            self._table_header = row
            return
        text = linearize_table_row(self._table_header, row)
        if text:
            self.blocks.append(Block("table_row", text))

    def close(self) -> None:
        super().close()
        self._flush()


def parse_html(text: str) -> ParsedDocument:
    extractor = _BlockExtractor()
    extractor.feed(text)
    extractor.close()
    title = extractor.title or next(
        (b.text for b in extractor.blocks if b.kind == "heading" and b.level == 1), None
    )
    return ParsedDocument(blocks=extractor.blocks, title=title)
