"""BM25 ranking (pure Python and SQLite FTS5), the cosine retriever and rank fusion."""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from sourcewise.config import PROJECT_ROOT
from sourcewise.container import Container, build_container
from sourcewise.db import make_engine
from sourcewise.main import create_app
from sourcewise.models import Chunk, Document
from sourcewise.retrieval import (
    BM25Retriever,
    CosineRetriever,
    FieldWeights,
    Fts5Retriever,
    IndexEntry,
    ReciprocalRankFusion,
    Retriever,
    TermStatistics,
    build_lexical_retriever,
    fts5_available,
    index_entry,
    sync_index,
)
from sourcewise.retrieval.bm25 import K1, B, bm25_idf
from sourcewise.retrieval.vector import cosine_similarity

from .conftest import ADMIN, make_settings, sign_in
from .fakes import KeywordEmbedder

ENTRIES = [
    IndexEntry(1, 10, 100, "Full-time employees receive 25 days of paid annual leave each year.", "Leave > Annual leave", "Employee Handbook"),
    IndexEntry(2, 10, 100, "Telephone your line manager before 08:00 on the first day of sickness absence.", "Leave > Sickness absence", "Employee Handbook"),
    IndexEntry(3, 11, 100, "Claim 45p per mile when you use your own car for work journeys.", "Travel > Driving", "Travel and Expense Policy"),
    IndexEntry(4, 11, 100, "Hotel rooms are limited to £120 a night including breakfast.", "Accommodation > Hotels", "Travel and Expense Policy"),
    IndexEntry(5, 12, 200, "Passwords must be at least 14 characters long.", "Passwords and sign-in > Passwords", "Information Security Policy"),
    IndexEntry(6, 12, 200, "Report a lost or stolen laptop to the IT Service Desk within one hour.", "Devices > Lost or stolen devices", "Information Security Policy"),
    IndexEntry(7, 13, 200, "The annual review of access rights happens every quarter; leave requests are not affected.", "Access", "Information Security Policy"),
]

FTS5 = fts5_available(make_engine("sqlite://"))
needs_fts5 = pytest.mark.skipif(not FTS5, reason="this SQLite build has no FTS5 extension")


def make_retriever(kind: str, tmp_path):
    if kind == "bm25":
        return BM25Retriever()
    return Fts5Retriever(make_engine(f"sqlite:///{(tmp_path / 'index.db').as_posix()}"))


LEXICAL = ["bm25", pytest.param("fts5", marks=needs_fts5)]


@pytest.fixture(params=LEXICAL)
def lexical(request, tmp_path):
    retriever = make_retriever(request.param, tmp_path)
    retriever.add(ENTRIES)
    return retriever


def ids(hits) -> list[int]:
    return [hit.chunk_id for hit in hits]


# -- behaviour shared by both lexical retrievers ---------------------------------------------
def test_lexical_retrievers_implement_the_interfaces(lexical) -> None:
    assert isinstance(lexical, Retriever)
    assert isinstance(lexical, TermStatistics)


def test_relevant_chunk_ranks_first(lexical) -> None:
    assert ids(lexical.search("How many days of annual leave do employees get?"))[0] == 1
    assert ids(lexical.search("lost laptop"))[0] == 6
    assert ids(lexical.search("minimum password length in characters"))[0] == 5
    assert ids(lexical.search("mileage for my car"))[0] == 3


def test_query_and_documents_meet_at_the_stem(lexical) -> None:
    assert ids(lexical.search("reporting stolen laptops"))[0] == 6
    assert ids(lexical.search("claiming miles"))[0] == 3


def test_scores_are_positive_and_sorted_best_first(lexical) -> None:
    hits = lexical.search("annual leave review", top_k=5)
    assert len(hits) >= 2
    assert all(hit.score > 0 for hit in hits)
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)


def test_top_k_limits_the_result(lexical) -> None:
    assert len(lexical.search("leave policy handbook", top_k=2)) == 2


def test_no_match_and_stopword_only_queries_return_nothing(lexical) -> None:
    assert lexical.search("zebra crossing") == []
    assert lexical.search("what is the") == []
    assert lexical.search("") == []


def test_a_heading_match_outweighs_a_body_match(lexical) -> None:
    # Chunk 4 has "hotel" in its body and in its heading; chunk 8 has it in its (shorter) body only.
    lexical.add([IndexEntry(8, 14, 100, "Book a hotel through the travel desk.", "Booking", "Travel and Expense Policy")])
    assert ids(lexical.search("hotels"))[:2] == [4, 8]


