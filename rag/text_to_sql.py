"""Natural language to validated SQL against the warehouse.

The model is asked for one SELECT and given the mart schema to write it
against. Nothing it returns reaches the database unchecked: every candidate
goes through the AST validator in rag.sql_guard first, and the connection is
opened read-only regardless, so a validator bug still cannot write.

The prompt also gives the model a way to decline. A question the schema cannot
answer should produce a refusal rather than a query that runs and returns
something plausible-looking, which is the failure mode that matters here.
"""
from __future__ import annotations

import os
import re

import anthropic
import duckdb
import pandas as pd
from dotenv import load_dotenv

from rag.sql_guard import UnsafeQueryError, validate
from src.paths import DUCKDB_PATH

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1000

FENCE_PATTERN = re.compile(r"^```(?:sql)?\s*|\s*```$", re.MULTILINE)

SCHEMA_DOC = """
marts.fct_loan (grain: one funded loan)
  loan_id, date_key, borrower_key, geography_key, issue_date, issue_month,
  issue_year, grade, sub_grade, purpose, term_months, application_type,
  funded_amount, interest_rate, installment, is_default (1 = charged off,
  0 = fully paid, null while in flight), is_terminal, net_cash_flow,
  realised_loss, total_payment, months_on_book, unemployment_at_origination,
  state_unemployment_at_origination, treasury_10y_at_origination,
  sentiment_at_origination, cpi_at_origination,
  industry_delinquency_at_origination, vintage_quarter

marts.dim_borrower (grain: one borrower per loan, joins on borrower_key = loan_id)
  borrower_key, fico_score, fico_band, annual_income, income_decile,
  debt_to_income, dti_band, employment_years, home_ownership,
  verification_status, credit_history_months, revolving_utilisation,
  bankcard_utilisation, bankruptcies, public_records, delinquencies_2y,
  inquiries_6m

marts.dim_geography
  geography_key, state_code, census_region

marts.dim_date
  date_key, month_date, calendar_year, calendar_quarter, calendar_month,
  year_quarter, is_gfc_period

marts.fct_application_funnel (grain: one application, accepted or declined)
  decision ('ACCEPTED' or 'REJECTED'), application_date, application_month,
  application_year, amount_requested, fico_score, debt_to_income, state_code,
  employment_years, is_default (always null for declined applications)
"""

SYSTEM_PROMPT = f"""You are a SQL analyst for a credit risk warehouse running DuckDB.
Write exactly one SELECT statement that answers the user's question.

Schema:
{SCHEMA_DOC}

Rules:
- Only SELECT. Never DDL or DML.
- Filter on is_terminal = true whenever computing a default rate, because loans
  still in flight carry no label.
- Use explicit JOIN ... ON. Never an implicit join.
- Qualify tables with the marts schema.
- Round percentages to two decimals and give them a clear alias.
- If the question cannot be answered from this schema, return the single word
  UNANSWERABLE and nothing else.
- Return only the SQL. No markdown fences, no commentary."""

UNANSWERABLE = "UNANSWERABLE"


def generate_sql(question: str) -> str:
    """Ask the model for a single SELECT answering the question."""
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add a key."
        )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )
    raw = "".join(block.text for block in message.content if block.type == "text")
    return FENCE_PATTERN.sub("", raw.strip()).strip()


def ask(question: str) -> tuple[str, pd.DataFrame]:
    """Answer a question, returning the SQL that ran and its result."""
    candidate = generate_sql(question)
    if candidate.strip().upper().startswith(UNANSWERABLE):
        raise UnsafeQueryError(
            "the question cannot be answered from the warehouse schema"
        )

    sql = validate(candidate)
    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(
            f"{DUCKDB_PATH} not found. Run `make ingest && make build` first."
        )

    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        return sql, connection.execute(sql).df()
    finally:
        connection.close()


if __name__ == "__main__":
    import sys

    prompt = " ".join(sys.argv[1:]) or "What is the default rate by FICO band?"
    executed, result = ask(prompt)
    print(executed, "\n")
    print(result.head(20).to_string(index=False))
