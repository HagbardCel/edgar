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

### Out of scope for Phase 2B (delivered in Phase 2C or later)

Formerly sketched as “Phase 2B applicability”:

- PostgreSQL registry materialization (Phase 2C)
- Scope-based applicability / overlapping-rule precedence (Phase 2D+)
- `metric_observation` acceptance (Phase 2D+)

## Phase 2C — complete (canonical registry and mapping ledger)

Git-authoritative metric contracts plus an append-only mapping decision ledger:

- `registry/metrics.yml` and `src/edgar/registry/`
- Alembic `0002_registry`: `registry.canonical_metric`, `registry.mapping_assertion`
- `edgar registry validate|sync`
- `edgar mappings list|show|propose|accept|reject|export`
- Live affected-fact enumeration; no observation selection

Normative contract: [`docs/normalization.md`](normalization.md).
Phase 2A `semantic-registry/` is a historical archive, not live authority.

### Phase 2C exit gate — complete

- YAML metric contracts validate without a database.
- Propose/accept require YAML==mirror; claim identity includes definition hash.
- Rejected is terminal; show displays the named revision.
- Constructed-fixture E2E covers validate → sync → propose → accept → export.

## Next

Phase 2D+ planning: observations, applicability, and research datasets — only
after a frozen plan. Phase 2C publication eligibility is frozen in
[`docs/normalization.md`](normalization.md) and is not implemented here.
