# edgar

Reproducible, point-in-time-aware platform for SEC company filings.

**Status:** Phase 1A filesystem acquisition and Phase 1 catalog foundation are
implemented (`src/edgar/`). Thin Arelle semantic projection (PR #6) is next.

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
# set EDGAR_DATABASE_URL=postgresql+psycopg://edgar:edgar@localhost:5432/edgar
uv run edgar db upgrade
uv run edgar db check
uv run edgar filings catalog --bundle-dir var/bundles/<cik>/<accession>/<opaque_id> --json
```

## Opt-in tests

```bash
uv run pytest -m network tests/contract/test_live_sec_smoke.py
uv run pytest -m database   # requires EDGAR_DATABASE_URL
```

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
