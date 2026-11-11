"""Embed the documents that need it.

Default model: a small multilingual sentence model run locally through fastembed (ONNX, CPU, 384 dims), since
Groq serves no embedding models. Product names and certifications are often in Spanish while visitors ask in
English, hence multilingual. The API must embed queries with the SAME model; it is recorded per document.

``hash`` is a deterministic stand-in for tests and offline runs: it only checks the plumbing, not meaning.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from typing import Protocol

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

DIMENSIONS = 384
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]: ...


class FastEmbedder:
    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        from fastembed import TextEmbedding  # imported lazily: heavy, and not needed for the hash embedder

        self.name = model
        self._model = TextEmbedding(model_name=model)

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        return [np.asarray(v, dtype=np.float32) for v in self._model.embed(list(texts))]


class HashEmbedder:
    name = "hash-test"

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        out = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")
            vector = np.random.default_rng(seed).standard_normal(DIMENSIONS).astype(np.float32)
            out.append(vector / np.linalg.norm(vector))
        return out


def make_embedder(name: str) -> Embedder:
    return HashEmbedder() if name == "hash" else FastEmbedder(name)


def _batches(rows: list[tuple[str, str]], size: int) -> Iterable[list[tuple[str, str]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def embed_pending(conn: psycopg.Connection, embedder: Embedder, batch_size: int = 128) -> int:
    """Embed documents with no embedding or one from another model. Returns how many were embedded."""
    register_vector(conn)
    rows = conn.execute(
        "SELECT doc_id, title || E'\\n' || body FROM rag.documents "
        "WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %s ORDER BY doc_id",
        (embedder.name,),
    ).fetchall()
    done = 0
    for batch in _batches(rows, batch_size):
        vectors = embedder.embed([text for _, text in batch])
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(
                "UPDATE rag.documents SET embedding = %s, embedding_model = %s WHERE doc_id = %s",
                [(vector, embedder.name, doc_id) for (doc_id, _), vector in zip(batch, vectors, strict=True)],
            )
        done += len(batch)
    return done


def search(
    conn: psycopg.Connection, embedder: Embedder, query: str, k: int = 5, kinds: Sequence[str] | None = None
) -> list[dict]:
    """Nearest documents by cosine distance: the retrieval step the API will call."""
    register_vector(conn)
    vector = embedder.embed([query])[0]
    sql = (
        "SELECT doc_id, kind, title, body, url, metadata, 1 - (embedding <=> %s) AS score FROM rag.documents "
        "WHERE embedding_model = %s" + (" AND kind = ANY(%s)" if kinds else "") + " ORDER BY embedding <=> %s LIMIT %s"
    )
    params: tuple = (vector, embedder.name, list(kinds), vector, k) if kinds else (vector, embedder.name, vector, k)
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        return cur.execute(sql, params).fetchall()
