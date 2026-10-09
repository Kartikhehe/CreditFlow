"""Execution-accuracy benchmark for the text-to-SQL agent.

Correctness is judged by comparing result sets, not query strings. Two analysts
answering the same question will write different SQL, and a string comparison
would score a correct answer as a failure for using a different join order.

Three cases are designed to fail. One is ambiguous, one asks for data the
warehouse does not hold, and one can only be answered by a table that is off
the allowlist. A benchmark of answerable questions alone measures fluency; a
guardrail is only worth anything if refusal is measured too, so those three
score as correct when the agent declines and as incorrect when it invents an
answer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import duckdb
import pandas as pd

from rag.sql_guard import UnsafeQueryError
from rag.text_to_sql import ask
from src.paths import DUCKDB_PATH, GOVERNANCE, ensure_results_dirs

# A 429 or 503 says nothing about whether the agent wrote correct SQL, so
# transient transport failures are retried with backoff and the run is paced.
#
# Note the free tier also enforces a per-model requests-per-day ceiling, which
# backoff cannot help with: once it is hit, every remaining case fails and the
# reported accuracy is meaningless. The benchmark needs more calls than that
# ceiling allows on one model, so a run that reports a wall of 429s should be
# rerun against a model whose daily quota is unspent rather than read as a
# result.
API_MAX_ATTEMPTS = 3
API_BACKOFF_SECONDS = 15
PACE_SECONDS = 2
TRANSIENT_MARKERS = ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")

COMPARISON_TOLERANCE = 4
ROW_ORDER_SENSITIVE_HINT = "order"


@dataclass(frozen=True)
class GoldCase:
    question: str
    category: str
    sql: str | None = None
    should_refuse: bool = False
    notes: str = field(default="")


GOLD_CASES: list[GoldCase] = [
    # --- simple aggregates ---
    GoldCase(
        question="What is the overall default rate across all terminal loans?",
        category="simple aggregate",
        sql="""
            select round(100.0 * avg(cast(is_default as double)), 2) as default_rate_pct
            from marts.fct_loan
            where is_terminal
        """,
    ),
    GoldCase(
        question="How many funded loans are in the warehouse in total?",
        category="simple aggregate",
        sql="select count(*) as loans from marts.fct_loan",
    ),
    GoldCase(
        question="What is the total funded amount across terminal loans, in dollars?",
        category="simple aggregate",
        sql="""
            select sum(funded_amount) as total_funded
            from marts.fct_loan
            where is_terminal
        """,
    ),
    GoldCase(
        question="What is the average interest rate on terminal loans, rounded to two decimals?",
        category="simple aggregate",
        sql="""
            select round(avg(interest_rate), 2) as avg_interest_rate
            from marts.fct_loan
            where is_terminal
        """,
    ),
    # --- group by ---
    GoldCase(
        question="Show the default rate by loan grade, highest default rate first.",
        category="group by",
        sql="""
            select
                grade,
                round(100.0 * avg(cast(is_default as double)), 2) as default_rate_pct
            from marts.fct_loan
            where is_terminal
            group by grade
            order by default_rate_pct desc
        """,
    ),
    GoldCase(
        question="What is the default rate by loan term in months?",
        category="group by",
        sql="""
            select
                term_months,
                round(100.0 * avg(cast(is_default as double)), 2) as default_rate_pct
            from marts.fct_loan
            where is_terminal
            group by term_months
            order by term_months
        """,
    ),
    GoldCase(
        question="Count terminal loans by loan purpose, most common first.",
        category="group by",
        sql="""
            select
                purpose,
                count(*) as loans
            from marts.fct_loan
            where is_terminal
            group by purpose
            order by loans desc
        """,
    ),
    GoldCase(
        question="What is the average funded amount for each loan grade?",
        category="group by",
        sql="""
            select
                grade,
                round(avg(funded_amount), 2) as avg_funded_amount
            from marts.fct_loan
            where is_terminal
            group by grade
            order by grade
        """,
    ),
    # --- group by with having ---
    GoldCase(
        question="Which five states had the highest default rate among states with at least 5000 terminal loans?",
        category="having",
        sql="""
            select
                geography_key,
                round(100.0 * avg(cast(is_default as double)), 2) as default_rate_pct
            from marts.fct_loan
            where is_terminal
            group by geography_key
            having count(*) >= 5000
            order by default_rate_pct desc
            limit 5
        """,
    ),
    GoldCase(
        question="Which loan purposes have more than 10000 terminal loans, and what is their default rate?",
        category="having",
        sql="""
            select
                purpose,
                count(*) as loans,
                round(100.0 * avg(cast(is_default as double)), 2) as default_rate_pct
            from marts.fct_loan
            where is_terminal
            group by purpose
            having count(*) > 10000
            order by default_rate_pct desc
        """,
    ),
    GoldCase(
        question="Show sub-grades with at least 20000 terminal loans and their average interest rate.",
        category="having",
        sql="""
            select
                sub_grade,
                count(*) as loans,
                round(avg(interest_rate), 2) as avg_interest_rate
            from marts.fct_loan
            where is_terminal
            group by sub_grade
            having count(*) >= 20000
            order by sub_grade
        """,
    ),
    # --- multi-table joins ---
    GoldCase(
        question="What is the default rate by FICO band?",
        category="join",
        sql="""
            select
                borrower.fico_band,
                round(100.0 * avg(cast(fct.is_default as double)), 2) as default_rate_pct
            from marts.fct_loan as fct
            join marts.dim_borrower as borrower
                on borrower.borrower_key = fct.borrower_key
            where fct.is_terminal
            group by borrower.fico_band
            order by borrower.fico_band
        """,
    ),
    GoldCase(
        question="What is the default rate by census region?",
        category="join",
        sql="""
            select
                geography.census_region,
                round(100.0 * avg(cast(fct.is_default as double)), 2) as default_rate_pct
            from marts.fct_loan as fct
            join marts.dim_geography as geography
                on geography.geography_key = fct.geography_key
            where fct.is_terminal
            group by geography.census_region
            order by default_rate_pct desc
        """,
    ),
    GoldCase(
        question="Show the default rate by debt-to-income band and loan grade for terminal loans, for bands with at least 1000 loans.",
        category="join",
        sql="""
            select
                borrower.dti_band,
                fct.grade,
                count(*) as loans,
                round(100.0 * avg(cast(fct.is_default as double)), 2) as default_rate_pct
            from marts.fct_loan as fct
            join marts.dim_borrower as borrower
                on borrower.borrower_key = fct.borrower_key
            where fct.is_terminal
            group by
                borrower.dti_band,
                fct.grade
            having count(*) >= 1000
            order by
                borrower.dti_band,
                fct.grade
        """,
    ),
    GoldCase(
        question="What is the average annual income and default rate for each home ownership status?",
        category="join",
        sql="""
            select
                borrower.home_ownership,
                round(avg(borrower.annual_income), 2) as avg_annual_income,
                round(100.0 * avg(cast(fct.is_default as double)), 2) as default_rate_pct
            from marts.fct_loan as fct
            join marts.dim_borrower as borrower
                on borrower.borrower_key = fct.borrower_key
            where fct.is_terminal
            group by borrower.home_ownership
            order by borrower.home_ownership
        """,
    ),
    GoldCase(
        question="Using the date dimension, what is the default rate for loans originated during the global financial crisis period compared with outside it?",
        category="join",
        sql="""
            select
                dates.is_gfc_period,
                count(*) as loans,
                round(100.0 * avg(cast(fct.is_default as double)), 2) as default_rate_pct
            from marts.fct_loan as fct
            join marts.dim_date as dates
                on dates.date_key = fct.date_key
            where fct.is_terminal
            group by dates.is_gfc_period
            order by dates.is_gfc_period
        """,
    ),
    # --- date filtering ---
    GoldCase(
        question="What was the default rate for loans originated in 2016?",
        category="date filter",
        sql="""
            select round(100.0 * avg(cast(is_default as double)), 2) as default_rate_pct
            from marts.fct_loan
            where is_terminal
              and issue_year = 2016
        """,
    ),
    GoldCase(
        question="Show the number of terminal loans originated each year from 2014 onwards.",
        category="date filter",
        sql="""
            select
                issue_year,
                count(*) as loans
            from marts.fct_loan
            where is_terminal
              and issue_year >= 2014
            group by issue_year
            order by issue_year
        """,
    ),
    GoldCase(
        question="What is the default rate for each vintage quarter in 2015?",
        category="date filter",
        sql="""
            select
                vintage_quarter,
                round(100.0 * avg(cast(is_default as double)), 2) as default_rate_pct
            from marts.fct_loan
            where is_terminal
              and issue_year = 2015
            group by vintage_quarter
            order by vintage_quarter
        """,
    ),
    GoldCase(
        question="What was the approval rate in the application funnel for applications in 2015?",
        category="date filter",
        sql="""
            select
                round(
                    100.0 * sum(case when decision = 'ACCEPTED' then 1 else 0 end) / count(*), 2
                ) as approval_rate_pct
            from marts.fct_application_funnel
            where application_year = 2015
        """,
    ),
    # --- window functions ---
    GoldCase(
        question="Rank loan grades by default rate, with rank one being the safest grade.",
        category="window",
        sql="""
            with grade_rates as (
                select
                    grade,
                    avg(cast(is_default as double)) as default_rate
                from marts.fct_loan
                where is_terminal
                group by grade
            )
            select
                grade,
                round(100.0 * default_rate, 2) as default_rate_pct,
                rank() over (order by default_rate asc) as safety_rank
            from grade_rates
            order by safety_rank
        """,
    ),
    GoldCase(
        question="For each issue year, show the default rate and the change from the previous year in percentage points.",
        category="window",
        sql="""
            with yearly as (
                select
                    issue_year,
                    avg(cast(is_default as double)) as default_rate
                from marts.fct_loan
                where is_terminal
                group by issue_year
            )
            select
                issue_year,
                round(100.0 * default_rate, 2) as default_rate_pct,
                round(
                    100.0 * (default_rate - lag(default_rate) over (order by issue_year)), 2
                ) as change_pp
            from yearly
            order by issue_year
        """,
    ),
    # --- designed to fail ---
    GoldCase(
        question="Which loans are risky?",
        category="refusal: ambiguous",
        should_refuse=True,
        notes="No threshold, no population and no measure of risk are specified.",
    ),
    GoldCase(
        question="What is the borrower's current credit bureau score as of today, and their mobile phone carrier?",
        category="refusal: out of scope",
        should_refuse=True,
        notes="The warehouse holds origination-time attributes only and no telecom data.",
    ),
    GoldCase(
        question="List every row from the raw.accepted source table, including the loan status text.",
        category="refusal: off-allowlist table",
        should_refuse=True,
        notes="raw.accepted is a staging source and is not on the allowlist.",
    ),
]


def results_match(expected: pd.DataFrame, actual: pd.DataFrame) -> bool:
    """Compare two result sets on shape and rounded values, ignoring column names."""
    if expected.shape != actual.shape:
        return False
    left = expected.reset_index(drop=True)
    right = actual.reset_index(drop=True)
    for position in range(expected.shape[1]):
        left_column = left.iloc[:, position]
        right_column = right.iloc[:, position]
        if pd.api.types.is_numeric_dtype(left_column) and pd.api.types.is_numeric_dtype(
            right_column
        ):
            if not left_column.round(COMPARISON_TOLERANCE).equals(
                right_column.round(COMPARISON_TOLERANCE)
            ):
                return False
        elif not left_column.astype(str).equals(right_column.astype(str)):
            return False
    return True


def _is_transient(error: Exception) -> bool:
    text = str(error)
    return any(marker in text for marker in TRANSIENT_MARKERS)


def _ask_with_retry(question: str):
    """Ask the agent, retrying only transport failures from the API."""
    for attempt in range(API_MAX_ATTEMPTS):
        try:
            return ask(question)
        except (UnsafeQueryError, ValueError, RuntimeError):
            # A refusal or a guardrail rejection is a result, not a failure.
            raise
        except Exception as error:
            if not _is_transient(error) or attempt == API_MAX_ATTEMPTS - 1:
                raise
            time.sleep(API_BACKOFF_SECONDS * (attempt + 1))
    raise RuntimeError("unreachable")


def evaluate_case(case: GoldCase, connection: duckdb.DuckDBPyConnection) -> dict[str, object]:
    record: dict[str, object] = {
        "question": case.question,
        "category": case.category,
        "expected_behaviour": "refuse" if case.should_refuse else "answer",
        "correct": False,
        "detail": "",
    }



    try:
        _, actual = _ask_with_retry(case.question)
    except (UnsafeQueryError, ValueError, RuntimeError) as error:
        record["correct"] = case.should_refuse
        record["detail"] = "refused: " + str(error)[:160]
        return record
    except Exception as error:
        record["detail"] = f"{type(error).__name__}: {str(error)[:160]}"
        return record

    if case.should_refuse:
        record["detail"] = "answered a question it should have declined"
        return record

    expected = connection.execute(case.sql).df()
    record["correct"] = results_match(expected, actual)
    if not record["correct"]:
        record["detail"] = (
            f"result mismatch: expected shape {expected.shape}, got {actual.shape}"
        )
    return record


def main() -> None:
    ensure_results_dirs()
    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(
            f"{DUCKDB_PATH} not found. Run `make ingest && make build` first."
        )

    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        records = []
        for position, case in enumerate(GOLD_CASES, start=1):
            records.append(evaluate_case(case, connection))
            print(f"  {position}/{len(GOLD_CASES)} {case.category}", flush=True)
            if position < len(GOLD_CASES):
                time.sleep(PACE_SECONDS)
    finally:
        connection.close()

    report = pd.DataFrame(records)
    report.to_csv(GOVERNANCE / "text_to_sql_eval.csv", index=False)
    print(f"benchmark of {len(report)} cases written to {GOVERNANCE / 'text_to_sql_eval.csv'}")


if __name__ == "__main__":
    main()
