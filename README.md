# edgar

Reproducible, point-in-time-aware platform for SEC company filings.

**Status:** Phase 1 foundation. Planning documents are in place; Slice 0 (Arelle offline-closure spike) is the first executable work.

Apache-2.0 covers this project's software and documentation. It does **not** automatically license third-party SEC filing content or taxonomies retrieved from EDGAR.

## Principles

- Raw SEC artifacts are immutable and content-addressed.
- Parsed outputs are regenerable from source bundles.
- XBRL semantic networks are preserved before metric mapping.
- Offline replay must succeed with network disabled.
- Local LLMs are optional development aids, never required for ingestion or parsing.

## Quick start (Slice 0 spike)

```bash
cp .env.example .env   # set SEC_USER_AGENT to "Name email@example.com"
uv sync
uv run python scripts/spikes/arelle_offline_closure.py \
  --cik 0001065088 \
  --accession 0001065088-24-000036
```

Outputs land under `var/spikes/<accession>/` (gitignored):

```text
bundles/<policy>/<payload-hash>/manifest.json
runs/<run-id>/inspection-core.json
runs/<run-id>/run.json
objects/sha256/...
```

Use `--clean --repeat` for a full independent revalidation.

## Documentation

| Topic | Document |
| --- | --- |
| System boundaries | [docs/architecture.md](docs/architecture.md) |
| Tables and invariants | [docs/data-model.md](docs/data-model.md) (after Slice 0) |
| Fixture and attachment policy | [docs/fixture-policy.md](docs/fixture-policy.md) |
| Phase sequencing | [docs/phase-1-plan.md](docs/phase-1-plan.md) |
| Roadmap | [docs/project-roadmap.md](docs/project-roadmap.md) |
| Metric semantics (later phases) | [docs/metric-semantics.md](docs/metric-semantics.md) |
| Agent rules | [AGENTS.md](AGENTS.md) |
| Decisions | [docs/adr/](docs/adr/) |

## License

Apache License 2.0. See [LICENSE](LICENSE).
