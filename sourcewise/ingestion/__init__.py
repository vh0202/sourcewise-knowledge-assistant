"""Document ingestion: parsing, normalisation, chunking and indexing."""

from .blocks import Block, ParsedDocument
from .chunker import ChunkDraft, ChunkedDocument, ChunkingConfig, chunk_document
from .normalize import normalize_blocks, normalize_text
from .parsers import (
    SUPPORTED_EXTENSIONS,
    DocumentParseError,
    UnsupportedDocumentError,
    detect_kind,
    parse_document,
)
from .pipeline import IngestionError, ingest_document

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "Block",
    "ChunkDraft",
    "ChunkedDocument",
    "ChunkingConfig",
    "DocumentParseError",
    "IngestionError",
    "ParsedDocument",
    "UnsupportedDocumentError",
    "chunk_document",
    "detect_kind",
    "ingest_document",
    "normalize_blocks",
    "normalize_text",
    "parse_document",
]
