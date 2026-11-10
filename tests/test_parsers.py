"""Parsing of each supported file type into structural blocks."""

from __future__ import annotations

import io

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate

from sourcewise.ingestion.blocks import linearize_table_row
from sourcewise.ingestion.parsers import (
    DocumentParseError,
    UnsupportedDocumentError,
    decode_text,
    detect_kind,
    parse_document,
)


def kinds(document) -> list[tuple[str, int, str]]:
    return [(block.kind, block.level, block.text) for block in document.blocks]


# -- Markdown ----------------------------------------------------------------------------------
MARKDOWN = """---
title: "Leave Policy"
owner: People Team
---
# Leave Policy

Intro with **bold**, _italics_, `code` and a [link](https://example.com/x).
It continues on a second line.

## Annual leave

### Entitlement
Full-time staff get 25 days.

- Request leave in RotaBoard
- Give two weeks' notice
  for longer breaks
1. First step
2. Second step

| Tier | Monthly price |
|------|--------------:|
| Basic | £10 |
| Plus  | £20 |

<!-- an internal comment that must not be indexed -->

Setext heading
--------------
Body text.

```
keep   this
  verbatim
```
"""


def test_markdown_structure() -> None:
    document = parse_document("md", MARKDOWN.encode())
    assert document.title == "Leave Policy"
    assert kinds(document) == [
        ("heading", 1, "Leave Policy"),
        ("paragraph", 0, "Intro with bold, italics, code and a link. It continues on a second line."),
        ("heading", 2, "Annual leave"),
        ("heading", 3, "Entitlement"),
        ("paragraph", 0, "Full-time staff get 25 days."),
        ("list_item", 0, "Request leave in RotaBoard"),
        ("list_item", 0, "Give two weeks' notice for longer breaks"),
        ("list_item", 0, "1. First step"),
        ("list_item", 0, "2. Second step"),
        ("table_row", 0, "Tier: Basic; Monthly price: £10"),
        ("table_row", 0, "Tier: Plus; Monthly price: £20"),
        ("heading", 2, "Setext heading"),
        ("paragraph", 0, "Body text."),
        ("code", 0, "keep   this\n  verbatim"),
    ]


def test_markdown_title_falls_back_to_first_h1() -> None:
    assert parse_document("md", b"# Expenses\n\nText.").title == "Expenses"
    assert parse_document("md", b"Just text, no headings.").title is None


def test_markdown_keeps_underscores_inside_words() -> None:
    document = parse_document("md", b"Set the SOURCEWISE_TOP_K variable and snake_case_names.")
    assert document.blocks[0].text == "Set the SOURCEWISE_TOP_K variable and snake_case_names."


def test_table_rows_carry_their_column_headers() -> None:
    assert linearize_table_row(["Plan", "Price", ""], ["Active", "£69", "popular"]) == "Plan: Active; Price: £69; popular"
    assert linearize_table_row(["Plan", "Price"], ["Active", ""]) == "Plan: Active"


# -- plain text --------------------------------------------------------------------------------
PLAINTEXT = """REMOTE WORKING GUIDELINES

Calderwick Health - Version 2

1. Who is eligible

Support staff may work remotely
up to two days a week.

1.1 Core hours

Be available between 10:00 and 15:00.

- Use your company laptop.
- Lock your screen.
a) First option
b) Second option

EQUIPMENT

A headset is provided.

Underlined heading
------------------

More text. With two sentences.
"""


def test_plaintext_structure_is_inferred_from_layout() -> None:
    document = parse_document("txt", PLAINTEXT.encode())
    assert document.title == "REMOTE WORKING GUIDELINES"
    assert kinds(document) == [
        ("heading", 1, "REMOTE WORKING GUIDELINES"),
        ("paragraph", 0, "Calderwick Health - Version 2"),
        ("heading", 2, "1. Who is eligible"),
        ("paragraph", 0, "Support staff may work remotely up to two days a week."),
        ("heading", 3, "1.1 Core hours"),
        ("paragraph", 0, "Be available between 10:00 and 15:00."),
        ("list_item", 0, "Use your company laptop."),
        ("list_item", 0, "Lock your screen."),
        ("list_item", 0, "a. First option"),
        ("list_item", 0, "b. Second option"),
        ("heading", 2, "EQUIPMENT"),
        ("paragraph", 0, "A headset is provided."),
        ("heading", 2, "Underlined heading"),
        ("paragraph", 0, "More text. With two sentences."),
    ]


