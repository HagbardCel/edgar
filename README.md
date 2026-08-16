# edgar

Reproducible, point-in-time-aware platform for SEC company filings.

**Status:** Phase 1A–1D and Phase 2A are implemented (`src/edgar/`,
`semantic-registry/`): filesystem acquisition, catalog foundation, thin Arelle
semantic projection (PR #6), offline document blocks / regulatory sections
(PR #7), Phase 1D acceptance (PR #10), and the Git-authoritative curated metric
registry with reviewed real-corpus mappings (PR #11). Current activity is
Phase 2B planning/preparation.

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
```

`documents project` defaults to the filing primary HTML document. Pass
`--artifact-path accession/exhibit.htm` to project another eligible HTML
attachment (blocks only; no regulatory sections).

Compose initializes `edgar` (durable) and, on a **fresh** volume, also creates disposable `edgar_test`.
If your volume predates that init script:

```bash
docker compose exec postgres \
  psql -U edgar -d edgar -c "CREATE DATABASE edgar_test"
```

## Makefile

```bash
make check                 # ruff, pyright, pytest (incl. database marker)
make phase1-acceptance     # complete non-network Phase-1 pytest suite + JUnit
make phase1-corpus-acceptance  # local real-corpus coverage (requires acquired bundles)
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

## Historical Slice 0 evidence

Seven frozen evidence files under `fixtures/manifests/0001065088-24-000036/` are guarded by `tests/contract/test_frozen_slice0_evidence.py`. Historical spike documentation lives under `docs/spikes/`.

## Phase 2A metric registry (Git-only)

```bash
uv run edgar metrics list
uv run edgar mappings list
uv run edgar mappings export --format json
uv run edgar mappings explain <rule_key>   # DB-backed pinned evidence only
```

See [semantic-registry/README.md](semantic-registry/README.md) and [docs/adr/0010-curated-semantic-registry.md](docs/adr/0010-curated-semantic-registry.md).

## Documentation

| Topic | Document |
| --- | --- |
| System boundaries | [docs/architecture.md](docs/architecture.md) |
| Tables and invariants | [docs/data-model.md](docs/data-model.md) |
| Filesystem FilingBundle (PR #4) | [docs/adr/0009-filesystem-filing-bundle.md](docs/adr/0009-filesystem-filing-bundle.md) |
| Fixture and attachment policy | [docs/fixture-policy.md](docs/fixture-policy.md) |
| Phase sequencing | [docs/phase-1-plan.md](docs/phase-1-plan.md) |
| Phase 2A registry | [docs/phase-2-plan.md](docs/phase-2-plan.md) |
| Roadmap | [docs/project-roadmap.md](docs/project-roadmap.md) |
| Metric semantics (later phases) | [docs/metric-semantics.md](docs/metric-semantics.md) |
| Agent rules | [AGENTS.md](AGENTS.md) |
| Decisions | [docs/adr/](docs/adr/) |

## License

Apache License 2.0. See [LICENSE](LICENSE).
