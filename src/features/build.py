"""Assemble the modelling dataset and split it out of time.

Three leakage controls live here, and they are the reason this module exists
separately from the mart layer rather than being a query inside the model
scripts.

First, BANNED_COLUMNS names every field that describes what happened after
money moved. The mart keeps those columns because the profitability analysis
needs them; the modelling frame must not see them, and the assertion below
fails the build rather than quietly training on repayment history.

Second, macro features come from the fact table, where they were joined on the
origination month. Nothing is recomputed here.

Third, the split is temporal. A random split lets the model learn from 2018
loans while scoring 2016, which is a condition production never offers, and it
hides exactly the population drift the stability report is built to measure.
"""
from __future__ import annotations

import duckdb
import pandas as pd

from src.paths import DUCKDB_PATH, MODEL_DATA

TRAIN_MAX_YEAR = 2015
VALID_YEAR = 2016
TEST_MIN_YEAR = 2017

MIN_INCOME_FOR_RATIO = 1.0
MONTHS_PER_YEAR = 12

# Post-origination fields. Any of these reaching the feature frame means the
# model is being told the answer.
BANNED_COLUMNS = frozenset(
    {
        "total_payment",
        "principal_recovered",
        "interest_received",
        "recoveries",
        "last_payment_date",
        "months_on_book",
        "net_cash_flow",
        "realised_loss",
        "loan_status_raw",
        "out_prncp",
        "total_rec_prncp",
        "last_pymnt_amnt",
        "total_pymnt",
        "is_terminal",
    }
)

FEATURE_QUERY = """
select
    fct.loan_id,
    fct.issue_date,
    fct.issue_year,
    fct.vintage_quarter,
    fct.funded_amount,
    fct.interest_rate,
    fct.term_months,
    fct.grade,
    fct.sub_grade,
    fct.purpose,
    fct.geography_key                           as state_code,
    borrower.fico_score,
    borrower.annual_income,
    borrower.debt_to_income,
    borrower.employment_years,
    borrower.home_ownership,
    borrower.verification_status,
    borrower.credit_history_months,
    borrower.revolving_utilisation,
    borrower.bankruptcies,
    borrower.inquiries_6m,
    borrower.delinquencies_2y,
    fct.unemployment_at_origination,
    fct.state_unemployment_at_origination,
    fct.treasury_10y_at_origination,
    fct.sentiment_at_origination,
    fct.is_default
from marts.fct_loan as fct
join marts.dim_borrower as borrower
    on borrower.borrower_key = fct.borrower_key
where fct.is_terminal
  and fct.is_default is not null
"""


def assert_no_leakage(frame: pd.DataFrame) -> None:
    """Raise if any post-origination column survived into the feature frame."""
    present = sorted(set(frame.columns) & BANNED_COLUMNS)
    if present:
        raise AssertionError(
            "post-origination columns present in the modelling frame: "
            f"{', '.join(present)}. These describe repayment and cannot be used "
            "as origination-time features."
        )


def engineer(frame: pd.DataFrame) -> pd.DataFrame:
    """Add ratio and interaction features, all computable at application time."""
    out = frame.copy()
    income = out["annual_income"].clip(lower=MIN_INCOME_FOR_RATIO)

    out["loan_to_income"] = out["funded_amount"] / income
    out["installment_burden"] = (
        out["funded_amount"] / out["term_months"]
    ) / (income / MONTHS_PER_YEAR)
    out["credit_history_years"] = out["credit_history_months"] / MONTHS_PER_YEAR
    out["fico_x_dti"] = out["fico_score"] * out["debt_to_income"]

    # Income relative to the state median, so a given salary is read against
    # local cost of living rather than against the national distribution.
    out["income_vs_state"] = out.groupby("state_code")["annual_income"].transform(
        lambda series: series / series.median()
    )

    # How much worse the borrower's local labour market was than the national
    # one at origination.
    out["macro_stress"] = (
        out["state_unemployment_at_origination"] - out["unemployment_at_origination"]
    )
    out["is_debt_consolidation"] = (out["purpose"] == "debt_consolidation").astype(int)
    return out


def split(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "train": frame[frame["issue_year"] <= TRAIN_MAX_YEAR],
        "valid": frame[frame["issue_year"] == VALID_YEAR],
        "test": frame[frame["issue_year"] >= TEST_MIN_YEAR],
    }


def main() -> None:
    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(
            f"{DUCKDB_PATH} not found. Run `make ingest && make build` first."
        )

    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        frame = connection.execute(FEATURE_QUERY).df()
    finally:
        connection.close()

    assert_no_leakage(frame)
    frame = engineer(frame)

    MODEL_DATA.mkdir(parents=True, exist_ok=True)
    for name, part in split(frame).items():
        if part.empty:
            raise ValueError(
                f"the {name} split is empty. Check that the mart covers the "
                "expected origination years before modelling."
            )
        part.to_parquet(MODEL_DATA / f"{name}.parquet", index=False)
        print(
            f"{name:<6} rows={len(part):>9,}  "
            f"years={int(part.issue_year.min())}-{int(part.issue_year.max())}"
        )


if __name__ == "__main__":
    main()
