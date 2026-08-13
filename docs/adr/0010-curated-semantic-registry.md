# ADR 0010: Curated semantic registry

- **Status:** Accepted
- **Date:** 2026-08-13
- **Related:** [ADR 0006](0006-regenerable-parser-outputs-vs-curated-overlays.md) (Accepted; storage-authority detail refined here)

## Context

Phase 2A must define versioned metric measurement contracts and human-reviewed XBRL concept relationships before any automated fact-to-metric mapping. Curated mapping decisions are non-regenerable source data ([ADR 0006](0006-regenerable-parser-outputs-vs-curated-overlays.md)). Phase 1 preserves expanded QName identity and full fact occurrence multiplicity ([ADR 0008](0008-lean-xbrl-semantic-projection.md)).

## Decision

1. **Git JSON is authoritative.** `semantic-registry/` holds metric families, definitions, and approved mapping rules. PostgreSQL is a transactional, queryable materialization only.

2. **Envelope vs record schema versions.** Files carry `registry_schema_version`. Each definition carries `definition_schema_version`; each rule carries `rule_schema_version`. Frozen per-version canonicalizers compute immutable record hashes.

3. **Revision log.** `semantic_registry_revision` is append-only; latest = highest `id`. `registry_hash` is indexed, not unique. Identical consecutive states are not recorded. Same hash as latest → verified no-op after full materialization check.

4. **Families are mutable metadata.** Stable `code`; `family_hash` includes envelope version. Definitions and rules are immutable and non-removable under the same key.

5. **Approved-only registry.** No `mapping_review` table or `review_status`. Every stored rule is a historically human-approved decision. `reviewed_by` / `reviewed_at` are mechanically required; human accountability is governance ([ADR 0003](0003-no-llm-in-critical-path.md)).

6. **Current vs superseded.** Derived from the supersession graph: current = no successor supersedes it; superseded = at least one successor references it. `supersedes` fully retires the predecessor. Precedence among current rules is Phase 2B.

7. **Evidence model.** Separate `evidence_snapshot` (review record) and `evidence_citations` (pinned identities). Projection-backed citations share a projection-identity base; `RawArtifactCitation` does not. Each citation must resolve to exactly one source object at sync. At least one projection-backed citation must involve the rule's source QName.

8. **Cited-projection lifecycle.** Referenced semantic projections remain regenerable but must not be discarded unless identically rematerializable. Snapshots do not substitute for failed citation resolution.

9. **Public reads.** Load Git registry; require `latest.registry_hash == current registry_hash`; else fail with sync required. Then verify complete DB materialization (reconstruct, rehash, compare).

10. **Sync serialization.** Transaction-scoped PostgreSQL advisory lock before reading latest revision.

11. **Scope denormalization.** `scope_kind` must equal `scope.kind` (DB constraint + reconstruction check).

12. **2A data constraints.** `derived_equivalent` rejected in registry data. `issuer_equivalent` requires `issuer_period` or `filing` scope. No `metric_observation` in Phase 2A.

## Consequences

- `edgar metrics sync` materializes Git registry transactionally.
- Mapping rules pin exact projection identity; cleanup of cited projections breaks sync.
- Export JSON/Markdown is audit output only; never accepted by sync.

## Alternatives considered

- Database-only mapping store — loses Git reviewability and authoritative source.
- Single file schema version for all record types — blocks mixed v1/v2 immutable records in one file.
- Unique `registry_hash` — incompatible with mutable family metadata and hash reuse across revision history.
