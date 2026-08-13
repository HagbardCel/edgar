EDGAR_TEST_DATABASE_URL ?= postgresql+psycopg://edgar:edgar@localhost:5432/edgar_test

.PHONY: bootstrap db-up migrate lint typecheck test check phase1-acceptance phase1-corpus-acceptance

bootstrap:
	uv sync --extra dev --locked

db-up:
	docker compose up -d postgres

migrate:
	uv run alembic upgrade head

lint:
	uv run ruff check .

typecheck:
	uv run pyright

test:
	uv run pytest -q -m "not database and not network"
	EDGAR_TEST_DATABASE_URL="$(EDGAR_TEST_DATABASE_URL)" \
	  uv run pytest -q -m "database and not network"

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run pytest -q -m "not database and not network"
	EDGAR_TEST_DATABASE_URL="$(EDGAR_TEST_DATABASE_URL)" \
	  uv run pytest -q -m "database and not network"

phase1-acceptance:
	mkdir -p var/reports
	EDGAR_TEST_DATABASE_URL="$(EDGAR_TEST_DATABASE_URL)" \
	  uv run pytest -q -m "not network" tests/contract tests/integration \
	    --junitxml=var/reports/phase1-acceptance.xml

phase1-corpus-acceptance:
	uv run python scripts/phase1_corpus_acceptance.py
