# Development

**Status:** Local development notes for the V2 `source.*` + `registry.*` baseline.

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

Head revision is `0005_m1a_integrity` (after `0004_m1a_network_identity`):
schema `source` plus schema `registry` (`canonical_metric`, `mapping_assertion`).
Live Core metadata is `src/edgar/db/source_schema.py` and
`src/edgar/db/registry_schema.py`.

**Phase-1 databases cannot upgrade in place.** If `alembic_version` still
references the deleted 0001–0004 lineage, drop/recreate the database (or run the
test helper `reset_test_database`) then `alembic upgrade head`.

## Live CLI path

```bash
edgar filings retrieve --accession …
edgar filings catalog --bundle-dir …
edgar filings extract --bundle-dir …
edgar filings extract --accessions-file fixtures/spike/p2-accessions.txt --jobs 1
edgar documents sections --document-id …
edgar registry validate
edgar registry sync
edgar metrics list|show
edgar rules check
edgar build --check-gold --output-dir var/builds/p1
edgar build --check-gold --quality-report var/reports/p2-quality.json --output-dir var/builds/p1
edgar mappings list|show|propose|accept|reject|export
```

`filings extract --accessions-file` reads one dashed accession per line. It does
not download. Each worker process extracts one accession. The parent writes
`${EDGAR_DATA_ROOT}/reports/p2-extract.json` sorted by accession and exits
non-zero if any accession fails. Successful filings stay committed. Sample
metadata for the quality report lives in `fixtures/spike/p2-sample.csv`, separate
from the accession list. The committed list is the six-filing baseline, not the
500–1,000 census.

`edgar build --quality-report` groups slots by metric, fiscal year, filing
US-GAAP release, and industry bucket. The release comes from concept
declarations before selection (`unknown` or `mixed` when it is not unique).
Oracle columns are `oracle_agree`, `oracle_differ`, `oracle_absent`,
`oracle_ambiguous`, and `oracle_na`. A companyfacts differ does not change the
observation. Cached companyfacts bytes, when present, are loaded from the object
store via `${EDGAR_DATA_ROOT}/companyfacts/CIK##########.sha256`. Build does not
fetch them. `registry.canonical_metric` is not a P1/P2 runtime authority; do not
sync it to make `edgar build` work.

## Tests

```bash
EDGAR_TEST_DATABASE_URL=postgresql+psycopg://edgar:edgar@localhost:5432/edgar_test \
  uv run pytest -q -m "database and not network"
uv run pytest -q -m "not network and not database"
uv run ruff check .
make corpus-acceptance   # six-accession local corpus; alias: phase1-corpus-acceptance
```

### P1 walking-skeleton acceptance (six-filing corpus)

Requires `var/bundles/{cik}/{accession}/…` (or another `EDGAR_DATA_ROOT` with all
six accessions from `fixtures/corpus.toml`), Postgres, and migrated schemas.

```bash
export EDGAR_DATABASE_URL=postgresql+psycopg://edgar:edgar@localhost:5432/edgar
export EDGAR_TEST_DATABASE_URL=postgresql+psycopg://edgar:edgar@localhost:5432/edgar_test
make db-up migrate

EDGAR_DATA_ROOT=var EDGAR_TEST_DATABASE_URL="$EDGAR_TEST_DATABASE_URL" \
  uv run pytest -q tests/integration/test_p1_gold_build.py

EDGAR_DATA_ROOT=var EDGAR_DATABASE_URL="$EDGAR_DATABASE_URL" \
  uv run edgar build --check-gold --output-dir /tmp/edgar-p1-build
```

The integration test resets `edgar_test`, extracts all six bundles, and runs
`run_build(check_gold=True)`. `edgar build` uses the `edgar` database (populate
via the same extracts or your normal ingest workflow).

Integration fixtures call `reset_test_database` so a stale Phase-1 stamp cannot
poison `upgrade head`.

## Boundaries

- No dual-write to Phase-1 projection tables.
- No `scripts/spikes/` imports from production `src/`.
- Offline extract uses the isolated Arelle worker (`operation=extract`) and a
  native lossless `ReportExtraction` wire (`extraction_payload`). M1A-3 runs
  parent-side upstream inventory before the worker, reconciles raw vs worker fact
  counts, validates `integrity.py`, then persists with required upstream evidence
  (`upstream_inventory` on the persist path). SQL NULL/NULL upstream columns are
  legacy rows only; new writes pair `upstream_item_fact_count` with
  `arelle_item_fact_count`.
- Fatality is fail-closed; persist refuses `severity="fatal"` issues.
