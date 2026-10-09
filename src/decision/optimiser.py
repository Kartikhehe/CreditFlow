"""Turn a probability of default into an approve or decline decision.

A cutoff is a business choice, not a modelling one, so this module states its
unit economics explicitly and sweeps the whole frontier rather than reporting a
single number. Every assumption is a named constant, because the conclusion
moves with them and a reader needs to see what they would have to disagree with.

The swap-set analysis is the part a credit policy committee actually asks for.
Two models at the same approval rate approve different people, and the
difference between who each one lets in is more informative than the difference
between their AUCs.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.paths import FIGURES, METRICS, MODEL_DATA, TABLES, ensure_results_dirs

# Loss given default, net of recoveries, on a charged-off unsecured consumer
# loan. Held constant rather than modelled; the decision documentation records
# which conclusions that simplification touches.
LGD = 0.65

# Marginal funding cost, annualised.
COST_OF_FUNDS = 0.035

# Acquisition and servicing cost per booked loan, over its life.
OPEX_PER_LOAN = 120.0

# Share of contractual interest actually collected on a performing loan, after
# borrowers who settle ahead of schedule stop paying the remaining coupon.
#
# Calibrated against realised net cash flow on the seasoned 2012-2014 cohorts
# rather than assumed: those vintages are old enough that nearly every loan has
# terminated, so their realised return is a fact the modelled economics can be
# checked against. An earlier value of 0.55 here double-counted early
# termination, because AVERAGE_BALANCE_FACTOR below already accounts for the
# balance retiring over the term, and the two together made every cutoff
# unprofitable.
PREPAYMENT_RETENTION = 0.95

# Average balance outstanding over the life of a level-payment loan, as a share
# of the amount funded. Principal amortises to zero across the term, so the
# interest earned, the funding cost and the loss on default all accrue on
# roughly half the original balance rather than all of it. A level-payment
# schedule sits slightly above the 0.5 a straight-line payoff would give,
# because early payments are interest-weighted and principal retires more
# slowly at the start.
AVERAGE_BALANCE_FACTOR = 0.55

MONTHS_PER_YEAR = 12
CUTOFF_MIN = 0.02
CUTOFF_MAX = 0.60
CUTOFF_STEP = 0.005
MIN_APPROVED_FOR_SWEEP = 100

SWAP_APPROVAL_RATES = (0.50, 0.65, 0.80)
FIGURE_DPI = 150

MODELS = {"scorecard": "pd_scorecard", "challenger": "pd_challenger"}


def unit_economics(frame: pd.DataFrame, pd_column: str) -> pd.DataFrame:
    """Attach expected revenue, loss and profit per application.

    Interest and funding both accrue on the balance outstanding, not on the
    original principal. These are amortising instalment loans, so the balance
    declines to zero over the term and the average exposure is roughly half the
    amount funded. Charging either leg on full principal for the full term
    overstates it by about a factor of two, and because funding cost is a pure
    subtraction while interest is scaled by survival, the two errors do not
    cancel: the result is a book that loses money at every cutoff.
    """
    out = frame.copy()
    years = out["term_months"] / MONTHS_PER_YEAR
    probability = out[pd_column]

    # Average balance over the life of a level-payment loan.
    average_balance = out["funded_amount"] * AVERAGE_BALANCE_FACTOR

    gross_interest = (
        average_balance * (out["interest_rate"] / 100) * years * PREPAYMENT_RETENTION
    )
    funding_cost = average_balance * COST_OF_FUNDS * years

    out["expected_revenue"] = (1 - probability) * gross_interest
    out["expected_loss"] = probability * average_balance * LGD
    out["expected_profit"] = (
        out["expected_revenue"] - out["expected_loss"] - funding_cost - OPEX_PER_LOAN
    )
    return out


def sweep_cutoffs(frame: pd.DataFrame, pd_column: str) -> pd.DataFrame:
    """Evaluate every cutoff, reporting both predicted and realised bad rates."""
    rows = []
    for cutoff in np.arange(CUTOFF_MIN, CUTOFF_MAX, CUTOFF_STEP):
        approved = frame[frame[pd_column] <= cutoff]
        if len(approved) < MIN_APPROVED_FOR_SWEEP:
            continue
        rows.append(
            {
                "cutoff_pd": round(float(cutoff), 3),
                "approval_rate": len(approved) / len(frame),
                "approved_loans": len(approved),
                "volume_musd": approved["funded_amount"].sum() / 1e6,
                "predicted_bad_rate": approved[pd_column].mean(),
                "realised_bad_rate": approved["is_default"].mean(),
                "expected_profit_musd": approved["expected_profit"].sum() / 1e6,
                "expected_profit_per_application": approved["expected_profit"].sum()
                / len(frame),
                "expected_loss_musd": approved["expected_loss"].sum() / 1e6,
            }
        )
    if not rows:
        raise ValueError(
            "no cutoff admitted enough applications to evaluate; widen the "
            "cutoff range or check that the scored frame is populated"
        )
    return pd.DataFrame(rows)


def swap_set(
    frame: pd.DataFrame, candidate_column: str, incumbent_column: str, approval_rate: float
) -> dict[str, float]:
    """Compare who two rankings approve when both are held to the same volume.

    Holding volume equal is what makes the comparison fair: a model that simply
    approves more people will look better on volume and worse on loss rate for
    reasons that have nothing to do with its ranking.
    """
    n_approved = int(len(frame) * approval_rate)
    candidate_approved = set(frame.nsmallest(n_approved, candidate_column)["loan_id"])
    incumbent_approved = set(frame.nsmallest(n_approved, incumbent_column)["loan_id"])

    swap_in = frame[frame["loan_id"].isin(candidate_approved - incumbent_approved)]
    swap_out = frame[frame["loan_id"].isin(incumbent_approved - candidate_approved)]

    has_both = len(swap_in) > 0 and len(swap_out) > 0
    return {
        "approval_rate": approval_rate,
        "swap_in_loans": len(swap_in),
        "swap_in_bad_rate": float(swap_in["is_default"].mean()) if len(swap_in) else np.nan,
        "swap_out_loans": len(swap_out),
        "swap_out_bad_rate": float(swap_out["is_default"].mean()) if len(swap_out) else np.nan,
        "bad_rate_improvement_pp": (
            float((swap_out["is_default"].mean() - swap_in["is_default"].mean()) * 100)
            if has_both
            else np.nan
        ),
    }


def load_scored() -> pd.DataFrame:
    scorecard_path = MODEL_DATA / "scored_scorecard_test_oot.parquet"
    challenger_path = MODEL_DATA / "scored_challenger_test_oot.parquet"
    for path, module in (
        (scorecard_path, "src.models.scorecard"),
        (challenger_path, "src.models.challenger"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Run `python -m {module}` first.")

    scorecard = pd.read_parquet(scorecard_path)
    challenger = pd.read_parquet(challenger_path)
    return scorecard.merge(
        challenger[["loan_id", "pd_challenger"]], on="loan_id", validate="one_to_one"
    )


def plot_frontier(sweep: pd.DataFrame) -> None:
    figure, profit_axis = plt.subplots(figsize=(8, 5))
    profit_axis.plot(
        sweep["approval_rate"], sweep["expected_profit_musd"], "b-", linewidth=2
    )
    profit_axis.set_xlabel("Approval rate")
    profit_axis.set_ylabel("Expected profit ($M)", color="b")

    risk_axis = profit_axis.twinx()
    risk_axis.plot(
        sweep["approval_rate"], sweep["realised_bad_rate"] * 100, "r--", linewidth=2
    )
    risk_axis.set_ylabel("Realised bad rate (%)", color="r")

    peak = sweep.loc[sweep["expected_profit_musd"].idxmax()]
    profit_axis.axvline(peak["approval_rate"], color="grey", linestyle=":")
    profit_axis.set_title("Approval rate against profit and risk, out-of-time window")
    figure.tight_layout()
    figure.savefig(FIGURES / "profit_frontier.png", dpi=FIGURE_DPI)
    plt.close(figure)


def main() -> None:
    ensure_results_dirs()
    scored = load_scored()

    # The incumbent policy is proxied by the priced interest rate: Lending Club
    # set the coupon from its own grade assignment, so the rate percentile is
    # the closest available stand-in for the risk ranking already in force.
    scored["pd_incumbent"] = scored["interest_rate"].rank(pct=True)

    optimal = {}
    for label, pd_column in MODELS.items():
        priced = unit_economics(scored, pd_column)
        sweep = sweep_cutoffs(priced, pd_column)
        sweep.to_csv(TABLES / f"cutoff_sweep_{label}.csv", index=False)
        optimal[label] = sweep.loc[sweep["expected_profit_musd"].idxmax()].to_dict()

    pd.DataFrame(optimal).T.to_csv(METRICS / "optimal_cutoffs.csv", index_label="model")

    swaps = [
        swap_set(scored, "pd_challenger", "pd_incumbent", rate)
        for rate in SWAP_APPROVAL_RATES
    ]
    pd.DataFrame(swaps).to_csv(TABLES / "swap_set_analysis.csv", index=False)

    plot_frontier(pd.read_csv(TABLES / "cutoff_sweep_challenger.csv"))
    print(f"decision artifacts written to {TABLES} and {METRICS}")


if __name__ == "__main__":
    main()
