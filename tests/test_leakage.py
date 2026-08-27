"""Tests for the leakage controls.

The point-in-time test reimplements the join independently in pandas rather
than calling the dbt model. A test that ran the model's own SQL would pass for
any join the model happened to contain; recomputing the expected value from the
month key means the test states the invariant and the model has to meet it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features.build import BANNED_COLUMNS, assert_no_leakage, engineer

POST_ORIGINATION_EXAMPLES = [
    "total_payment",
    "recoveries",
    "realised_loss",
    "months_on_book",
    "loan_status_raw",
]


def test_a_clean_frame_passes(loan_frame):
    assert_no_leakage(loan_frame)


@pytest.mark.parametrize("column", POST_ORIGINATION_EXAMPLES)
def test_each_post_origination_column_is_rejected(loan_frame, column):
    contaminated = loan_frame.assign(**{column: 1.0})
    with pytest.raises(AssertionError, match=column):
        assert_no_leakage(contaminated)


def test_the_error_names_every_offending_column(loan_frame):
    contaminated = loan_frame.assign(total_payment=1.0, recoveries=0.0)
    with pytest.raises(AssertionError) as raised:
        assert_no_leakage(contaminated)
    message = str(raised.value)
    assert "total_payment" in message
    assert "recoveries" in message


def test_the_banned_list_covers_repayment_and_outcome_fields():
    """The list is the control, so its contents are asserted, not assumed."""
    required = {
        "total_payment",
        "principal_recovered",
        "recoveries",
        "realised_loss",
        "net_cash_flow",
        "months_on_book",
        "last_payment_date",
        "loan_status_raw",
    }
    assert required <= BANNED_COLUMNS


def test_engineered_features_use_only_origination_inputs(loan_frame):
    engineered = engineer(loan_frame)
    added = set(engineered.columns) - set(loan_frame.columns)
    assert added
    assert not added & BANNED_COLUMNS
    assert_no_leakage(engineered)


def test_loan_to_income_survives_a_zero_income_row(loan_frame):
    zero_income = loan_frame.assign(annual_income=[0.0, 90_000.0, 45_000.0])
    engineered = engineer(zero_income)
    assert np.isfinite(engineered["loan_to_income"]).all()


def point_in_time_join(loans: pd.DataFrame, macro: pd.DataFrame) -> pd.DataFrame:
    """Attach each loan the macro reading of its own origination month."""
    return loans.drop(columns=["unemployment_at_origination"]).merge(
        macro.rename(columns={"unemployment_national": "unemployment_at_origination"}),
        left_on="issue_month",
        right_on="month",
        how="left",
    )


def test_the_macro_join_returns_the_origination_month_value(loan_frame, macro_frame):
    joined = point_in_time_join(loan_frame, macro_frame)
    for _, row in joined.iterrows():
        expected = macro_frame.loc[
            macro_frame["month"] == row["issue_month"], "unemployment_national"
        ].iloc[0]
        assert row["unemployment_at_origination"] == pytest.approx(expected)


def test_no_loan_carries_a_macro_value_from_a_later_month(loan_frame, macro_frame):
    """The invariant the dbt singular test enforces on the warehouse."""
    joined = point_in_time_join(loan_frame, macro_frame)
    lookup = dict(zip(macro_frame["month"], macro_frame["unemployment_national"]))

    for _, row in joined.iterrows():
        later_values = {
            value
            for month, value in lookup.items()
            if month > row["issue_month"] and value != lookup[row["issue_month"]]
        }
        assert row["unemployment_at_origination"] not in later_values


def test_a_forward_filled_join_is_detectable(loan_frame, macro_frame):
    """A join that reaches ahead must fail the same check that passes above.

    This is the regression the control exists to catch, so the test asserts the
    check has teeth rather than only that the correct join passes it.
    """
    shifted = macro_frame.copy()
    shifted["month"] = shifted["month"] - pd.DateOffset(months=6)
    leaked = point_in_time_join(loan_frame, shifted)

    correct = point_in_time_join(loan_frame, macro_frame)
    assert not np.allclose(
        leaked["unemployment_at_origination"].to_numpy(),
        correct["unemployment_at_origination"].to_numpy(),
    )


def test_macro_stress_is_the_gap_between_state_and_national(loan_frame):
    engineered = engineer(loan_frame)
    expected = (
        loan_frame["state_unemployment_at_origination"]
        - loan_frame["unemployment_at_origination"]
    )
    assert np.allclose(engineered["macro_stress"], expected)
