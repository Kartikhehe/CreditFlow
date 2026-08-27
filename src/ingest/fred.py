"""Pull macroeconomic series from the FRED API into the bronze layer.

Two series families are fetched: national indicators, and per-state
unemployment. State unemployment matters more than the national rate for this
book, because Lending Club's geographic mix shifts over time and a borrower in
a state with rising unemployment faces different conditions than the national
average implies.

Writes are idempotent: the frame is deduplicated on ``(series_id, date)`` before
it hits disk, so a partial run followed by a rerun leaves the same file rather
than duplicating observations.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import polars as pl
import requests
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

from src.paths import PARQUET

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
OUTPUT_DIR = PARQUET / "macro"
OUTPUT_FILE = OUTPUT_DIR / "fred_series.parquet"

OBSERVATION_START = "2006-01-01"
REQUEST_TIMEOUT_SECONDS = 30
COURTESY_DELAY_SECONDS = 0.4
MAX_ATTEMPTS = 5

NATIONAL_SERIES = {
    "UNRATE": "civilian unemployment rate",
    "DGS10": "10-year treasury constant maturity",
    "UMCSENT": "university of michigan consumer sentiment",
    "CPIAUCSL": "consumer price index, all urban consumers",
    "DRCCLACBS": "credit card delinquency rate, all commercial banks",
}

# The states carrying the bulk of origination volume in this book.
STATES = [
    "CA", "TX", "NY", "FL", "IL", "NJ", "PA", "OH",
    "GA", "VA", "NC", "MI", "MA", "AZ", "WA",
]


def _api_key() -> str:
    load_dotenv()
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError(
            "FRED_API_KEY is not set. Copy .env.example to .env and add a key from "
            "https://fred.stlouisfed.org/docs/api/api_key.html"
        )
    return key


@retry(
    stop=stop_after_attempt(MAX_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def fetch_series(series_id: str, api_key: str) -> pl.DataFrame:
    response = requests.get(
        BASE_URL,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": OBSERVATION_START,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    observations = response.json().get("observations", [])
    if not observations:
        raise RuntimeError(f"FRED returned no observations for series {series_id}")

    return (
        pl.DataFrame(observations)
        .select(
            pl.col("date").str.to_date("%Y-%m-%d"),
            pl.col("value").cast(pl.Float64, strict=False),
        )
        .with_columns(pl.lit(series_id).alias("series_id"))
        .drop_nulls("value")
    )


def main() -> Path:
    api_key = _api_key()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    frames: list[pl.DataFrame] = []
    for series_id in NATIONAL_SERIES:
        frames.append(fetch_series(series_id, api_key))
        time.sleep(COURTESY_DELAY_SECONDS)
    for state in STATES:
        frames.append(fetch_series(f"{state}UR", api_key))
        time.sleep(COURTESY_DELAY_SECONDS)

    combined = (
        pl.concat(frames)
        .unique(subset=["series_id", "date"], keep="last")
        .sort(["series_id", "date"])
    )
    combined.write_parquet(OUTPUT_FILE, compression="zstd")
    print(
        f"macro observations written: {combined.height:,} rows across "
        f"{combined['series_id'].n_unique()} series"
    )
    return OUTPUT_FILE


if __name__ == "__main__":
    main()
