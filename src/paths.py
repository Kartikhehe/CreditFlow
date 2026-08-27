"""Single source of truth for every path the pipeline reads or writes.

Every artifact the pipeline produces lands under ``results/`` and nowhere else.
Importing the constants from here rather than hardcoding relative paths in each
module is what makes that constraint enforceable: there is exactly one place
where an output directory is named, so a stray write is easy to spot in review.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Inputs and intermediates. None of these are tracked.
DATA = PROJECT_ROOT / "data"
RAW = DATA / "raw"
PARQUET = DATA / "parquet"
WAREHOUSE = DATA / "warehouse"
MODEL_DATA = DATA / "model"
DOCS_CORPUS = DATA / "docs"
DUCKDB_PATH = WAREHOUSE / "creditflow.duckdb"
MODEL_ARTIFACTS = PROJECT_ROOT / "models"

# Outputs. The only tracked directory the pipeline writes into.
RESULTS = PROJECT_ROOT / "results"
METRICS = RESULTS / "metrics"
TABLES = RESULTS / "tables"
FIGURES = RESULTS / "figures"
GOVERNANCE = RESULTS / "governance"

_OUTPUT_DIRS = (METRICS, TABLES, FIGURES, GOVERNANCE)


def ensure_results_dirs() -> None:
    """Create the results subdirectories if a fresh clone has not been run yet."""
    for directory in _OUTPUT_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


def require(path: Path, produced_by: str) -> Path:
    """Return ``path``, or raise pointing at the command that would create it."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path.relative_to(PROJECT_ROOT)} is missing. Run `{produced_by}` to produce it."
        )
    return path