def test_plaintext_numbered_sentence_is_not_a_heading() -> None:
    document = parse_document("txt", b"Title\n\n1. Lock the cash drawer before you leave.\n\n2. Set the alarm.\n")
    assert [block.kind for block in document.blocks] == ["heading", "list_item", "list_item"]


# -- HTML --------------------------------------------------------------------------------------
HTML = """<!doctype html>
<html><head><title>IT FAQ &amp; Help</title><style>body { color: red }</style>
<script>var tracking = "must not be indexed";</script></head>
<body>
<nav><a href="/">Home</a> | <a href="/it">IT</a></nav>
<h1>IT FAQ</h1>
<h2>Accounts &amp; passwords</h2>
<p>Use the <b>self-service</b> page.<br>It needs the app.</p>
<ul><li>First bullet</li><li><p>Second bullet</p></li></ul>
<ol start="3"><li>Third step</li><li>Fourth step</li></ol>
<table>
  <tr><th>Priority</th><th>Response</th></tr>
  <tr><td>P1</td><td>15 minutes</td></tr>
  <tr><td>P2</td><td>1 hour</td></tr>
</table>
<pre>line one
  line two</pre>
<footer>Footer text that is page chrome</footer>
</body></html>"""


def test_html_structure_and_chrome_removal() -> None:
    document = parse_document("html", HTML.encode())
    assert document.title == "IT FAQ & Help"
    assert kinds(document) == [
        ("heading", 1, "IT FAQ"),
        ("heading", 2, "Accounts & passwords"),
        ("paragraph", 0, "Use the self-service page. It needs the app."),
        ("list_item", 0, "First bullet"),
        ("list_item", 0, "Second bullet"),
        ("list_item", 0, "3. Third step"),
        ("list_item", 0, "4. Fourth step"),
        ("table_row", 0, "Priority: P1; Response: 15 minutes"),
        ("table_row", 0, "Priority: P2; Response: 1 hour"),
        ("code", 0, "line one\n  line two"),
    ]
    text = " ".join(block.text for block in document.blocks)
    assert "tracking" not in text and "Home" not in text and "Footer" not in text


def test_html_without_title_uses_first_heading_and_tolerates_bad_markup() -> None:
    document = parse_document("html", b"<h1>Guide</h1><p>Unclosed paragraph<p>Another one<div>And a div")
    assert document.title == "Guide"
    assert [block.text for block in document.blocks] == ["Guide", "Unclosed paragraph", "Another one", "And a div"]


# -- PDF ---------------------------------------------------------------------------------------
def build_pdf() -> bytes:
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10.5, leading=15, spaceAfter=7)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=8)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=14, leading=18, spaceBefore=10, spaceAfter=6)

    def decorate(canvas, document) -> None:
        canvas.setFont("Helvetica", 8)
        canvas.drawString(20 * mm, A4[1] - 12 * mm, "Northgate Clinic - Desk Procedure")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {document.page}")

    def items(texts: list[str], bullet: str) -> ListFlowable:
        return ListFlowable([ListItem(Paragraph(text, body)) for text in texts], bulletType=bullet)

    long_paragraph = (
        "The opening receptionist arrives thirty minutes before the first appointment so that the "
        "waiting area, the card terminal and the day lists are ready, and so that any cancellations "
        "left on the answerphone overnight can be entered before patients arrive."
    )
    story = [
        Paragraph("Desk Procedure", h1),
        Paragraph("1. Opening", h2),
        Paragraph(long_paragraph, body),
        items(["Disarm the alarm.", "Count the float with a colleague and record it in the till log for the clinic manager to check."], "1"),
        Paragraph("The float is £100.", body),
        PageBreak(),
        Paragraph("2. Closing", h2),
        Paragraph("Cash is banked every <b>Tuesday</b> and Friday.", body),
        items(["Lock the internal doors.", "Set the alarm."], "bullet"),
        PageBreak(),
        Paragraph("3. Review", h2),
        Paragraph("This procedure is reviewed every 12 months.", body),
    ]
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, title="Desk Procedure", topMargin=24 * mm, bottomMargin=20 * mm).build(
        story, onFirstPage=decorate, onLaterPages=decorate
    )
    return buffer.getvalue()


