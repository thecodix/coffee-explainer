"""Connection and migrations."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parent.parent / "db" / "migrations"


def connect(url: str | None = None) -> psycopg.Connection:
    """``DATABASE_URL`` (Neon gives one per branch), or the standard PG* variables when unset."""
    return psycopg.connect(url or os.environ.get("DATABASE_URL", ""))


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply pending ``db/migrations/*.sql`` in order, each in its own transaction. Returns what ran."""
    with conn.transaction():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS public.schema_migrations "
            "(filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
    done = {row[0] for row in conn.execute("SELECT filename FROM public.schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO public.schema_migrations (filename) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied
