# Phase 2 plan

## Phase 2A — complete (Git registry)

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

### Phase 2A exit gate — complete

- 20 v1 metric contracts are Git-authoritative.
- Three Fabian-reviewed real-corpus rules are authoritative at Phase 2A close-out.
- Registry definitions and rules remain Git-only.
- No registry PostgreSQL tables, migrations, sync mechanism, or serialization-version framework were introduced.

## Phase 2B — complete (source cutover)

Cut over live persistence from Phase-1 public projection/catalog tables to V2
`source.*`:

- Alembic baseline `0001_source_v2` creates only `source.*`
- Live path: FilingBundle → `filings catalog|extract` → `source.*`
- Mapping explain remounted on `source.*` evidence pins
- Phase-1 projection packages, attempt tables, and dual-write removed

### Out of scope for Phase 2B (deferred to Phase 2C+)

Formerly sketched as “Phase 2B applicability”:

- Scope-based applicability in explain
- Candidate fact selection / overlapping-rule precedence
- PostgreSQL registry materialization
- `metric_observation` acceptance (Phase 2C)

## Next

Phase 2C+ planning: observations, applicability, and research datasets — only
after a frozen plan.
