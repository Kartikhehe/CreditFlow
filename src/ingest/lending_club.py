"""Convert the Lending Club CSV extracts into typed, partitioned Parquet.

The non-obvious decision here is the partition key. Every downstream query in
this project filters on origination time -- vintage curves, out-of-time splits,
drift windows -- so partitioning by issue year lets DuckDB prune whole
directories instead of scanning the full history for a single cohort.

The CSVs are read with schema inference disabled and every column cast
explicitly. Lending Club changed column formats across the years it published,
and letting an inference pass guess from the first few thousand rows produces
silently truncated columns further down the file.
"""
from __future__ import annotations

import time
from pathlib import Path

import polars as pl

from src.paths import PARQUET, RAW

ACCEPTED_CSV = "accepted_2007_to_2018Q4.csv"
REJECTED_CSV = "rejected_2007_to_2018Q4.csv"

ACCEPTED_OUT = PARQUET / "accepted"
REJECTED_OUT = PARQUET / "rejected"

COMPRESSION = "zstd"

# Stored as "13.56%" in the source extract.
PERCENT_COLUMNS = ["int_rate", "revol_util"]

# Stored as "Dec-2015".
DATE_COLUMNS = ["issue_d", "earliest_cr_line", "last_pymnt_d", "last_credit_pull_d"]
LC_DATE_FORMAT = "%b-%Y"

STRING_COLUMNS = [
    "id",
    "term",
    "grade",
    "sub_grade",
    "emp_length",
    "home_ownership",
    "verification_status",
    "loan_status",
    "purpose",
    "addr_state",
    "initial_list_status",
    "application_type",
]

ACCEPTED_COLUMNS = [
    "id",
    "loan_amnt",
    "funded_amnt",
    "term",
    "int_rate",
    "installment",
    "grade",
    "sub_grade",
    "emp_length",
    "home_ownership",
    "annual_inc",
    "verification_status",
    "issue_d",
    "loan_status",
    "purpose",
    "addr_state",
    "dti",
    "delinq_2yrs",
    "earliest_cr_line",
    "fico_range_low",
    "fico_range_high",
    "inq_last_6mths",
    "open_acc",
    "pub_rec",
    "revol_bal",
    "revol_util",
    "total_acc",
    "initial_list_status",
    "out_prncp",
    "total_pymnt",
    "total_rec_prncp",
    "total_rec_int",
    "recoveries",
    "last_pymnt_d",
    "last_pymnt_amnt",
    "last_credit_pull_d",
    "application_type",
    "mort_acc",
    "pub_rec_bankruptcies",
    "tot_cur_bal",
    "total_bc_limit",
    "acc_open_past_24mths",
    "avg_cur_bal",
    "bc_util",
    "mo_sin_old_rev_tl_op",
    "mths_since_recent_inq",
    "num_actv_bc_tl",
    "num_tl_90g_dpd_24m",
    "percent_bc_gt_75",
]

NUMERIC_COLUMNS = [
    column
    for column in ACCEPTED_COLUMNS
    if column not in PERCENT_COLUMNS + DATE_COLUMNS + STRING_COLUMNS
]


def strip_percent(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .str.replace_all("%", "")
        .str.strip_chars()
        .cast(pl.Float64, strict=False)
        .alias(column)
    )


def parse_lending_club_date(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .cast(pl.Utf8)
        .str.strip_chars()
        .str.to_date(LC_DATE_FORMAT, strict=False)
        .alias(column)
    )


def _require_source(name: str) -> Path:
    path = RAW / name
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Download the Lending Club extract first: "
            "`kaggle datasets download -d wordsforthewise/lending-club -p data/raw --unzip`"
        )
    return path


def ingest_accepted() -> Path:
    """Write the funded-loan extract to Parquet, partitioned by issue year."""
    source = _require_source(ACCEPTED_CSV)
    ACCEPTED_OUT.mkdir(parents=True, exist_ok=True)

    frame = (
        pl.scan_csv(source, infer_schema_length=0, ignore_errors=True)
        .select(ACCEPTED_COLUMNS)
        .with_columns([strip_percent(column) for column in PERCENT_COLUMNS])
        .with_columns([parse_lending_club_date(column) for column in DATE_COLUMNS])
        .with_columns(
            [pl.col(column).cast(pl.Float64, strict=False) for column in NUMERIC_COLUMNS]
        )
        .with_columns(
            pl.col("term").str.extract(r"(\d+)").cast(pl.Int32).alias("term_months"),
            pl.col("issue_d").dt.year().cast(pl.Int32).alias("issue_year"),
        )
        .filter(pl.col("issue_d").is_not_null() & pl.col("loan_amnt").is_not_null())
    )

    table = frame.collect(streaming=True)
    table.write_parquet(
        ACCEPTED_OUT, partition_by=["issue_year"], compression=COMPRESSION
    )
    print(f"accepted applications written: {table.height:,} rows, {table.width} columns")
    return ACCEPTED_OUT


def ingest_rejected() -> Path:
    """Write the declined-application extract to Parquet, partitioned by year."""
    source = _require_source(REJECTED_CSV)
    REJECTED_OUT.mkdir(parents=True, exist_ok=True)

    frame = pl.scan_csv(source, infer_schema_length=0, ignore_errors=True)
    normalised = {
        name: name.strip().lower().replace(" ", "_")
        for name in frame.collect_schema().names()
    }
    frame = frame.rename(normalised)

    frame = (
        frame.with_columns(
            pl.col("amount_requested").cast(pl.Float64, strict=False),
            pl.col("risk_score").cast(pl.Float64, strict=False),
            pl.col("debt-to-income_ratio")
            .cast(pl.Utf8)
            .str.replace_all("%", "")
            .str.strip_chars()
            .cast(pl.Float64, strict=False)
            .alias("dti"),
            pl.col("application_date")
            .cast(pl.Utf8)
            .str.to_date("%Y-%m-%d", strict=False),
        )
        .with_columns(pl.col("application_date").dt.year().cast(pl.Int32).alias("app_year"))
        .filter(pl.col("application_date").is_not_null())
    )

    table = frame.collect(streaming=True)
    table.write_parquet(
        REJECTED_OUT, partition_by=["app_year"], compression=COMPRESSION
    )
    print(f"declined applications written: {table.height:,} rows")
    return REJECTED_OUT


def main() -> None:
    started = time.perf_counter()
    ingest_accepted()
    ingest_rejected()
    print(f"bronze layer complete in {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
