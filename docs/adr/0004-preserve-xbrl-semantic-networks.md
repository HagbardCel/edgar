# ADR 0004: Preserve XBRL semantic networks

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

Concept names and labels alone do not establish economic equivalence. Later metric mapping needs presentation, calculation, and definition networks, plus labels and references, as filed.

## Decision

Phase 1 persists Arelle’s **effective** relationship set for presentation, calculation, and definition networks, together with labels, references, role/arcrole declarations, contexts, dimensions, units, and facts.

Raw linkbase bytes remain immutable artifacts. Raw-arc tables are deferred until a concrete forensic need appears.

Each effective relationship is represented exactly once in the canonical inspection set, keyed by network type, arcrole, link role, source/target concept QNames, and applicable order/weight/preferred-label/target-role/closed/usable/context-element fields.

## Validation

Corrected Slice 0 rerun (`docs/spikes/0001-arelle-offline-closure.md`, run `20260730T163802Z-da85b81a`) confirmed:

- Online and offline loads in fresh subprocesses produced matching concept/context/unit/fact counts.
- Canonical effective relationship-set hashes matched (`relationship_set_hash`).
- Closure document and discovery-edge sets matched with network denial and a cache that started empty and was seeded only from manifested payload objects.
- Full-pipeline repeat reproduced `payload_hash` and `inspection_hash`.

Fact locator fields are occurrence-model **candidates** for Slice 2; this ADR does not lock an occurrence key.

## Consequences

- Phase 1 schema is larger than fact-only extraction.
- Phase 2 can begin mapping experiments on fixture corpus evidence without re-downloading.
- Parser outputs remain regenerable from the source bundle.

## Alternatives considered

- Facts only in Phase 1 — insufficient for conservative mapping.
- Dual XBRL engines before measuring Arelle gaps — premature complexity.
- Using `baseSets` list lengths as relationship evidence — rejected; not unique effective relationships.
