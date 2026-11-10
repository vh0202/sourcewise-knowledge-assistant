"""The ingestion pipeline end to end, for every supported file type."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from sourcewise.container import Container
from sourcewise.ingestion.pipeline import tidy_title
from sourcewise.knowledge import (
    KnowledgeError,
    create_document,
    delete_document,
    run_ingestion,
    safe_filename,
    title_from_filename,
)
from sourcewise.models import Chunk, Collection, Document

from .test_parsers import HTML, MARKDOWN, PLAINTEXT, build_pdf

FILES = {
    "md": ("leave-policy.md", MARKDOWN.encode()),
    "txt": ("remote-working.txt", PLAINTEXT.encode()),
    "html": ("it-faq.html", HTML.encode()),
    "pdf": ("desk-procedure.pdf", build_pdf()),
}


def ingest(container: Container, filename: str, data: bytes, **kwargs) -> Document:
    with container.session_factory() as session:
        collection = session.execute(select(Collection)).scalars().first()
        if collection is None:
            collection = Collection(name="Test", description="", starter_questions=[])
            session.add(collection)
            session.commit()
        document = create_document(container, session, collection=collection, filename=filename, data=data, **kwargs)
        document_id = document.id
    run_ingestion(container, document_id)
    with container.session_factory() as session:
        document = session.get(Document, document_id)
        session.refresh(document)
        _ = document.chunks  # load before the session closes
        return document


@pytest.mark.parametrize("kind", ["md", "txt", "html", "pdf"])
def test_each_file_type_is_ingested_and_searchable(container: Container, kind: str) -> None:
    filename, data = FILES[kind]
    document = ingest(container, filename, data)

    assert document.kind == kind
    assert document.status == "ready", document.error
    assert document.error is None
    assert document.indexed_at is not None
    assert document.chunk_count == len(document.chunks) > 0
    assert document.char_count > 0
    assert document.page_count == (3 if kind == "pdf" else None)
    assert container.lexical.chunk_count() == document.chunk_count

    assert [stage["name"] for stage in document.stages] == ["parse", "normalize", "chunk", "index"]
    assert all(stage["status"] == "done" and stage["duration_ms"] >= 0 and stage["detail"] for stage in document.stages)

    for chunk in document.chunks:
        assert chunk.collection_id == document.collection_id
        assert chunk.token_estimate > 0
        assert (chunk.page_start is not None) == (kind == "pdf")

    # Every chunk can be found again through the index.
    hits = container.retriever.search(document.chunks[0].text, top_k=3)
    assert document.chunks[0].id in [hit.chunk_id for hit in hits]


def test_title_comes_from_the_document_unless_the_admin_supplied_one(container: Container) -> None:
    parsed = ingest(container, *FILES["md"])
    assert parsed.title == "Leave Policy"  # YAML front matter
    shouted = ingest(container, *FILES["txt"])
    assert shouted.title == "Remote Working Guidelines"  # an ALL-CAPS title is tidied
    chosen = ingest(container, "it-faq.html", HTML.encode() + b" ", title="  IT questions  ")
    assert chosen.title == "IT questions"
    untitled = ingest(container, "holiday_rota-2026.txt", b"A note with a full stop at the end.\n\nAnd a second paragraph.")
    assert untitled.title == "Holiday Rota 2026"  # falls back to the file name


def test_stage_details_describe_what_happened(container: Container) -> None:
    document = ingest(container, *FILES["pdf"])
    details = {stage["name"]: stage["detail"] for stage in document.stages}
    assert "from 3 pages" in details["parse"]
    assert "removed 6 repeated header/footer lines" in details["parse"]
    assert "characters" in details["normalize"]
    assert details["chunk"].startswith(f"{document.chunk_count} chunk")
    assert container.retriever.label in details["index"]


def test_pdf_chunks_know_their_pages_and_sections(container: Container) -> None:
    document = ingest(container, *FILES["pdf"])
    by_section = {tuple(chunk.heading_path): chunk for chunk in document.chunks}
    assert by_section[("1. Opening",)].page_start == 1
    assert by_section[("2. Closing",)].page_start == by_section[("2. Closing",)].page_end == 2
    assert by_section[("3. Review",)].page_start == 3
    assert "Cash is banked every Tuesday and Friday." in by_section[("2. Closing",)].text


def test_reindexing_replaces_chunks_and_index_entries(container: Container) -> None:
    document = ingest(container, *FILES["md"])
    before = [chunk.id for chunk in document.chunks]

    run_ingestion(container, document.id)

    with container.session_factory() as session:
        after = session.execute(select(Chunk.id).where(Chunk.document_id == document.id)).scalars().all()
        refreshed = session.get(Document, document.id)
        assert refreshed.status == "ready"
        assert refreshed.chunk_count == len(after) == len(before)
    assert not set(before) & set(after)  # old rows are gone ...
    assert container.lexical.chunk_count() == len(after)  # ... and so are their index entries


def test_a_document_without_text_fails_with_a_helpful_message(container: Container) -> None:
    document = ingest(container, "empty.md", b"# Only a heading\n\n## And another\n")
    assert document.status == "failed"
    assert "No extractable text" in document.error
    assert document.chunk_count == 0 and document.chunks == []
    assert document.stages[0]["status"] == "failed"
    assert [stage["status"] for stage in document.stages[1:]] == ["pending", "pending", "pending"]
    assert container.lexical.chunk_count() == 0


def test_a_corrupt_pdf_fails_without_raising(container: Container) -> None:
    document = ingest(container, "broken.pdf", b"%PDF-1.7\nnot a real pdf body")
    assert document.status == "failed"
    assert "could not be read" in document.error


def test_a_failed_document_can_be_reindexed_after_the_file_is_fixed(container: Container) -> None:
    document = ingest(container, "empty.md", b"# Only a heading\n")
    Path(document.storage_path).write_bytes(b"# Title\n\nNow there is a paragraph of body text.")
    run_ingestion(container, document.id)
    with container.session_factory() as session:
        fixed = session.get(Document, document.id)
        assert (fixed.status, fixed.error, fixed.chunk_count) == ("ready", None, 1)


def test_upload_validation(container: Container) -> None:
    with container.session_factory() as session:
        collection = Collection(name="Validation", description="", starter_questions=[])
        session.add(collection)
        session.commit()

        def attempt(filename: str, data: bytes) -> KnowledgeError:
            with pytest.raises(KnowledgeError) as caught:
                create_document(container, session, collection=collection, filename=filename, data=data)
            return caught.value

        assert attempt("empty.txt", b"").status_code == 400
        assert attempt("sheet.xlsx", b"PK\x03\x04").status_code == 415
        assert attempt("fake.pdf", b"plain text").status_code == 415
        too_big = b"x" * (container.settings.max_upload_mb * 1024 * 1024 + 1)
        assert attempt("big.txt", too_big).status_code == 413

        create_document(container, session, collection=collection, filename="a.txt", data=b"Same content.")
        duplicate = attempt("b.txt", b"Same content.")
        assert duplicate.status_code == 409 and "already in the collection" in duplicate.message


def test_deleting_a_document_removes_rows_index_entries_and_file(container: Container) -> None:
    keep = ingest(container, *FILES["md"])
    drop = ingest(container, *FILES["txt"])
    stored = Path(drop.storage_path)
    assert stored.exists()

    with container.session_factory() as session:
        delete_document(container, session, session.get(Document, drop.id))
        assert session.get(Document, drop.id) is None
        assert session.execute(select(func.count(Chunk.id)).where(Chunk.document_id == drop.id)).scalar_one() == 0
    assert not stored.exists()
    assert container.lexical.chunk_count() == keep.chunk_count
    assert container.retriever.search("core hours laptop") == []


def test_ingesting_a_missing_document_is_a_no_op(container: Container) -> None:
    run_ingestion(container, 12345)  # must not raise


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\Leave Policy (v2).md", "Leave Policy _v2_.md"),
        ("r\u00e9sum\u00e9<script>.txt", "r_sum_script_.txt"),
        ("....", "document"),
    ],
)
def test_uploaded_file_names_are_sanitised(raw: str, expected: str) -> None:
    assert safe_filename(raw) == expected


def test_title_helpers() -> None:
    assert title_from_filename("travel-and_expense-policy.md") == "Travel And Expense Policy"
    assert title_from_filename("IT-faq.html") == "IT Faq"
    assert tidy_title("REMOTE AND HYBRID WORKING GUIDELINES") == "Remote and Hybrid Working Guidelines"
    assert tidy_title("  Already   Fine  ") == "Already Fine"
