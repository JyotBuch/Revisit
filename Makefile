## Revisit — local development commands
## Run `make help` to see all targets.

PYTHON   := .venv/bin/python
PIP      := .venv/bin/pip
PYTEST   := .venv/bin/pytest
UVICORN  := .venv/bin/uvicorn
ALEMBIC  := .venv/bin/alembic
GUNICORN := .venv/bin/gunicorn

.PHONY: help install db-up db-down db-test-setup migrate dev start test seed-demo eval batch

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install all dependencies
	python3 -m venv .venv
	$(PIP) install -r requirements.txt

db-up: ## Start Postgres in Docker (pgvector image)
	docker compose up -d

db-down: ## Stop and remove Postgres container
	docker compose down

db-test-setup: ## Create the revisit_test database (run once after db-up)
	psql postgresql://$$USER@localhost:5432/postgres \
		-c "CREATE DATABASE revisit_test OWNER revisit;" 2>/dev/null || true
	psql postgresql://$$USER@localhost:5432/revisit_test \
		-c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || true
	DATABASE_URL=postgresql+psycopg2://revisit:revisit@localhost:5432/revisit_test \
		$(ALEMBIC) upgrade head

migrate: ## Apply Alembic migrations to the main database
	$(ALEMBIC) upgrade head

dev: ## Start FastAPI with auto-reload (loads .env automatically)
	$(UVICORN) app.main:app --reload

start: ## Start FastAPI with gunicorn + uvicorn workers (production-style)
	$(GUNICORN) -k uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:${PORT:-8000} --timeout 120 app.main:app

test: ## Run the integration test suite against revisit_test
	$(PYTEST) tests/ -v

seed-demo: ## Seed demo data and run the daily batch (add --clear to wipe first)
	$(PYTHON) scripts/seed_demo_data.py $(ARGS)

eval: ## Run the offline eval harness for Revisit Cards
	$(PYTHON) -m evals.run_revisit_card_eval

batch: ## Trigger the daily batch via the running API (rule_based)
	/usr/bin/curl -s -X POST "http://127.0.0.1:8000/jobs/daily-batch" | \
		$(PYTHON) -c "import json,sys; j=json.load(sys.stdin); print('status:', j['status']); [print(f'  {k}: {v}') for k,v in (j.get('summary_json') or {}).items()]"
