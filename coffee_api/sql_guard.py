"""Validate model-written SQL before it runs.

Defence in depth: the database role is already read-only, cannot see ``obs`` and has a statement timeout. This
check adds what a role cannot express: one SELECT only, only the curated ``api`` views, no dangerous functions,
and a row cap.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp


class UnsafeSQL(ValueError):
    pass


FORBIDDEN_FUNCTIONS = {
    "pg_sleep",
    "pg_sleep_for",
    "pg_sleep_until",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "lo_get",
    "dblink",
    "dblink_exec",
    "set_config",
    "current_setting",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "query_to_xml",
    "copy",
    "txid_current",
    "nextval",
    "setval",
}


def _cte_names(tree: exp.Expression) -> set[str]:
    return {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}


def validate(sql: str, allowed_views: set[str], row_limit: int) -> str:
    """Return the SQL to run (with a LIMIT) or raise ``UnsafeSQL`` with the reason."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as error:
        raise UnsafeSQL(f"does not parse: {error.errors[0]['description'] if error.errors else error}") from None
    if len(statements) != 1:
        raise UnsafeSQL("exactly one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise UnsafeSQL(f"only SELECT is allowed, got {tree.key.upper()}")
    for node in tree.walk():
        if isinstance(node, exp.DML | exp.DDL | exp.Command | exp.Into | exp.Lock):
            raise UnsafeSQL(f"{node.key.upper()} is not allowed")

    ctes = _cte_names(tree)
    for table in tree.find_all(exp.Table):
        name, schema = table.name.lower(), (table.db or "").lower()
        if not schema and name in ctes:
            continue
        if schema not in ("", "api") or name not in allowed_views:
            raise UnsafeSQL(f"table {table.sql()} is not one of the api views")

    for func in tree.find_all(exp.Func):
        name = (func.sql_name() if not isinstance(func, exp.Anonymous) else func.name).lower()
        if name in FORBIDDEN_FUNCTIONS:
            raise UnsafeSQL(f"function {name} is not allowed")

    limit = tree.args.get("limit")
    if limit is None or not isinstance(limit.expression, exp.Literal) or int(limit.expression.this) > row_limit:
        tree = tree.limit(row_limit, copy=True)
    return tree.sql(dialect="postgres")
