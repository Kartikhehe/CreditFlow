"""Tests for the text-to-SQL validator.

The mutating-statement cases are written so a keyword blocklist would fail
them: the forbidden operation is hidden in a comment, a string literal, or a
nested position where a substring scan either misses it or fires on a query
that is actually safe. Parsing is what makes all four groups behave correctly.
"""
from __future__ import annotations

import pytest

from rag.sql_guard import ALLOWED_TABLES, MAX_ROWS, UnsafeQueryError, validate

SAFE_QUERY = """
select
    grade,
    count(*) as loans
from marts.fct_loan
where is_terminal
group by grade
limit 10
"""

MUTATING_STATEMENTS = [
    "drop table marts.fct_loan",
    "delete from marts.fct_loan where is_default = 1",
    "update marts.fct_loan set is_default = 0",
    "insert into marts.fct_loan (loan_id) values ('x')",
    "create table marts.scratch as select * from marts.fct_loan",
    "alter table marts.fct_loan add column injected int",
]

OFF_ALLOWLIST_TABLES = [
    "select * from raw.accepted",
    "select * from marts.internal_pricing",
    "select * from information_schema.tables",
    "select * from staging.stg_loans",
]


def test_a_safe_query_passes_unchanged():
    assert validate(SAFE_QUERY).strip() == SAFE_QUERY.strip()


@pytest.mark.parametrize("statement", MUTATING_STATEMENTS)
def test_mutating_statements_are_rejected(statement):
    with pytest.raises(UnsafeQueryError):
        validate(statement)


@pytest.mark.parametrize("statement", OFF_ALLOWLIST_TABLES)
def test_off_allowlist_tables_are_rejected(statement):
    with pytest.raises(UnsafeQueryError, match="allowlist"):
        validate(statement)


def test_every_allowlisted_table_is_accepted():
    for table in sorted(ALLOWED_TABLES):
        assert validate(f"select * from marts.{table} limit 1")


def test_a_mutating_statement_nested_in_a_subquery_is_rejected():
    """A top-level-only check would miss this."""
    with pytest.raises(UnsafeQueryError):
        validate(
            "select * from (delete from marts.fct_loan returning loan_id) as removed"
        )


def test_an_off_allowlist_table_in_a_subquery_is_rejected():
    with pytest.raises(UnsafeQueryError, match="allowlist"):
        validate(
            """
            select count(*)
            from (
                select loan_id from raw.accepted
            ) as source
            """
        )


def test_an_off_allowlist_table_in_a_join_is_rejected():
    with pytest.raises(UnsafeQueryError, match="allowlist"):
        validate(
            """
            select fct.loan_id
            from marts.fct_loan as fct
            join raw.rejected as declined
                on declined.state = fct.geography_key
            limit 5
            """
        )


def test_cte_names_are_treated_as_valid_references():
    validated = validate(
        """
        with terminal_loans as (
            select
                grade,
                is_default
            from marts.fct_loan
            where is_terminal
        )
        select
            grade,
            avg(cast(is_default as double)) as default_rate
        from terminal_loans
        group by grade
        limit 10
        """
    )
    assert "terminal_loans" in validated


def test_a_cte_may_not_smuggle_in_an_off_allowlist_table():
    with pytest.raises(UnsafeQueryError, match="allowlist"):
        validate(
            """
            with source as (
                select * from raw.accepted
            )
            select count(*) from source
            """
        )


def test_a_limit_is_injected_when_absent():
    validated = validate("select loan_id from marts.fct_loan")
    assert f"limit {MAX_ROWS}" in validated.lower()


def test_an_existing_limit_is_left_alone():
    validated = validate("select loan_id from marts.fct_loan limit 7")
    assert "limit 7" in validated.lower()
    assert str(MAX_ROWS) not in validated


def test_a_trailing_semicolon_does_not_break_limit_injection():
    validated = validate("select loan_id from marts.fct_loan;")
    assert validated.rstrip().lower().endswith(f"limit {MAX_ROWS}")


def test_a_forbidden_keyword_inside_a_string_literal_is_not_a_rejection():
    """A blocklist scanning for 'delete' would reject this valid query."""
    validated = validate(
        """
        select purpose
        from marts.fct_loan
        where purpose = 'delete drop truncate'
        limit 5
        """
    )
    assert validated


def test_a_forbidden_keyword_inside_a_comment_is_not_a_rejection():
    validated = validate(
        """
        -- do not drop this table
        select loan_id
        from marts.fct_loan
        limit 5
        """
    )
    assert validated


def test_unparseable_input_is_rejected():
    with pytest.raises(UnsafeQueryError, match="parse"):
        validate("this is not sql at all ((((")


def test_empty_input_is_rejected():
    with pytest.raises(UnsafeQueryError):
        validate("")


def test_a_union_across_allowlisted_tables_is_accepted():
    validated = validate(
        """
        select
            loan_id,
            grade
        from marts.fct_loan
        where issue_year = 2015

        union all

        select
            loan_id,
            grade
        from marts.fct_loan
        where issue_year = 2016
        """
    )
    assert validated


def test_a_union_reaching_an_off_allowlist_table_is_rejected():
    with pytest.raises(UnsafeQueryError, match="allowlist"):
        validate(
            """
            select loan_id from marts.fct_loan
            union all
            select id from raw.accepted
            """
        )
