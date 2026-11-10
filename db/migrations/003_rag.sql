-- Retrieval corpus. Documents are rebuilt from obs.* on every load; an embedding is kept while the
-- document's content_hash and the embedding model stay the same, so a reload only re-embeds what changed.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS rag;

CREATE TABLE rag.documents (
    doc_id          text PRIMARY KEY,           -- '<kind>:<ref_id>'
    kind            text NOT NULL,              -- product | roaster | region | about
    ref_id          text NOT NULL,
    title           text NOT NULL,
    body            text NOT NULL,
    url             text,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    content_hash    text NOT NULL,
    embedding       vector(384),
    embedding_model text,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX documents_kind_idx ON rag.documents (kind);
CREATE INDEX documents_embedding_idx ON rag.documents USING hnsw (embedding vector_cosine_ops);
