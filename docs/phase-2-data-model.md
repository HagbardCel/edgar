# Phase 2 data model

**Status:** Authoritative for Phase 2A metric ontology and curated mapping registry.

Related: [ADR 0010](adr/0010-curated-semantic-registry.md), [metric-semantics.md](metric-semantics.md), [phase-2-plan.md](phase-2-plan.md).

Physical schema: `migrations/versions/0004_metric_ontology.py`, `src/edgar/db/schema.py`.

## Git registry files

```text
semantic-registry/
  metric-families.json      # registry_schema_version + families[]
  metric-definitions.json   # registry_schema_version + definitions[]
  mapping-rules.json        # registry_schema_version + rules[] (approved only)
```

All three files must share the same `registry_schema_version`. Immutable records carry their own `definition_schema_version` or `rule_schema_version`.

## Canonicalization (v1)

- UTF-8 JSON, `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`
- Set-valued arrays: canonical sort, reject duplicate elements
- Ordered arrays: preserve order (presentation path, neighborhood order)
- `family_hash` = SHA-256(`{registry_schema_version, code, name, description, parent_code}`)
- `definition_hash` = SHA-256(`canonicalize_definition_v1`)
- `rule_hash` = SHA-256(`canonicalize_rule_v1`) including `evidence_snapshot` and `evidence_citations`
- `registry_hash` = SHA-256(`{registry_schema_version, families_file_hash, definitions_file_hash, rules_file_hash}`)

Reconstruction for verification uses stable keys only (never surrogate DB ids).

## Tables

### `metric_family`

Mutable organizational metadata under stable `code`. Non-removable once imported.

### `metric_definition`

Immutable under `(metric_code, definition_version)`. Columns: contract fields + `constraints` JSONB + `definition_hash`.

### `metric_mapping_rule`

Immutable under `rule_key`. Separate `evidence_snapshot` and `evidence_citations` JSONB. `scope_kind` denormalized from `scope.kind`.

### `semantic_registry_revision`

Append-only log. `registry_hash` indexed, not unique. Latest = highest `id`.

## Mapping rule state

- **Historically approved:** every row in `mapping-rules.json` / DB
- **Current:** no other rule has `supersedes` pointing at this `rule_key`
- **Superseded:** at least one successor references this rule
- **Supersedes:** full retirement; same source QName required

## Evidence citations

Projection-backed kinds share: accession, bundle opaque_id, report input ordinal, projection version, Arelle version, semantic config fingerprint.

`RawArtifactCitation`: accession, bundle opaque_id, logical_path, artifact SHA-256, optional document URI. No projection fields.

Sync resolves each citation to exactly one Phase 1 source object.

## Scope kinds (2A data)

`global`, `issuer`, `issuer_period`, `filing`. For v1 registry data, `issuer_equivalent` requires `issuer_period` or `filing`.

## Explicitly deferred

`metric_observation`, `metric_candidate`, `metric_derivation`, `mapping_review`, industry-scoped rules, `derived_equivalent` data.
