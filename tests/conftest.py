"""Synthetic fixtures so the suite runs on a clone with no data downloaded.

The fixtures are generated rather than sampled from the real extract. That
keeps the repository free of loan data, and it lets each test state the exact
property it is checking -- a separation the tests assert on is put there
deliberately, not hoped for.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

SEED = 20260827
SAMPLE_SIZE = 20_000


@pytest.fixture(scope="session")
def rng() -> np.random.Generator:
    return np.random.default_rng(SEED)


@pytest.fixture
def perfectly_separated() -> tuple[np.ndarray, np.ndarray]:
    """Labels and scores with no overlap between the classes."""
    labels = np.array([0] * 100 + [1] * 100)
    scores = np.array([0.1] * 100 + [0.9] * 100)
    return labels, scores


@pytest.fixture
def uninformative(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Labels and scores drawn independently, so the score carries no signal."""
    labels = rng.integers(0, 2, SAMPLE_SIZE)
    scores = rng.random(SAMPLE_SIZE)
    return labels, scores


@pytest.fixture
def stable_samples(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Two draws from the same distribution."""
    return rng.normal(size=SAMPLE_SIZE), rng.normal(size=SAMPLE_SIZE)


@pytest.fixture
def shifted_samples(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Two draws whose means differ by well over one standard deviation."""
    return rng.normal(0, 1, SAMPLE_SIZE), rng.normal(1.5, 1, SAMPLE_SIZE)


@pytest.fixture
def loan_frame() -> pd.DataFrame:
    """A minimal modelling frame carrying only origination-time columns."""
    return pd.DataFrame(
        {
            "loan_id": ["a", "b", "c"],
            "issue_year": [2015, 2016, 2017],
            "issue_month": pd.to_datetime(["2015-03-01", "2016-07-01", "2017-01-01"]),
            "funded_amount": [10_000.0, 15_000.0, 8_000.0],
            "annual_income": [60_000.0, 90_000.0, 45_000.0],
            "term_months": [36, 60, 36],
            "credit_history_months": [120, 240, 60],
            "fico_score": [700.0, 760.0, 640.0],
            "debt_to_income": [18.0, 12.0, 29.0],
            "state_code": ["CA", "CA", "TX"],
            "purpose": ["debt_consolidation", "credit_card", "debt_consolidation"],
            "unemployment_at_origination": [5.5, 4.9, 4.4],
            "state_unemployment_at_origination": [6.2, 5.4, 4.0],
            "is_default": [0, 1, 0],
        }
    )


@pytest.fixture
def macro_frame() -> pd.DataFrame:
    """Monthly national unemployment, one row per month."""
    months = pd.date_range("2015-01-01", "2017-12-01", freq="MS")
    return pd.DataFrame(
        {
            "month": months,
            "unemployment_national": np.linspace(5.7, 4.1, len(months)),
        }
    )
