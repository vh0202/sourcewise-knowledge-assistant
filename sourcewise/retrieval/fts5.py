"""BM25 retrieval backed by SQLite's FTS5 full-text index.

The index stores the output of ``analyze()`` (stop-words removed, Porter-stemmed) rather than
raw text, and FTS5 is configured with its plain ``unicode61`` tokenizer. Query terms go
through the same ``analyze()``, so the engine sees identical terms on both sides and its
built-in ``bm25()`` ranking does the scoring. Field weights are passed to ``bm25()``.

The index lives in the same database file as the rest of the data, so there is nothing to
rebuild at start-up and nothing extra to back up.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence

from sqlalchemy import Engine, text
from sqlalchemy.exc import DatabaseError

from ..text.analyzer import analyze, query_terms
from .base import DEFAULT_WEIGHTS, FieldWeights, IndexEntry, SearchHit

_TABLE = "chunk_fts"
_VOCAB = "chunk_fts_vocab"


def fts5_available(engine: Engine) -> bool:
    """True if this Python's SQLite was compiled with the FTS5 extension."""
    try:
        with engine.connect() as connection:
            connection.execute(text("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(x)"))
            connection.execute(text("DROP TABLE temp.fts5_probe"))
            connection.rollback()
        return True
    except DatabaseError:
        return False


class Fts5Retriever:
    name = "fts5"
    label = "BM25 (SQLite FTS5)"

    def __init__(self, engine: Engine, weights: FieldWeights = DEFAULT_WEIGHTS) -> None:
        self._engine = engine
        self._weights = weights
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS {_TABLE} USING fts5("
                    "body, heading, title, document_id UNINDEXED, collection_id UNINDEXED, "
                    "tokenize = 'unicode61')"
                )
            )
            connection.execute(
                text(f"CREATE VIRTUAL TABLE IF NOT EXISTS {_VOCAB} USING fts5vocab({_TABLE}, 'row')")
            )

    # -- indexing --------------------------------------------------------------------------
    def add(self, entries: Sequence[IndexEntry]) -> None:
        if not entries:
            return
        rows = [
            {
                "rowid": entry.chunk_id,
                "body": " ".join(analyze(entry.text)),
                "heading": " ".join(analyze(entry.heading)),
                "title": " ".join(analyze(entry.title)),
                "document_id": entry.document_id,
                "collection_id": entry.collection_id,
            }
            for entry in entries
        ]
        with self._engine.begin() as connection:
            connection.execute(
                text(f"DELETE FROM {_TABLE} WHERE rowid = :rowid"), [{"rowid": row["rowid"]} for row in rows]
            )
            connection.execute(
                text(
                    f"INSERT INTO {_TABLE} (rowid, body, heading, title, document_id, collection_id) "
                    "VALUES (:rowid, :body, :heading, :title, :document_id, :collection_id)"
                ),
                rows,
            )

    def remove_document(self, document_id: int) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(f"DELETE FROM {_TABLE} WHERE document_id = :document_id"), {"document_id": document_id}
            )

    def clear(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {_TABLE}"))

    # -- statistics ------------------------------------------------------------------------
    def chunk_count(self) -> int:
        with self._engine.connect() as connection:
            return int(connection.execute(text(f"SELECT count(*) FROM {_TABLE}")).scalar_one())

    def document_frequencies(self, terms: Iterable[str]) -> dict[str, int]:
        wanted = list(dict.fromkeys(terms))
        frequencies = dict.fromkeys(wanted, 0)
        if not wanted:
            return frequencies
        placeholders = ", ".join(f":t{i}" for i in range(len(wanted)))
        parameters = {f"t{i}": term for i, term in enumerate(wanted)}
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(f"SELECT term, doc FROM {_VOCAB} WHERE term IN ({placeholders})"), parameters
            )
            for term, count in rows:
                frequencies[term] = int(count)
        return frequencies

    # -- search ----------------------------------------------------------------------------
    def search(
        self, query: str, *, top_k: int = 6, collection_ids: Collection[int] | None = None
    ) -> list[SearchHit]:
        terms = query_terms(query)
        if not terms:
            return []
        if collection_ids is not None and not collection_ids:
            return []
        # Terms are [a-z0-9]+ by construction; quoting keeps FTS5 from reading "or"/"and"/"not"
        # or a leading digit as query syntax.
        match = " OR ".join(f'"{term}"' for term in terms)
        scope = ""
        if collection_ids is not None:
            scope = f" AND collection_id IN ({', '.join(str(int(cid)) for cid in collection_ids)})"
        statement = text(
            f"SELECT rowid, bm25({_TABLE}, :w_text, :w_heading, :w_title) AS rank "
            f"FROM {_TABLE} WHERE {_TABLE} MATCH :match{scope} ORDER BY rank, rowid LIMIT :top_k"
        )
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement,
                {
                    "match": match,
                    "top_k": top_k,
                    "w_text": self._weights.text,
                    "w_heading": self._weights.heading,
                    "w_title": self._weights.title,
                },
            ).all()
        # FTS5 reports BM25 as a negative number (more negative = better); flip the sign.
        return [SearchHit(int(rowid), -float(rank)) for rowid, rank in rows]
