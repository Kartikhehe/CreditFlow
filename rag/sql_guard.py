"""AST validation for generated SQL.

This is deliberately not a keyword blocklist. A blocklist for "drop" or
"delete" is defeated by a comment, an unusual amount of whitespace, a string
literal or a nested statement, and it also rejects legitimate queries that
happen to contain the word in a value. So the statement is parsed into a syntax
tree and the tree is what gets checked: the root must be a select, no mutating
node may appear anywhere beneath it, and every table reference must resolve
either to a CTE defined in the same statement or to a name on the allowlist.

The module holds no API client and no database connection, so the guardrail can
be exercised directly by the test suite without either.
"""
from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

DIALECT = "duckdb"
MAX_ROWS = 500

ALLOWED_TABLES = frozenset(
    {
        "fct_loan",
        "fct_application_funnel",
        "dim_borrower",
        "dim_geography",
        "dim_date",
    }
)

# Node types that write, define or destroy. Checked structurally, so a mutating
# statement nested inside a subquery is caught along with a top-level one.
FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Merge,
    exp.Command,
)

PERMITTED_ROOTS = (exp.Select, exp.Subquery, exp.Union, exp.With)

LIMIT_PATTERN = re.compile(r"\blimit\b", re.IGNORECASE)


class UnsafeQueryError(ValueError):
    """Raised when generated SQL fails validation."""


def _qualified_name(table: exp.Table) -> str:
    return f"{table.db}.{table.name}" if table.db else table.name


def validate(sql: str) -> str:
    """Return SQL that is safe to execute, with a row limit, or raise."""
    if not sql or not sql.strip():
        raise UnsafeQueryError("generated SQL was empty")

    try:
        parsed = sqlglot.parse_one(sql, read=DIALECT)
    except Exception as error:
        raise UnsafeQueryError(f"generated SQL did not parse: {error}") from error

    if parsed is None:
        raise UnsafeQueryError("generated SQL was empty")

    if not isinstance(parsed, PERMITTED_ROOTS):
        raise UnsafeQueryError(
            f"only SELECT statements are permitted, received {type(parsed).__name__}"
        )

    for node in parsed.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeQueryError(
                f"statement contains a forbidden node type: {type(node).__name__}"
            )

    # A CTE name is a valid table reference within its own statement, so those
    # names are collected first and treated as in scope rather than checked
    # against the allowlist of physical tables.
    cte_names = {cte.alias_or_name for cte in parsed.find_all(exp.CTE)}

    for table in parsed.find_all(exp.Table):
        if table.name in cte_names:
            continue
        if table.name not in ALLOWED_TABLES:
            raise UnsafeQueryError(
                f"table is not on the allowlist: {_qualified_name(table)}"
            )

    if not LIMIT_PATTERN.search(sql):
        return f"{sql.rstrip().rstrip(';')}\nlimit {MAX_ROWS}"
    return sql
