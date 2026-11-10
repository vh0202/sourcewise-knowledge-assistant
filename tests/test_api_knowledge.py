"""Knowledge-base administration over the HTTP API."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sourcewise.container import Container

from .test_parsers import HTML, MARKDOWN, PLAINTEXT, build_pdf

UPLOADS = {
    "md": ("leave-policy.md", MARKDOWN.encode(), "text/markdown"),
    "txt": ("remote-working.txt", PLAINTEXT.encode(), "text/plain"),
    "html": ("it-faq.html", HTML.encode(), "text/html"),
    "pdf": ("desk-procedure.pdf", build_pdf(), "application/pdf"),
}


def create_collection(admin: TestClient, name: str = "Policies", description: str = "Company policies") -> dict:
    response = admin.post("/api/collections", json={"name": name, "description": description})
    assert response.status_code == 201, response.text
    return response.json()


def upload(admin: TestClient, collection_id: int, kind: str = "md", **data) -> dict:
    filename, content, content_type = UPLOADS[kind]
    response = admin.post(
        "/api/documents",
        files={"file": (filename, content, content_type)},
        data={"collection_id": str(collection_id), **data},
    )
    assert response.status_code == 202, response.text
    return response.json()


# -- collections -------------------------------------------------------------------------------
def test_collection_crud(admin: TestClient) -> None:
    created = create_collection(admin, "  Policies  ", "  Company policies  ")
    assert (created["name"], created["description"]) == ("Policies", "Company policies")
    assert (created["document_count"], created["chunk_count"], created["starter_questions"]) == (0, 0, [])
    assert created["created_at"].endswith("Z")

    renamed = admin.patch(f"/api/collections/{created['id']}", json={"name": "HR Policies", "description": "People"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "HR Policies"
    assert [c["name"] for c in admin.get("/api/collections").json()] == ["HR Policies"]

    assert admin.delete(f"/api/collections/{created['id']}").status_code == 204
    assert admin.get("/api/collections").json() == []
    assert admin.delete(f"/api/collections/{created['id']}").status_code == 404


def test_collection_names_are_unique_and_required(admin: TestClient) -> None:
    create_collection(admin, "Policies")
    other = create_collection(admin, "Guides")
    assert admin.post("/api/collections", json={"name": "policies", "description": ""}).status_code == 409
    assert admin.patch(f"/api/collections/{other['id']}", json={"name": "POLICIES", "description": ""}).status_code == 409
    # Renaming a collection to its own name is fine.
    assert admin.patch(f"/api/collections/{other['id']}", json={"name": "Guides", "description": "x"}).status_code == 200
    assert admin.post("/api/collections", json={"name": "   ", "description": ""}).status_code == 422
    assert admin.patch("/api/collections/999", json={"name": "Nope", "description": ""}).status_code == 404


def test_collection_counts_follow_its_documents(admin: TestClient) -> None:
    collection = create_collection(admin)
    document = upload(admin, collection["id"], "md")
    (listed,) = admin.get("/api/collections").json()
    ready = admin.get(f"/api/documents/{document['id']}").json()
    assert (listed["document_count"], listed["chunk_count"]) == (1, ready["chunk_count"])


# -- upload and ingestion ----------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["md", "txt", "html", "pdf"])
def test_upload_is_accepted_then_ingested_in_the_background(admin: TestClient, kind: str) -> None:
    collection = create_collection(admin)
    accepted = upload(admin, collection["id"], kind)
    assert accepted["status"] == "queued" and accepted["chunk_count"] == 0
    assert accepted["kind"] == kind and accepted["collection_name"] == "Policies"

    document = admin.get(f"/api/documents/{accepted['id']}").json()
    assert document["status"] == "ready" and document["error"] is None
    assert document["chunk_count"] > 0 and document["char_count"] > 0
    assert [stage["name"] for stage in document["stages"]] == ["parse", "normalize", "chunk", "index"]
    assert [stage["label"] for stage in document["stages"]] == ["Parse", "Normalise", "Chunk", "Index"]
    assert all(stage["status"] == "done" for stage in document["stages"])
    assert document["size_bytes"] == len(UPLOADS[kind][1])
    assert document["page_count"] == (3 if kind == "pdf" else None)
    assert document["indexed_at"].endswith("Z")


def test_upload_with_a_custom_title(admin: TestClient) -> None:
    collection = create_collection(admin)
    document = upload(admin, collection["id"], "md", title="Leave rules 2026")
    assert admin.get(f"/api/documents/{document['id']}").json()["title"] == "Leave rules 2026"


@pytest.mark.parametrize(
    ("filename", "content", "status", "message"),
    [
        ("budget.xlsx", b"PK\x03\x04binary", 415, "Unsupported file type"),
        ("fake.pdf", b"this is not a pdf", 415, "not a PDF"),
        ("empty.txt", b"", 400, "empty"),
    ],
)
def test_bad_uploads_are_rejected_with_a_clear_message(admin: TestClient, filename: str, content: bytes, status: int, message: str) -> None:
    collection = create_collection(admin)
    response = admin.post("/api/documents", files={"file": (filename, content)}, data={"collection_id": str(collection["id"])})
    assert response.status_code == status
    assert message in response.json()["detail"]
    assert admin.get("/api/documents").json() == []


def test_oversized_and_duplicate_uploads(admin: TestClient, container: Container) -> None:
    collection = create_collection(admin)
    container.settings.max_upload_mb = 1
    big = admin.post("/api/documents", files={"file": ("big.txt", b"x" * (1024 * 1024 + 1))}, data={"collection_id": str(collection["id"])})
    assert big.status_code == 413 and "1 MB" in big.json()["detail"]

    upload(admin, collection["id"], "md")
    filename, content, content_type = UPLOADS["md"]
    again = admin.post("/api/documents", files={"file": ("copy-" + filename, content, content_type)}, data={"collection_id": str(collection["id"])})
    assert again.status_code == 409 and "already in the collection" in again.json()["detail"]
    # The same file may live in a different collection.
    other = create_collection(admin, "Other")
    upload(admin, other["id"], "md")


def test_upload_needs_an_existing_collection_and_a_file(admin: TestClient) -> None:
    assert admin.post("/api/documents", files={"file": ("a.txt", b"Text.")}, data={"collection_id": "999"}).status_code == 404
    collection = create_collection(admin)
    assert admin.post("/api/documents", data={"collection_id": str(collection["id"])}).status_code == 422


def test_a_document_that_cannot_be_ingested_is_listed_as_failed(admin: TestClient) -> None:
    collection = create_collection(admin)
    response = admin.post("/api/documents", files={"file": ("headings.md", b"# Only\n\n## Headings\n")}, data={"collection_id": str(collection["id"])})
    assert response.status_code == 202
    document = admin.get(f"/api/documents/{response.json()['id']}").json()
    assert document["status"] == "failed"
    assert "No extractable text" in document["error"]
    assert document["stages"][0]["status"] == "failed"


# -- listing and inspection --------------------------------------------------------------------
def test_documents_are_listed_with_their_collection_and_can_be_filtered(admin: TestClient) -> None:
    first, second = create_collection(admin, "Alpha"), create_collection(admin, "Beta")
    upload(admin, first["id"], "md")
    upload(admin, first["id"], "txt")
    upload(admin, second["id"], "html")

    everything = admin.get("/api/documents").json()
    assert [(d["collection_name"], d["title"]) for d in everything] == [
        ("Alpha", "Leave Policy"), ("Alpha", "Remote Working Guidelines"), ("Beta", "IT FAQ & Help"),
    ]
    only_beta = admin.get("/api/documents", params={"collection_id": second["id"]}).json()
    assert [d["title"] for d in only_beta] == ["IT FAQ & Help"]
    assert admin.get("/api/documents/999").status_code == 404


def test_chunk_inspector_payload(admin: TestClient) -> None:
    collection = create_collection(admin)
    document = upload(admin, collection["id"], "pdf")
    payload = admin.get(f"/api/documents/{document['id']}/chunks").json()

    assert payload["document"]["id"] == document["id"] and payload["document"]["status"] == "ready"
    assert payload["chunking"] == {"max_chars": 700, "overlap_chars": 150}
    chunks = payload["chunks"]
    assert len(chunks) == payload["document"]["chunk_count"]
    assert [chunk["ordinal"] for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert set(chunk) == {
            "id", "ordinal", "text", "heading_path", "page_start", "page_end", "start_char", "end_char",
            "overlap_chars", "token_estimate",
        }
        assert chunk["end_char"] - chunk["start_char"] == len(chunk["text"])
        assert chunk["page_start"] in (1, 2, 3)
    assert [chunk["heading_path"] for chunk in chunks] == [["1. Opening"], ["2. Closing"], ["3. Review"]]
    assert admin.get("/api/documents/999/chunks").status_code == 404


def test_overlap_is_visible_in_the_inspector_for_a_long_section(admin: TestClient) -> None:
    collection = create_collection(admin)
    long_section = "# Guide\n\n## Long section\n\n" + " ".join(
        f"Sentence number {i} explains one more detail of the procedure." for i in range(1, 41)
    )
    response = admin.post("/api/documents", files={"file": ("long.md", long_section.encode())}, data={"collection_id": str(collection["id"])})
    chunks = admin.get(f"/api/documents/{response.json()['id']}/chunks").json()["chunks"]
    assert len(chunks) >= 3
    assert chunks[0]["overlap_chars"] == 0
    for previous, current in pairwise(chunks):
        assert 0 < current["overlap_chars"] <= 225
        assert current["start_char"] < previous["end_char"]
        assert current["text"][: current["overlap_chars"]] == previous["text"][-current["overlap_chars"] :]


# -- re-index and delete -----------------------------------------------------------------------
def test_reindex_runs_the_pipeline_again(admin: TestClient, container: Container) -> None:
    collection = create_collection(admin)
    document = upload(admin, collection["id"], "md")
    before = admin.get(f"/api/documents/{document['id']}/chunks").json()["chunks"]

    response = admin.post(f"/api/documents/{document['id']}/reindex")
    assert response.status_code == 202 and response.json()["status"] == "queued"

    after = admin.get(f"/api/documents/{document['id']}/chunks").json()
    assert after["document"]["status"] == "ready"
    assert [c["text"] for c in after["chunks"]] == [c["text"] for c in before]
    assert not {c["id"] for c in after["chunks"]} & {c["id"] for c in before}
    assert container.lexical.chunk_count() == len(before)
    assert admin.post("/api/documents/999/reindex").status_code == 404


def test_delete_removes_the_document_everywhere(admin: TestClient, container: Container) -> None:
    collection = create_collection(admin)
    document = upload(admin, collection["id"], "md")
    stored = Path(container.settings.upload_dir)
    assert len(list(stored.iterdir())) == 1

    assert admin.delete(f"/api/documents/{document['id']}").status_code == 204
    assert admin.get("/api/documents").json() == []
    assert admin.get(f"/api/documents/{document['id']}").status_code == 404
    assert admin.delete(f"/api/documents/{document['id']}").status_code == 404
    assert container.lexical.chunk_count() == 0
    assert list(stored.iterdir()) == []


def test_deleting_a_collection_deletes_its_documents(admin: TestClient, container: Container) -> None:
    keep, drop = create_collection(admin, "Keep"), create_collection(admin, "Drop")
    kept = upload(admin, keep["id"], "md")
    upload(admin, drop["id"], "txt")
    upload(admin, drop["id"], "html")

    assert admin.delete(f"/api/collections/{drop['id']}").status_code == 204
    assert [d["id"] for d in admin.get("/api/documents").json()] == [kept["id"]]
    assert container.lexical.chunk_count() == admin.get(f"/api/documents/{kept['id']}").json()["chunk_count"]