def test_search_can_be_scoped_to_collections(lexical) -> None:
    assert ids(lexical.search("annual leave", collection_ids=[200])) == [7]
    assert 7 not in ids(lexical.search("annual leave", collection_ids=[100]))
    assert lexical.search("annual leave", collection_ids=[]) == []
    assert lexical.search("annual leave", collection_ids=[999]) == []


def test_removing_a_document_removes_its_chunks(lexical) -> None:
    lexical.remove_document(10)
    assert lexical.chunk_count() == len(ENTRIES) - 2
    assert 1 not in ids(lexical.search("annual leave"))
    assert lexical.document_frequencies(["sick"]) == {"sick": 0}


def test_adding_a_chunk_again_replaces_it(lexical) -> None:
    lexical.add([IndexEntry(5, 12, 200, "Badges must be worn at chest height.", "Dress", "Information Security Policy")])
    assert lexical.chunk_count() == len(ENTRIES)
    assert lexical.search("password") == []  # the old text is gone
    assert ids(lexical.search("badges")) == [5]


def test_document_frequencies_count_chunks_containing_each_term(lexical) -> None:
    # "leav" occurs in chunks 1 (body + heading), 2 (heading) and 7 (body).
    assert lexical.document_frequencies(["leav", "laptop", "zebra"]) == {"leav": 3, "laptop": 1, "zebra": 0}
    assert lexical.chunk_count() == len(ENTRIES)


def test_clear_empties_the_index(lexical) -> None:
    lexical.clear()
    assert lexical.chunk_count() == 0
    assert lexical.search("annual leave") == []


# -- the BM25 formula --------------------------------------------------------------------------
def test_bm25_score_matches_a_hand_calculation() -> None:
    """Three one-field documents; score of 'cat' against the first, computed by hand."""
    retriever = BM25Retriever(FieldWeights(text=1.0, heading=1.0, title=1.0))
    retriever.add(
        [
            IndexEntry(1, 1, 1, "cat cat dog"),      # tf(cat) = 2, |d| = 3
            IndexEntry(2, 2, 1, "dog bird fish snake"),  # |d| = 4
            IndexEntry(3, 3, 1, "bird fish"),        # |d| = 2
        ]
    )
    n, df, tf, length, average = 3, 1, 2, 3, (3 + 4 + 2) / 3
    idf = math.log((n - df + 0.5) / (df + 0.5))
    expected = idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / average))
    (hit,) = retriever.search("cat")
    assert hit.chunk_id == 1
    assert hit.score == pytest.approx(expected, rel=1e-12)
    assert expected == pytest.approx(0.7024, abs=1e-4)  # ln(5/3) * 2 * 2.2 / 3.2


def test_idf_is_floored_for_terms_in_most_chunks() -> None:
    assert bm25_idf(10, 1) == pytest.approx(math.log(9.5 / 1.5))
    assert bm25_idf(10, 9) == 1e-6  # the raw value would be negative
    assert bm25_idf(10, 5) == 1e-6  # ... or exactly zero


def test_longer_chunks_are_penalised_for_the_same_term_frequency() -> None:
    retriever = BM25Retriever()
    retriever.add(
        [
            IndexEntry(1, 1, 1, "refund policy"),
            IndexEntry(2, 2, 1, "refund policy " + "padding " * 40),
            IndexEntry(3, 3, 1, "opening hours"),
            IndexEntry(4, 4, 1, "password length"),
            IndexEntry(5, 5, 1, "expense claims"),
        ]
    )
    short, long = retriever.search("refund")
    assert (short.chunk_id, long.chunk_id) == (1, 2)
    assert short.score > long.score


@needs_fts5
def test_pure_python_bm25_reproduces_fts5_scores(tmp_path) -> None:
    """Same analysis, same formula: both retrievers must agree on ranking *and* scores."""
    python, fts5 = BM25Retriever(), make_retriever("fts5", tmp_path)
    python.add(ENTRIES)
    fts5.add(ENTRIES)
    for query in ["annual leave", "lost or stolen laptop report", "hotel night breakfast limit", "policy", "car mile claim work"]:
        expected, actual = python.search(query, top_k=10), fts5.search(query, top_k=10)
        assert ids(actual) == ids(expected), query
        assert [hit.score for hit in actual] == pytest.approx([hit.score for hit in expected], rel=1e-6), query


