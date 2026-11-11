"""Command line: ``python -m explainer_data <command>``.

migrate                      apply db/migrations/*.sql
load --source PATH_OR_URL    replace the data with one export (fixtures folder, export folder or /data URL)
embed [--model NAME|hash]    embed documents that are new or changed
refresh --source ...         migrate + load + embed, the usual run after publishing
create-reader NAME           login role for the API (password from READER_PASSWORD), read-only, 5 s timeout
search "question"            try retrieval from the terminal
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

from psycopg import sql

from .db import connect, migrate
from .embed import DEFAULT_MODEL, embed_pending, make_embedder, search
from .load import load
from .source import read_export


def _create_reader(conn, name: str) -> None:
    password = os.environ.get("READER_PASSWORD")
    if not password:
        sys.exit("Set READER_PASSWORD for the new role.")
    role = sql.Identifier(name)
    with conn.transaction():
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))
        conn.execute(sql.SQL("GRANT explainer_reader TO {}").format(role))
        conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(role))
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '5s'").format(role))
        # public: where the pgvector type lives, so the API can register it
        conn.execute(sql.SQL("ALTER ROLE {} SET search_path = api, rag, public").format(role))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="explainer_data")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    for name in ("load", "refresh"):
        p = sub.add_parser(name)
        p.add_argument("--source", required=True)
        if name == "refresh":
            p.add_argument("--model", default=DEFAULT_MODEL)
    p = sub.add_parser("embed")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p = sub.add_parser("create-reader")
    p.add_argument("name")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("-k", type=int, default=5)
    args = parser.parse_args(argv)

    with connect() as conn:
        if args.command in ("migrate", "refresh"):
            print("migrations applied:", migrate(conn) or "none pending")
        if args.command in ("load", "refresh"):
            print(json.dumps(asdict(load(conn, read_export(args.source))), indent=2))
        if args.command in ("embed", "refresh"):
            print("embedded:", embed_pending(conn, make_embedder(args.model)))
        if args.command == "create-reader":
            _create_reader(conn, args.name)
            print(f"role {args.name} ready (member of explainer_reader, read-only)")
        if args.command == "search":
            for hit in search(conn, make_embedder(args.model), args.query, k=args.k):
                print(f"{hit['score']:.3f}  [{hit['kind']}] {hit['title']} — {hit['body'][:120]}")


if __name__ == "__main__":
    main()
