# edgar

Reproducible, point-in-time-aware platform for SEC company filings.

**Status:** Phase 1A–1C and Phase 2A metric registry are implemented: filesystem acquisition,
catalog foundation, thin Arelle semantic projection (PR #6), offline document blocks /
regulatory sections (PR #7), and Git-authoritative metric ontology + curated mapping registry.

Apache-2.0 covers this project's software and documentation. It does **not** automatically license third-party SEC filing content or taxonomies retrieved from EDGAR.

## Principles

- Raw SEC artifacts are immutable and content-addressed.
- PostgreSQL catalogs published FilingBundles; it does not create or validate the durable evidence boundary.
- Parsed outputs are regenerable from source bundles.
- XBRL semantic networks are preserved before metric mapping.
- Offline replay must succeed with network disabled.
- Local LLMs are optional development aids, never required for ingestion or parsing.

## Quick start (production acquisition)

```bash
cp .env.example .env   # set SEC_USER_AGENT to "Name email@example.com"
uv sync --extra dev
uv run edgar filings retrieve --accession 0001065088-24-000036
```

Outputs land under `$EDGAR_DATA_ROOT` (default `var/`):

```text
objects/sha256/{aa}/{sha256}
bundles/{cik}/{accession}/{opaque_id}/bundle.json
acquisition-attempts/{attempt_id}/result.json
locks/{cik}/{accession}.lock
```

Use `--json` for machine-readable output and `--data-root PATH` to override storage.

`filings retrieve` does **not** require PostgreSQL.

## PostgreSQL catalog

```bash
docker compose up -d
# Persistent application database (Settings reads .env):
# EDGAR_DATABASE_URL=postgresql+psycopg://edgar:edgar@localhost:5432/edgar
uv run edgar db upgrade
uv run edgar db check
uv run edgar filings catalog --bundle-dir var/bundles/<cik>/<accession>/<opaque_id> --json
uv run edgar xbrl project --bundle-dir var/bundles/<cik>/<accession>/<opaque_id> --json
uv run edgar documents project --bundle-dir var/bundles/<cik>/<accession>/<opaque_id> --json
uv run edgar documents sections --projection-id <id> --json
uv run edgar metrics sync
uv run edgar metrics list --json
uv run edgar mappings list --json
uv run edgar mappings explain RULE_KEY --json
```

`metrics sync` requires cataloged bundles and semantic projections for every pinned evidence citation in `semantic-registry/mapping-rules.json`. Run corpus catalog/project workflows first (see `scripts/phase2a_acceptance.sh`).

`documents project` defaults to the filing primary HTML document. Pass
`--artifact-path accession/exhibit.htm` to project another eligible HTML
attachment (blocks only; no regulatory sections).

Compose initializes `edgar` (durable) and, on a **fresh** volume, also creates disposable `edgar_test`.
If your volume predates that init script:

```bash
docker compose exec postgres \
  psql -U edgar -d edgar -c "CREATE DATABASE edgar_test"
```

## Opt-in tests

```bash
uv run pytest -m network tests/contract/test_live_sec_smoke.py

# Disposable test database — tests TRUNCATE and migrate this database.
# Must be named exactly edgar_test. Not a Settings field; expose to the process:
# EDGAR_TEST_DATABASE_URL=postgresql+psycopg://edgar:edgar@localhost:5432/edgar_test
uv run --env-file .env pytest -m database
```

Database integration tests refuse to run unless `EDGAR_TEST_DATABASE_URL` targets a database named exactly `edgar_test`. They destructively reset that database. Merely listing the variable in `.env` is not enough for the test helper unless you use `--env-file` (or export it).

## Historical Slice 0 spike

The Slice 0 spike under `scripts/spikes/` remains for verification of frozen evidence and is **not** a production API. Production code does not import it.

## Documentation

| Topic | Document |
| --- | --- |
| System boundaries | [docs/architecture.md](docs/architecture.md) |
| Tables and invariants | [docs/data-model.md](docs/data-model.md) |
| Filesystem FilingBundle (PR #4) | [docs/adr/0009-filesystem-filing-bundle.md](docs/adr/0009-filesystem-filing-bundle.md) |
| Fixture and attachment policy | [docs/fixture-policy.md](docs/fixture-policy.md) |
| Phase sequencing | [docs/phase-1-plan.md](docs/phase-1-plan.md) |
| Roadmap | [docs/project-roadmap.md](docs/project-roadmap.md) |
| Metric semantics (later phases) | [docs/metric-semantics.md](docs/metric-semantics.md) |
| Agent rules | [AGENTS.md](AGENTS.md) |
| Decisions | [docs/adr/](docs/adr/) |

## License

Apache License 2.0. See [LICENSE](LICENSE).
