"""Register the bronze Parquet files as DuckDB views.

These are views, not tables. DuckDB reads the Parquet directly, so registration
costs nothing and the warehouse file stays small -- the alternative would
duplicate several gigabytes for no query-time benefit, since DuckDB's Parquet
reader already pushes filters and projections into the scan.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from src.paths import DUCKDB_PATH, PARQUET, PROJECT_ROOT

RAW_SCHEMA = "raw"

SOURCES = {
    "accepted": PARQUET / "accepted",
    "rejected": PARQUET / "rejected",
    "macro": PARQUET / "macro",
}


def _glob_for(name: str, path: Path) -> str:
    if name == "macro":
        return str(path / "fred_series.parquet")
    return str(path / "**" / "*.parquet")


def main() -> None:
    missing = [name for name, path in SOURCES.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"bronze layer missing for {', '.join(missing)}. "
            "Run `make ingest` before loading the warehouse."
        )

    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(DUCKDB_PATH))
    try:
        connection.execute(f"create schema if not exists {RAW_SCHEMA};")
        for name, path in SOURCES.items():
            hive = 0 if name == "macro" else 1
            connection.execute(
                f"""
                create or replace view {RAW_SCHEMA}.{name} as
                select * from read_parquet('{_glob_for(name, path)}', hive_partitioning={hive});
                """
            )
        for name in SOURCES:
            rows = connection.execute(
                f"select count(*) from {RAW_SCHEMA}.{name}"
            ).fetchone()[0]
            print(f"{RAW_SCHEMA}.{name}: {rows:,} rows")
        print(f"warehouse registered at {DUCKDB_PATH.relative_to(PROJECT_ROOT)}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
