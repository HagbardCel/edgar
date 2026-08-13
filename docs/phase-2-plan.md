# Phase 2 plan (lean Phase 2A)

## Scope

Git-authoritative semantic registry:

- `semantic-registry/metric-families.json`
- `semantic-registry/metric-definitions.json`
- `semantic-registry/mapping-rules.json`

Python modules:

- `src/edgar/metrics/registry.py` — load, validate, `registry_hash`
- `src/edgar/metrics/service.py` — orchestration
- `src/edgar/metrics/export.py` — DB-free audit ledger
- `src/edgar/db/mapping_evidence.py` — pinned evidence SQL for explain

CLI:

- `edgar metrics list|show`
- `edgar mappings list|export|explain`

## Out of scope (Phase 2A)

- PostgreSQL registry materialization / sync
- Scope-based applicability and candidate fact selection (Phase 2B)
- `metric_observation` acceptance (Phase 2C)

## Exit gate

- 20 corrected metric contracts in Git
- 3–5 reviewed mapping rules with real `bundle_fingerprint` evidence (replace synthetic CI fixtures when corpus is projected)
- `make check` and `make phase1-acceptance` green
- Zero registry DB tables or migrations
