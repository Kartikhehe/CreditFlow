"""Execute every query in ``analysis/`` and write its result to results/tables/.

Output filenames drop the numeric prefix the SQL files carry: the prefix orders
the files for a reader working through them, but the artifact is referenced by
name from the README and the app, and a name that survives reordering is worth
more than one that encodes position.
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb

from src.paths import DUCKDB_PATH, PROJECT_ROOT, TABLES, ensure_results_dirs

ANALYSIS_DIR = PROJECT_ROOT / "analysis"
PREFIX_PATTERN = re.compile(r"^\d+_")


def output_name(query_path: Path) -> str:
    return f"{PREFIX_PATTERN.sub('', query_path.stem)}.csv"


def main() -> None:
    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(
            f"{DUCKDB_PATH} not found. Run `make ingest && make build` before `make analysis`."
        )

    ensure_results_dirs()
    queries = sorted(ANALYSIS_DIR.glob("*.sql"))
    if not queries:
        raise FileNotFoundError(f"no .sql files found in {ANALYSIS_DIR}")

    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        for query_path in queries:
            frame = connection.execute(query_path.read_text()).df()
            destination = TABLES / output_name(query_path)
            frame.to_csv(destination, index=False)
            print(
                f"{query_path.name} -> {destination.relative_to(PROJECT_ROOT)} "
                f"({len(frame)} rows, {len(frame.columns)} columns)"
            )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
