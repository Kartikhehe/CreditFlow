.PHONY: setup ingest build analysis model decide rag app test lint clean all
.DEFAULT_GOAL := help

DBT_DIR := dbt_creditflow

help:
	@echo "setup     install dependencies"
	@echo "ingest    raw extracts to Parquet, then register them in DuckDB"
	@echo "build     run the dbt models and their tests"
	@echo "analysis  run the analytical SQL into results/tables/"
	@echo "model     build features, fit the scorecards and the challenger"
	@echo "decide    optimise the cutoff and measure population stability"
	@echo "rag       build the retrieval index, benchmark text-to-SQL, draft the memo"
	@echo "app       serve the Streamlit front end"
	@echo "test      run the test suite"
	@echo "all       every stage in order"

setup:
	pip install -r requirements.txt
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt deps

ingest:
	python -m src.ingest.lending_club
	python -m src.ingest.fred
	python -m src.ingest.load_warehouse

build:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt build
	cd $(DBT_DIR) && DBT_PROFILES_DIR=. dbt docs generate

analysis:
	python -m analysis.run_analysis

model:
	python -m src.features.build
	python -m src.models.scorecard
	python -m src.models.scorecard_reduced
	python -m src.models.challenger
	python -m src.models.reject_inference

decide:
	python -m src.decision.optimiser
	python -m src.monitor.stability

rag:
	python -m rag.index
	python -m rag.eval_text_to_sql
	python -m rag.model_memo

app:
	streamlit run app/main.py

test:
	pytest tests/ -q

lint:
	python -c "import ast, pathlib; roots = ['src', 'rag', 'app', 'tests', 'analysis', 'orchestration']; [ast.parse(p.read_text()) for r in roots for p in pathlib.Path(r).rglob('*.py')]"
	python -c "import sqlglot, glob; [sqlglot.parse_one(open(f).read(), read='duckdb') for f in glob.glob('analysis/*.sql')]"

clean:
	rm -rf $(DBT_DIR)/target $(DBT_DIR)/dbt_packages $(DBT_DIR)/logs
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

all: ingest build analysis model decide rag
