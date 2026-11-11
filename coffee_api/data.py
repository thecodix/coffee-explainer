"""Database access as the read-only role: the schema prompt (from view COMMENTs), queries and retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from explainer_data.embed import Embedder, make_embedder, search

SCHEMA_QUERY = """
SELECT c.relname AS view, obj_description(c.oid) AS view_comment,
       a.attname AS col, format_type(a.atttypid, a.atttypmod) AS type, col_description(c.oid, a.attnum) AS comment
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE n.nspname = 'api' AND c.relkind IN ('v', 'm', 'r')
ORDER BY c.relname, a.attnum
"""


@dataclass(frozen=True)
class SchemaInfo:
    views: frozenset[str]
    prompt: str


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class Data:
    def __init__(self, database_url: str, embedding_model: str) -> None:
        # Neon suspends idle compute and drops idle connections: test each connection before handing it out,
        # and retire idle ones well before Neon does.
        self.pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={"autocommit": True},
            check=ConnectionPool.check_connection,
            max_idle=120,
        )
        self._embedding_model = embedding_model
        self._embedder: Embedder | None = None
        self._schema: SchemaInfo | None = None
        self._version: str | None = None

    def open(self) -> None:
        self.pool.open(wait=True, timeout=30)

    def close(self) -> None:
        self.pool.close()

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:  # loaded on first use: ~220 MB for the default model
            self._embedder = make_embedder(self._embedding_model)
        return self._embedder

    def schema(self) -> SchemaInfo:
        if self._schema is None:
            with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(SCHEMA_QUERY).fetchall()
            lines, views, current = [], set(), None
            for row in rows:
                if row["view"] != current:
                    current = row["view"]
                    views.add(current)
                    lines.append(f"\napi.{current} -- {row['view_comment'] or ''}")
                note = f" -- {row['comment']}" if row["comment"] else ""
                lines.append(f"  {row['col']} {row['type']}{note}")
            self._schema = SchemaInfo(frozenset(views), "\n".join(lines).strip())
        return self._schema

    def query(self, sql: str) -> tuple[list[str], list[list[Any]]]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql)
            columns = [d.name for d in cur.description or []]
            return columns, [[_plain(v) for v in row] for row in cur.fetchall()]

    def retrieve(self, question: str, k: int) -> list[dict]:
        with self.pool.connection() as conn:
            hits = search(conn, self.embedder, question, k=k * 3)
        return prefer_coffee(question, hits, k)

    def data_version(self) -> str | None:
        if self._version is None:
            self._version = self.meta().get("data_version")
        return self._version

    def meta(self) -> dict:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute("SELECT * FROM api.data_coverage").fetchone()
        return {k: _plain(v) for k, v in (row or {}).items()}


NON_COFFEE_HINTS = re.compile(
    r"capsul|c[aá]psul|pod|equipment|grinder|dripper|kettle|filter|merch|mug|gift|subscription|tea|chocolate",
    re.IGNORECASE,
)
NON_COFFEE_KINDS = {"capsules", "equipment", "merch", "other_drink", "other", "pack"}


def prefer_coffee(question: str, hits: list[dict], k: int) -> list[dict]:
    """Drop non-coffee product cards unless the question asks about them; keep order, return k."""
    if NON_COFFEE_HINTS.search(question):
        return hits[:k]
    kept = [h for h in hits if (h.get("metadata") or {}).get("product_kind") not in NON_COFFEE_KINDS]
    return kept[:k]


def is_query_error(error: Exception) -> bool:
    return isinstance(error, psycopg.Error)