@needs_fts5
def test_both_retrievers_agree_on_the_sample_corpus(seeded: Container) -> None:
    with seeded.session_factory() as session:
        rows = session.execute(select(Chunk, Document).join(Document, Chunk.document_id == Document.id)).all()
    python = BM25Retriever()
    python.add([index_entry(chunk, document) for chunk, document in rows])
    assert isinstance(seeded.retriever, Fts5Retriever)
    assert python.chunk_count() == seeded.lexical.chunk_count() > 100
    for query in [
        "How many days of annual leave do I get?",
        "What is the late cancellation fee?",
        "lost laptop",
        "How long are adult clinical records kept?",
        "guest wifi password",
    ]:
        expected, actual = python.search(query, top_k=6), seeded.retriever.search(query, top_k=6)
        assert ids(actual) == ids(expected), query
        assert [hit.score for hit in actual] == pytest.approx([hit.score for hit in expected], rel=1e-6), query


# -- choosing and synchronising the index ------------------------------------------------------
def test_build_lexical_retriever_prefers_fts5_and_falls_back(tmp_path) -> None:
    engine = make_engine(f"sqlite:///{(tmp_path / 'choose.db').as_posix()}")
    assert isinstance(build_lexical_retriever("bm25", engine), BM25Retriever)
    assert isinstance(build_lexical_retriever("auto", engine), Fts5Retriever if FTS5 else BM25Retriever)


def test_sync_index_rebuilds_an_in_memory_index_from_the_database(seeded: Container) -> None:
    fresh = BM25Retriever()
    indexed = sync_index(fresh, seeded.session_factory)
    assert indexed == fresh.chunk_count() == seeded.lexical.chunk_count()
    # The persistent index is already in step with the table, so nothing is rebuilt.
    assert sync_index(seeded.retriever, seeded.session_factory) == 0


# -- vector retrieval (fake embedder; no embedding provider is integrated) -------------------
VOCABULARY = ["leave", "sick", "car", "hotel", "password", "laptop"]


def test_cosine_similarity() -> None:
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([3, 4], [6, 8]) == pytest.approx(1.0)  # magnitude does not matter
    assert cosine_similarity([0, 0], [1, 1]) == 0.0
    with pytest.raises(ValueError):
        cosine_similarity([1, 2, 3], [1, 2])


def test_cosine_retriever_ranks_by_similarity_to_the_query_vector() -> None:
    retriever = CosineRetriever(KeywordEmbedder(VOCABULARY))
    retriever.add(ENTRIES)
    assert isinstance(retriever, Retriever)
    hits = retriever.search("I lost my laptop", top_k=3)
    assert ids(hits)[0] == 6
    assert hits[0].score == pytest.approx(1.0)
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)
    # Chunks with no similarity at all are not returned.
    assert ids(retriever.search("hotel")) == [4]


def test_cosine_retriever_embeds_title_and_heading_with_the_text() -> None:
    embedder = KeywordEmbedder(["driving"])
    retriever = CosineRetriever(embedder)
    retriever.add(ENTRIES)
    assert ids(retriever.search("driving")) == [3]  # "Driving" appears only in the heading of chunk 3


def test_cosine_retriever_scope_removal_and_threshold() -> None:
    retriever = CosineRetriever(KeywordEmbedder(VOCABULARY), min_similarity=0.9)
    retriever.add(ENTRIES)
    assert ids(retriever.search("leave", collection_ids=[200])) == [7]
    retriever.remove_document(10)
    assert 1 not in ids(retriever.search("leave"))
    assert retriever.search("leave sick car hotel password laptop") == []  # nothing is 0.9 similar to everything
    retriever.clear()
    assert retriever.search("leave") == []


def test_cosine_retriever_rejects_a_misbehaving_embedder() -> None:
    class Short:
        def embed(self, texts):
            return [[1.0]]

    with pytest.raises(ValueError, match="different number"):
        CosineRetriever(Short()).add(ENTRIES)


# -- hybrid ------------------------------------------------------------------------------------
class Scripted:
    """A retriever that returns a fixed ranking."""

    def __init__(self, name: str, ranking: list[int]) -> None:
        self.name = self.label = name
        self.ranking = ranking
        self.added: list[IndexEntry] = []
        self.removed: list[int] = []
        self.cleared = False

    def add(self, entries):
        self.added.extend(entries)

    def remove_document(self, document_id):
        self.removed.append(document_id)

    def clear(self):
        self.cleared = True

    def search(self, query, *, top_k=6, collection_ids=None):
        from sourcewise.retrieval import SearchHit

        return [SearchHit(chunk_id, 1.0 / rank) for rank, chunk_id in enumerate(self.ranking[:top_k], start=1)]