@pytest.fixture(scope="module")
def pdf_document():
    return parse_document("pdf", build_pdf())


def test_pdf_headings_come_from_font_size_and_carry_levels(pdf_document) -> None:
    headings = [(b.level, b.text, b.page) for b in pdf_document.blocks if b.kind == "heading"]
    assert headings == [(1, "Desk Procedure", 1), (2, "1. Opening", 1), (2, "2. Closing", 2), (2, "3. Review", 3)]
    assert pdf_document.title == "Desk Procedure"
    assert pdf_document.page_count == 3


def test_pdf_wrapped_lines_are_rejoined_into_paragraphs(pdf_document) -> None:
    paragraphs = [b.text for b in pdf_document.blocks if b.kind == "paragraph"]
    assert paragraphs[0].startswith("The opening receptionist arrives thirty minutes")
    assert paragraphs[0].endswith("can be entered before patients arrive.")
    assert "Cash is banked every Tuesday and Friday." in paragraphs  # inline bold does not split the line


def test_pdf_lists_keep_numbers_and_join_continuation_lines(pdf_document) -> None:
    items = [b.text for b in pdf_document.blocks if b.kind == "list_item"]
    assert items == [
        "1. Disarm the alarm.",
        "2. Count the float with a colleague and record it in the till log for the clinic manager to check.",
        "Lock the internal doors.",
        "Set the alarm.",
    ]


def test_pdf_running_headers_and_footers_are_removed(pdf_document) -> None:
    text = " ".join(block.text for block in pdf_document.blocks)
    assert "Northgate Clinic - Desk Procedure" not in text
    assert "Page 1" not in text and "Page 3" not in text
    assert pdf_document.notes == ["removed 6 repeated header/footer lines"]


def test_pdf_blocks_record_their_page(pdf_document) -> None:
    by_text = {block.text: block.page for block in pdf_document.blocks}
    assert by_text["The float is £100."] == 1
    assert by_text["Set the alarm."] == 2
    assert by_text["This procedure is reviewed every 12 months."] == 3


def test_corrupt_pdf_raises_a_parse_error() -> None:
    with pytest.raises(DocumentParseError):
        parse_document("pdf", b"%PDF-1.7\nthis is not really a pdf")


# -- detection and decoding --------------------------------------------------------------------
@pytest.mark.parametrize(
    ("filename", "data", "expected"),
    [
        ("notes.md", b"# hi", "md"),
        ("notes.MARKDOWN", b"# hi", "md"),
        ("policy.txt", b"hi", "txt"),
        ("page.htm", b"<p>hi</p>", "html"),
        ("scan.pdf", b"%PDF-1.4 ...", "pdf"),
        ("wrongly-named.txt", b"%PDF-1.4 ...", "pdf"),  # content wins over extension
    ],
)
def test_detect_kind(filename: str, data: bytes, expected: str) -> None:
    assert detect_kind(filename, data) == expected


def test_detect_kind_rejects_unsupported_and_mislabelled_files() -> None:
    with pytest.raises(UnsupportedDocumentError, match="Supported types"):
        detect_kind("budget.xlsx", b"PK\x03\x04")
    with pytest.raises(DocumentParseError, match="not a PDF"):
        detect_kind("fake.pdf", b"hello")


def test_decode_text_handles_bom_and_windows_1252() -> None:
    assert decode_text("﻿Title".encode()) == "Title"
    assert decode_text("Café £12".encode("cp1252")) == "Café £12"
