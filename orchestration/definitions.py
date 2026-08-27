"""Dagster asset graph over the pipeline.

The assets shell out to the same module entry points the Makefile calls rather
than importing and invoking their functions. That keeps one execution path: a
run from the command line and a run from the scheduler execute identical code,
so a failure reproduces the same way in both.

Dependencies are declared to match the real data flow, which lets Dagster
rebuild only what a change actually invalidates instead of re-running the whole
graph.
"""
from __future__ import annotations

import subprocess

from dagster import (
    AssetExecutionContext,
    Definitions,
    ScheduleDefinition,
    asset,
    define_asset_job,
)

LOG_TAIL_CHARS = 4000
WEEKLY_MONDAY_3AM = "0 3 * * 1"


def run(command: str, context: AssetExecutionContext) -> None:
    """Execute a pipeline step, surfacing its output through the Dagster log."""
    context.log.info(command)
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.stdout:
        context.log.info(result.stdout[-LOG_TAIL_CHARS:])
    if result.returncode != 0:
        raise RuntimeError(
            f"`{command}` exited with status {result.returncode}:\n"
            f"{result.stderr[-LOG_TAIL_CHARS:]}"
        )


@asset(group_name="bronze")
def lending_club_parquet(context: AssetExecutionContext) -> None:
    run("python -m src.ingest.lending_club", context)


@asset(group_name="bronze")
def fred_macro(context: AssetExecutionContext) -> None:
    run("python -m src.ingest.fred", context)


@asset(deps=[lending_club_parquet, fred_macro], group_name="warehouse")
def duckdb_raw_views(context: AssetExecutionContext) -> None:
    run("python -m src.ingest.load_warehouse", context)


@asset(deps=[duckdb_raw_views], group_name="warehouse")
def dbt_marts(context: AssetExecutionContext) -> None:
    run("cd dbt_creditflow && DBT_PROFILES_DIR=. dbt build", context)


@asset(deps=[dbt_marts], group_name="analysis")
def analysis_tables(context: AssetExecutionContext) -> None:
    run("python -m analysis.run_analysis", context)


@asset(deps=[dbt_marts], group_name="modelling")
def modelling_features(context: AssetExecutionContext) -> None:
    run("python -m src.features.build", context)


@asset(deps=[modelling_features], group_name="modelling")
def scorecard(context: AssetExecutionContext) -> None:
    run("python -m src.models.scorecard", context)


@asset(deps=[modelling_features], group_name="modelling")
def scorecard_reduced(context: AssetExecutionContext) -> None:
    run("python -m src.models.scorecard_reduced", context)


@asset(deps=[modelling_features], group_name="modelling")
def challenger(context: AssetExecutionContext) -> None:
    run("python -m src.models.challenger", context)


@asset(deps=[scorecard_reduced], group_name="modelling")
def reject_inference(context: AssetExecutionContext) -> None:
    run("python -m src.models.reject_inference", context)


@asset(deps=[scorecard, challenger], group_name="decision")
def decision_engine(context: AssetExecutionContext) -> None:
    run("python -m src.decision.optimiser", context)


@asset(deps=[scorecard], group_name="monitoring")
def stability_report(context: AssetExecutionContext) -> None:
    run("python -m src.monitor.stability", context)


@asset(group_name="governance")
def retrieval_index(context: AssetExecutionContext) -> None:
    run("python -m rag.index", context)


@asset(deps=[dbt_marts, retrieval_index], group_name="governance")
def text_to_sql_benchmark(context: AssetExecutionContext) -> None:
    run("python -m rag.eval_text_to_sql", context)


@asset(
    deps=[decision_engine, stability_report, reject_inference, retrieval_index],
    group_name="governance",
)
def validation_memo(context: AssetExecutionContext) -> None:
    run("python -m rag.model_memo", context)


ASSETS = [
    lending_club_parquet,
    fred_macro,
    duckdb_raw_views,
    dbt_marts,
    analysis_tables,
    modelling_features,
    scorecard,
    scorecard_reduced,
    challenger,
    reject_inference,
    decision_engine,
    stability_report,
    retrieval_index,
    text_to_sql_benchmark,
    validation_memo,
]

full_refresh = define_asset_job("full_refresh")

defs = Definitions(
    assets=ASSETS,
    jobs=[full_refresh],
    schedules=[
        ScheduleDefinition(job=full_refresh, cron_schedule=WEEKLY_MONDAY_3AM)
    ],
)
