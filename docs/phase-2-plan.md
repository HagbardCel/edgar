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

## Phase 2A exit gate — complete

- 20 v1 metric contracts are Git-authoritative.
- Three Fabian-reviewed real-corpus rules are authoritative at Phase 2A close-out:
  - `map-us-gaap-cash-and-cash-equivalents-equivalent` (`equivalent` / global; accession `0001065088-24-000036`)
  - `map-us-gaap-cash-restricted-combined-broader-than` (`broader_than` / global; accession `0001065088-24-000036`)
  - `map-us-gaap-interest-income-expense-net-incompatible-operating-revenue` (`incompatible` / global; accession `0000019617-24-000453`)
- Every authoritative evidence pin resolves against a complete `arelle-semantic-v2`, ordinal-0 projection.
- Registry definitions and rules remain Git-only.
- No registry PostgreSQL tables, migrations, sync mechanism, or serialization-version framework were introduced.

Phase 1 prerequisite: `diagnostic-policy-v2` and `arelle-semantic-v2` extended faithful representation of the Phase-1D corpus so complete projections could serve as Phase-2A evidence.
