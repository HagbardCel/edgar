# ADR 0004: Preserve XBRL semantic networks

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

Concept names and labels alone do not establish economic equivalence. Later metric mapping needs presentation, calculation, and definition networks, plus labels and references, as filed.

## Decision

Phase 1 persists Arelle’s **effective** relationship set for presentation, calculation, and definition networks, together with labels, references, role/arcrole declarations, contexts, dimensions, units, and facts.

Raw linkbase bytes remain immutable artifacts. Raw-arc tables are deferred until a concrete forensic need appears.

## Validation

Slice 0 (`docs/spikes/0001-arelle-offline-closure.md`) confirmed offline Arelle reload reproduces online concept/context/unit/fact counts and relationship-network totals for eBay `0001065088-24-000036`, with matching closure hashes. Fact occurrence keys should prefer Inline XBRL `id` and `sourceline`; Arelle did not provide usable XPath in sampled facts.

## Consequences

- Phase 1 schema is larger than fact-only extraction.
- Phase 2 can begin mapping experiments on fixture corpus evidence without re-downloading.
- Parser outputs remain regenerable from the source bundle.

## Alternatives considered

- Facts only in Phase 1 — insufficient for conservative mapping.
- Dual XBRL engines before measuring Arelle gaps — premature complexity.
