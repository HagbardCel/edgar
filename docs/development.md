# Development

**Status:** Local development notes for the V2 `source.*` baseline.

## Bootstrap

```bash
make bootstrap
make db-up
make migrate
make check
```

Configure `.env` with `EDGAR_DATA_ROOT`, `EDGAR_DATABASE_URL`, and (for tests)
`EDGAR_TEST_DATABASE_URL=postgresql+psycopg://edgar:edgar@localhost:5432/edgar_test`.

## Migrations

Head revision is `0001_source_v2`: frozen self-contained DDL that creates
schema `source` and all `source.*` tables. `src/edgar/db/source_schema.py` is
live Core metadata, not the historical meaning of revision `0001`.

**Phase-1 databases cannot upgrade in place.** If `alembic_version` still
references the deleted 0001–0004 lineage, drop/recreate the database (or run the
test helper `reset_test_database`) then `alembic upgrade head`.

## Live CLI path

```bash
edgar filings retrieve --accession …
edgar filings catalog --bundle-dir …
edgar filings extract --bundle-dir …
edgar documents sections --document-id …
edgar metrics list|show
edgar mappings list|export|explain
```

## Tests

```bash
EDGAR_TEST_DATABASE_URL=postgresql+psycopg://edgar:edgar@localhost:5432/edgar_test \
  uv run pytest -q -m "database and not network"
uv run pytest -q -m "not network and not database"
uv run ruff check .
make corpus-acceptance   # six-accession local corpus; alias: phase1-corpus-acceptance
```

Integration fixtures call `reset_test_database` so a stale Phase-1 stamp cannot
poison `upgrade head`.

## Boundaries

- No dual-write to Phase-1 projection tables.
- No `scripts/spikes/` imports from production `src/`.
- Offline extract uses the isolated Arelle worker (`operation=extract`) and a
  native lossless `ReportExtraction` wire (`extraction_payload`).
- Fatality is fail-closed; persist refuses `severity="fatal"` issues.
