"""File-type detection and dispatch to the format-specific parsers."""

from __future__ import annotations

from pathlib import PurePath

from ..blocks import ParsedDocument
from .html import parse_html
from .markdown import parse_markdown
from .pdf import PdfParseError, parse_pdf
from .plaintext import parse_plaintext

# extension -> document kind
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
}


class UnsupportedDocumentError(ValueError):
    """The file type is not one SourceWise can ingest."""


class DocumentParseError(ValueError):
    """The file is of a supported type but could not be parsed."""


def detect_kind(filename: str, data: bytes) -> str:
    """Return the document kind for an upload, trusting content over extension for PDFs."""
    extension = PurePath(filename).suffix.lower()
    looks_like_pdf = data[:5] == b"%PDF-"
    if extension == ".pdf" and not looks_like_pdf:
        raise DocumentParseError("The file has a .pdf extension but is not a PDF document.")
    if looks_like_pdf:
        return "pdf"
    try:
        return SUPPORTED_EXTENSIONS[extension]
    except KeyError:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedDocumentError(
            f"Unsupported file type '{extension or filename}'. Supported types: {allowed}."
        ) from None


def decode_text(data: bytes) -> str:
    """Decode an uploaded text file: UTF-8 (with or without BOM), then Windows-1252."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_document(kind: str, data: bytes) -> ParsedDocument:
    """Parse raw file bytes of the given kind into a ``ParsedDocument``."""
    if kind == "pdf":
        try:
            return parse_pdf(data)
        except PdfParseError as exc:
            raise DocumentParseError(str(exc)) from exc
    text = decode_text(data)
    if kind == "md":
        return parse_markdown(text)
    if kind == "html":
        return parse_html(text)
    if kind == "txt":
        return parse_plaintext(text)
    raise UnsupportedDocumentError(f"Unsupported document kind '{kind}'.")


__all__ = [
    "SUPPORTED_EXTENSIONS",
    "DocumentParseError",
    "UnsupportedDocumentError",
    "decode_text",
    "detect_kind",
    "parse_document",
]
