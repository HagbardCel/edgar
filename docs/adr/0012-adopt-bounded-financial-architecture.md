# ADR 0012: Adopt bounded financial architecture and M0–M4 migration

- **Status:** Accepted
- **Date:** 2026-09-07
- **Adopts:** D1–D9 from [docs/architecture/decisions.md](../architecture/decisions.md)
- **Does not supersede:** [ADR 0010](0010-curated-semantic-registry.md) (implemented registry baseline until M2) or [ADR 0011](0011-source-extraction.md) (implemented source-extraction baseline until M1A)

## Context

The [target architecture package](../architecture/README.md) recorded an
independent recommendation for a bounded financial product on top of the Phase
2B `source.*` layer and Phase 2C registry. Until this ADR, that package was not
project-governing: documentation still treated it as a recommendation, and agent
instructions deferred work under the older “Phase 2D+” label.

M0 must convert that recommendation into an adopted migration without claiming
that target behavior is already implemented. Phase 2C assets
(`registry/metrics.yml`, `registry.canonical_metric`, `registry.mapping_assertion`,
migration `0002_registry`) remain the live registry baseline.

## Decision

1. **Adopt D1–D9** as the project's forward architectural decisions:

   | ID | Decision |
   |---|---|
   | D1 | Native XBRL evidence + small application model |
   | D2 | Direct conditional mapping to measurement contracts |
   | D3 | Relational semantic registry; no ontology runtime |
   | D4 | Ordinary SQL + typed Python; no transformation platform yet |
   | D5 | Replaceable source extraction + durable publications/knowledge |
   | D6 | Explicit authority for contracts, decisions and assessment inputs |
   | D7 | Preserve dimensions; defer canonical dimensional rewriting |
   | D8 | Explicit publication policies and multiple knowledge clocks |
   | D9 | One pinned exact-review profile |

2. **Adopt the migration sequence** from
   [migration-plan.md](../architecture/migration-plan.md):

   ```text
   M0 → M1A → M2 → M3 → M4
   ```

   with `M1B` case-triggered evidence enrichment and `M5` evidence-triggered
   extensions. Do not implement a later phase ahead of its gate. Historical
   Phase 2A/2B/2C names remain historical; they are not renamed to M0/M1/M2.

3. **Implemented baseline vs adopted target.** Until the corresponding migration
   phase changes them:

   - [ADR 0010](0010-curated-semantic-registry.md) remains authoritative for the
     **implemented** Git YAML + PostgreSQL mapping-ledger baseline.
   - [ADR 0011](0011-source-extraction.md) remains authoritative for the
     **implemented** `source.*` extraction baseline.
   - [ADR 0005](0005-amendment-restatement-semantics.md)'s conservative rule
     remains valid: an amendment does not imply filing-wide supersession; M4
     will define analytical time-selection behavior.
   - Older ADRs remain historical decisions unless this ADR or a later ADR
     explicitly replaces a forward-looking assumption.

4. **M0 scope.** M0 records adoption, inventories and backs up local knowledge,
   proves restore into the guarded `edgar_test` database, freezes eight initial
   measurement contracts and a bounded independently reviewed benchmark, freezes
   one exact-review profile, and derives a finite M1A requirements table. M0
   makes **no production schema or runtime-code changes**.

5. **Explicit non-goals until later phases.** No observation selector,
   `FinancialRequest`, SQLMesh, ontology/reference warehouse, automatic wider
   mapping reuse, currency conversion, full-history claims, or production
   `metric-v2` hashing until the owning phase implements them.

## Consequences

- Documentation and agent instructions treat the architecture package as the
  **adopted target**, with **current implementation phase: M0** until M0
  acceptance closes.
- Coding agents must not interpret “target adopted” as permission to implement
  M1A/M2/M3/M4 ahead of the phase gate.
- Phase 2B/2C behavior remains live production truth until M1A/M2 modify it.
- The bounded financial benchmark and review profile created in M0 become the
  concrete input to M1A; architecture documents alone are insufficient.

## Alternatives considered

- **Keep the package as a recommendation** — Rejected: M1A cannot start without
  a frozen adoption and benchmark.
- **Rewrite ADR 0010/0011 as if the target were already live** — Rejected:
  would erase the distinction between implemented baseline and adopted migration.
- **Reset to Phase 2B / rewrite `0002_registry`** — Rejected: Phase 2C is the
  retained baseline the new architecture explicitly keeps.
