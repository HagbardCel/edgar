# ADR 0004: Preserve XBRL semantic networks

- **Status:** Proposed
- **Date:** 2026-07-30

## Context

Concept names and labels alone do not establish economic equivalence. Later metric mapping needs presentation, calculation, and definition networks, plus labels and references, as filed.

## Decision (proposed)

Phase 1 persists Arelle’s **effective** relationship set for presentation, calculation, and definition networks, together with labels, references, role/arcrole declarations, contexts, dimensions, units, and facts.

Raw linkbase bytes remain immutable artifacts. Raw-arc tables are deferred until a concrete forensic need appears.

Acceptance of this ADR depends on Slice 0 confirming that offline Arelle reload reproduces online closure counts and that locator/identity fields needed for fact occurrence keys are available.

## Consequences

- Phase 1 schema is larger than fact-only extraction.
- Phase 2 can begin mapping experiments on fixture corpus evidence without re-downloading.
- Parser outputs remain regenerable from the source bundle.

## Alternatives considered

- Facts only in Phase 1 — insufficient for conservative mapping.
- Dual XBRL engines before measuring Arelle gaps — premature complexity.
