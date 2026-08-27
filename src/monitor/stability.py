"""Population Stability Index between the development and out-of-time windows.

The one detail that matters in a PSI implementation is where the bin edges come
from. They are quantiles of the development sample, computed once and then held
fixed while the later sample is bucketed into them. Recomputing quantiles on
each period would force both distributions to the same shape by construction
and return roughly zero no matter how far the population had moved.

Empty buckets are floored rather than dropped. A bucket that the later sample
never lands in is a real shift, and dropping it would understate the index.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.paths import METRICS, MODEL_DATA, ensure_results_dirs

DEFAULT_BINS = 10
EPSILON = 1e-6

STABLE_THRESHOLD = 0.10
SIGNIFICANT_THRESHOLD = 0.25

MONITORED_FEATURES = [
    "fico_score",
    "annual_income",
    "debt_to_income",
    "revolving_utilisation",
    "employment_years",
    "credit_history_months",
    "loan_to_income",
    "installment_burden",
    "interest_rate",
    "funded_amount",
    "state_unemployment_at_origination",
    "macro_stress",
]

TREND_FEATURE_COUNT = 6
SCORE_ROW_LABEL = "MODEL_SCORE"


def population_stability_index(
    expected: np.ndarray, actual: np.ndarray, bins: int = DEFAULT_BINS
) -> float:
    """Index between a development sample and a later sample."""
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    expected = expected[~np.isnan(expected)]
    actual = actual[~np.isnan(actual)]

    if expected.size == 0 or actual.size == 0:
        raise ValueError("PSI needs a non-empty sample on both sides")

    # Edges come from the development sample only, and the outer edges are
    # opened so the later sample cannot fall outside the scale.
    edges = np.quantile(expected, np.linspace(0, 1, bins + 1))
    edges = np.unique(edges)
    if edges.size < 2:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf

    expected_share = np.histogram(expected, edges)[0] / expected.size
    actual_share = np.histogram(actual, edges)[0] / actual.size
    expected_share = np.clip(expected_share, EPSILON, None)
    actual_share = np.clip(actual_share, EPSILON, None)

    return float(np.sum((actual_share - expected_share) * np.log(actual_share / expected_share)))


def verdict(value: float) -> str:
    if value < STABLE_THRESHOLD:
        return "STABLE"
    if value < SIGNIFICANT_THRESHOLD:
        return "MODERATE SHIFT"
    return "SIGNIFICANT SHIFT"


def _read(name: str) -> pd.DataFrame:
    path = MODEL_DATA / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m src.features.build` and the model "
            "scripts before monitoring stability."
        )
    return pd.read_parquet(path)


def main() -> None:
    ensure_results_dirs()
    train = _read("train")
    test = _read("test")

    rows = [
        {
            "feature": feature,
            "psi": round(
                population_stability_index(
                    train[feature].to_numpy(), test[feature].to_numpy()
                ),
                4,
            ),
        }
        for feature in MONITORED_FEATURES
    ]

    # Score-level stability is the row a model risk committee reads first: an
    # individual feature can drift without moving the decision, but the score
    # moving means the approved population has changed.
    scored_train = _read("scored_scorecard_train")
    scored_test = _read("scored_scorecard_test_oot")
    rows.append(
        {
            "feature": SCORE_ROW_LABEL,
            "psi": round(
                population_stability_index(
                    scored_train["pd_scorecard"].to_numpy(),
                    scored_test["pd_scorecard"].to_numpy(),
                ),
                4,
            ),
        }
    )

    report = pd.DataFrame(rows).sort_values("psi", ascending=False)
    report["verdict"] = report["psi"].apply(verdict)
    report.to_csv(METRICS / "psi_report.csv", index=False)

    trend = []
    for year in sorted(test["issue_year"].unique()):
        window = test[test["issue_year"] == year]
        trend.append(
            {
                "issue_year": int(year),
                **{
                    feature: round(
                        population_stability_index(
                            train[feature].to_numpy(), window[feature].to_numpy()
                        ),
                        4,
                    )
                    for feature in MONITORED_FEATURES[:TREND_FEATURE_COUNT]
                },
            }
        )
    pd.DataFrame(trend).to_csv(METRICS / "psi_by_year.csv", index=False)
    print(f"stability report written to {METRICS / 'psi_report.csv'}")


if __name__ == "__main__":
    main()