def test_reciprocal_rank_fusion_rewards_agreement() -> None:
    lexical, vector = Scripted("lexical", [1, 2, 3]), Scripted("vector", [3, 1, 4])
    fusion = ReciprocalRankFusion([lexical, vector], k=60)
    hits = fusion.search("anything", top_k=4)
    # 1 is ranked 1st and 2nd, 3 is ranked 3rd and 1st, 2 and 4 are each found by one retriever only.
    assert ids(hits) == [1, 3, 2, 4]
    assert hits[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert hits[1].score == pytest.approx(1 / 63 + 1 / 61)
    assert fusion.label == "Hybrid RRF (lexical + vector)"
    assert isinstance(fusion, Retriever)


def test_reciprocal_rank_fusion_forwards_index_changes() -> None:
    first, second = Scripted("a", []), Scripted("b", [])
    fusion = ReciprocalRankFusion([first, second])
    fusion.add(ENTRIES[:2])
    fusion.remove_document(10)
    fusion.clear()
    for retriever in (first, second):
        assert retriever.added == ENTRIES[:2] and retriever.removed == [10] and retriever.cleared
    with pytest.raises(ValueError):
        ReciprocalRankFusion([])


def test_lexical_and_vector_retrievers_fuse_end_to_end() -> None:
    lexical, vector = BM25Retriever(), CosineRetriever(KeywordEmbedder(VOCABULARY))
    fusion = ReciprocalRankFusion([lexical, vector])
    fusion.add(ENTRIES)
    assert ids(fusion.search("lost laptop", top_k=3))[0] == 6


# -- the plug-in point: an extra retriever inside the running application ----------------------
class ConceptEmbedder:
    """A toy embedding model: one dimension per concept, so synonyms land on the same axis."""

    CONCEPTS = (("vacation", "holiday", "annual leave"), ("password", "passphrase"), ("expense", "claim"))

    def embed(self, texts):
        return [[float(sum(text.lower().count(word) for word in words)) for words in self.CONCEPTS] for text in texts]


def test_an_extra_retriever_is_fused_into_the_running_application(tmp_path) -> None:
    """What the README describes: pass a vector retriever to build_container and everything else follows."""
    from sourcewise.seed import _seed_users

    settings = make_settings(tmp_path / "data")
    vector = CosineRetriever(ConceptEmbedder(), min_similarity=0.5)
    container = build_container(settings, extra_retrievers=[vector])
    try:
        with container.session_factory() as session:
            _seed_users(session)
        admin = sign_in(TestClient(create_app(settings, container=container)), ADMIN)
        label = f"Hybrid RRF ({container.lexical.label} + Cosine similarity (embeddings))"
        assert admin.get("/api/meta").json()["retriever"] == {"name": "rrf", "label": label}

        # Ingestion indexes every chunk in both retrievers.
        collection = admin.post("/api/collections", json={"name": "People", "description": ""}).json()
        handbook = (PROJECT_ROOT / "corpus" / "people" / "employee-handbook.md").read_bytes()
        upload = admin.post("/api/documents", files={"file": ("employee-handbook.md", handbook)}, data={"collection_id": str(collection["id"])})
        document = admin.get(f"/api/documents/{upload.json()['id']}").json()
        assert document["status"] == "ready" and label in document["stages"][-1]["detail"]
        assert container.lexical.chunk_count() == vector.chunk_count() == document["chunk_count"] > 10

        # The handbook never says "vacation": BM25 alone finds nothing, the fused retriever finds the leave sections.
        assert container.lexical.search("vacation") == []
        hits = container.retriever.search("vacation", top_k=3)
        assert hits
        with container.session_factory() as session:
            for hit in hits:
                chunk = session.get(Chunk, hit.chunk_id)
                assert any(word in f"{chunk.heading_path} {chunk.text}".lower() for word in ("holiday", "annual leave"))

        # Chat runs on the fused ranking.
        conversation = admin.post("/api/conversations", json={}).json()
        answer = admin.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"content": "How many days of annual leave do full-time employees get?", "stream": False},
        ).json()
        assert not answer["abstained"] and "25 days" in answer["content"]
        assert answer["citations"][0]["heading_path"] == ["Leave", "Annual leave"]
    finally:
        container.close()

    # After a restart an in-memory vector index is rebuilt from the database...
    restarted_vector = CosineRetriever(ConceptEmbedder(), min_similarity=0.5)
    restarted = build_container(settings, extra_retrievers=[restarted_vector])
    try:
        assert restarted_vector.chunk_count() == restarted.lexical.chunk_count() == document["chunk_count"]
        # ...and deleting a document removes it from every retriever.
        admin = sign_in(TestClient(create_app(settings, container=restarted)), ADMIN)
        assert admin.delete(f"/api/documents/{document['id']}").status_code == 204
        assert restarted_vector.chunk_count() == restarted.lexical.chunk_count() == 0
    finally:
        restarted.close()
