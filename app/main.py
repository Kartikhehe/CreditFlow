"""Streamlit front end over the warehouse and the generated results.

Every tab reads artifacts from results/ rather than recomputing anything, so
the app is a viewer over whatever the last pipeline run produced and starting
it never triggers a model fit. Artifacts that have not been generated yet are
reported as a missing-artifact notice naming the make target that produces
them, because a stack trace on a fresh clone is a worse answer than a
one-line instruction.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.paths import DUCKDB_PATH, FIGURES, METRICS, TABLES

PAGE_TITLE = "CreditFlow"
DEFAULT_VINTAGE_COUNT = 8
PSI_MODERATE = 0.10
PSI_SIGNIFICANT = 0.25

st.set_page_config(page_title=PAGE_TITLE, layout="wide")


@st.cache_data(show_spinner=False)
def query(sql: str) -> pd.DataFrame:
    connection = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    try:
        return connection.execute(sql).df()
    finally:
        connection.close()


@st.cache_data(show_spinner=False)
def read_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def missing(target: str, artifact: Path) -> None:
    st.info(f"`{artifact.name}` has not been generated yet. Run `make {target}` to produce it.")


def require_csv(path: Path, target: str) -> pd.DataFrame | None:
    if not path.exists():
        missing(target, path)
        return None
    return read_csv(str(path))


def require_warehouse() -> bool:
    if not DUCKDB_PATH.exists():
        st.info("The warehouse has not been built yet. Run `make ingest && make build`.")
        return False
    return True


def render_portfolio() -> None:
    if not require_warehouse():
        return

    headline = query(
        """
        select
            count(*)                                        as loans,
            sum(funded_amount) / 1e9                        as funded_busd,
            100 * avg(cast(is_default as double))           as default_rate_pct,
            avg(interest_rate)                              as avg_interest_rate
        from marts.fct_loan
        where is_terminal
        """
    )
    columns = st.columns(4)
    columns[0].metric("Terminal loans", f"{headline.loans[0]:,.0f}")
    columns[1].metric("Funded", f"${headline.funded_busd[0]:.1f}B")
    columns[2].metric("Charge-off rate", f"{headline.default_rate_pct[0]:.2f}%")
    columns[3].metric("Average APR", f"{headline.avg_interest_rate[0]:.2f}%")

    segments = query(
        """
        select
            borrower.fico_band,
            count(*)                                        as loans,
            100 * avg(cast(fct.is_default as double))       as default_rate_pct,
            sum(fct.net_cash_flow) / 1e6                    as net_profit_musd
        from marts.fct_loan as fct
        join marts.dim_borrower as borrower
            on borrower.borrower_key = fct.borrower_key
        where fct.is_terminal
        group by borrower.fico_band
        order by default_rate_pct
        """
    )
    st.plotly_chart(
        px.bar(
            segments,
            x="fico_band",
            y="default_rate_pct",
            color="net_profit_musd",
            labels={
                "fico_band": "FICO band",
                "default_rate_pct": "Charge-off rate (%)",
                "net_profit_musd": "Net profit ($M)",
            },
            title="Charge-off rate and realised profit by FICO band",
        ),
        use_container_width=True,
    )


def render_vintages() -> None:
    curves = require_csv(TABLES / "vintage_curves.csv", "analysis")
    if curves is None:
        return

    available = sorted(curves["vintage_quarter"].unique())
    selected = st.multiselect(
        "Vintages", available, default=available[-DEFAULT_VINTAGE_COUNT:]
    )
    if not selected:
        st.info("Select at least one vintage.")
        return

    st.plotly_chart(
        px.line(
            curves[curves["vintage_quarter"].isin(selected)],
            x="months_on_book",
            y="cumulative_default_rate_pct",
            color="vintage_quarter",
            labels={
                "months_on_book": "Months on book",
                "cumulative_default_rate_pct": "Cumulative default rate (%)",
                "vintage_quarter": "Vintage",
            },
            title="Cumulative default rate by months on book",
        ),
        use_container_width=True,
    )


def render_model_performance() -> None:
    scorecard = require_csv(METRICS / "scorecard_metrics.csv", "model")
    challenger = require_csv(METRICS / "challenger_metrics.csv", "model")
    if scorecard is None or challenger is None:
        return

    scorecard = scorecard.assign(model="Scorecard (champion)")
    challenger = challenger.assign(model="Challenger")
    combined = pd.concat([scorecard, challenger], ignore_index=True)
    st.dataframe(
        combined[["model"] + [c for c in combined.columns if c != "model"]],
        use_container_width=True,
        hide_index=True,
    )

    left, right = st.columns(2)
    calibration = FIGURES / "calibration.png"
    shap_summary = FIGURES / "shap_summary.png"
    if calibration.exists():
        left.image(str(calibration), caption="Calibration on the out-of-time window")
    else:
        with left:
            missing("model", calibration)
    if shap_summary.exists():
        right.image(str(shap_summary), caption="Challenger feature attribution")
    else:
        with right:
            missing("model", shap_summary)


def render_decision_simulator() -> None:
    sweep = require_csv(TABLES / "cutoff_sweep_challenger.csv", "decide")
    if sweep is None:
        return

    low = float(sweep["approval_rate"].min())
    high = float(sweep["approval_rate"].max())
    target = st.slider(
        "Target approval rate", low, high, value=float(sweep["approval_rate"].median())
    )
    row = sweep.iloc[(sweep["approval_rate"] - target).abs().argmin()]

    columns = st.columns(4)
    columns[0].metric("Approval rate", f"{row.approval_rate:.1%}")
    columns[1].metric("Realised bad rate", f"{row.realised_bad_rate:.2%}")
    columns[2].metric("Volume", f"${row.volume_musd:,.0f}M")
    columns[3].metric("Expected profit", f"${row.expected_profit_musd:,.1f}M")

    figure = go.Figure()
    figure.add_scatter(
        x=sweep["approval_rate"], y=sweep["expected_profit_musd"], name="Expected profit ($M)"
    )
    figure.add_scatter(
        x=sweep["approval_rate"],
        y=sweep["realised_bad_rate"] * 100,
        name="Realised bad rate (%)",
        yaxis="y2",
    )
    figure.update_layout(
        title="Approval rate frontier",
        xaxis_title="Approval rate",
        yaxis_title="Expected profit ($M)",
        yaxis2=dict(title="Realised bad rate (%)", overlaying="y", side="right"),
    )
    st.plotly_chart(figure, use_container_width=True)

    swaps = TABLES / "swap_set_analysis.csv"
    if swaps.exists():
        st.subheader("Swap sets against the incumbent policy")
        st.dataframe(read_csv(str(swaps)), use_container_width=True, hide_index=True)


def render_stability() -> None:
    report = require_csv(METRICS / "psi_report.csv", "decide")
    if report is None:
        return

    st.dataframe(
        report.style.background_gradient(subset=["psi"], cmap="Reds"),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        f"Below {PSI_MODERATE:.2f} stable · {PSI_MODERATE:.2f} to {PSI_SIGNIFICANT:.2f} "
        f"investigate · above {PSI_SIGNIFICANT:.2f} revalidate"
    )

    trend = METRICS / "psi_by_year.csv"
    if trend.exists():
        st.subheader("Drift by origination year")
        st.dataframe(read_csv(str(trend)), use_container_width=True, hide_index=True)


def render_ask_the_data() -> None:
    st.subheader("Ask the warehouse in plain English")
    st.caption(
        "Generated SQL is parsed and checked against a table allowlist before it runs. "
        "Queries that are not read-only, or that reference tables outside the marts, "
        "are rejected."
    )
    if not require_warehouse():
        return

    question = st.text_input("Question", placeholder="Which states had the worst 2016 vintage?")
    if not question:
        return

    try:
        from rag.text_to_sql import ask

        sql, frame = ask(question)
    except Exception as error:
        st.error(f"{type(error).__name__}: {error}")
        return

    st.code(sql, language="sql")
    st.dataframe(frame, use_container_width=True, hide_index=True)


TABS = [
    ("Portfolio", render_portfolio),
    ("Vintages", render_vintages),
    ("Model performance", render_model_performance),
    ("Decision simulator", render_decision_simulator),
    ("Stability", render_stability),
    ("Ask the data", render_ask_the_data),
]


def main() -> None:
    st.title("CreditFlow")
    st.caption("Credit risk analytics and decisioning over the Lending Club book")
    for tab, (_, render) in zip(st.tabs([name for name, _ in TABS]), TABS):
        with tab:
            render()


if __name__ == "__main__":
    main()
