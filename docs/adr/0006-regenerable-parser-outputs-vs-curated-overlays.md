# ADR 0006: Regenerable parser outputs vs curated overlays

- **Status:** Proposed
- **Date:** 2026-07-30

## Context

The project must support parser improvements without losing reproducibility or expensive human semantic work.

## Decision (proposed)

Treat three classes of data differently:

1. **Authoritative and immutable** — downloaded SEC artifacts, per-filing manifests, artifact hashes.
2. **Regenerable** — HTML blocks, sections, XBRL rows, parser quality issues, candidate mappings, derived metrics, research datasets, offline catalogs.
3. **Curated source data** — human mapping/review decisions: stored transactionally, backed up, exported to version-controlled YAML/JSON or append-only decision files, pinned by policy releases.

Phase 2 should normally proceed without re-downloading filings and with sufficient parsed evidence for initial mapping. All parsed evidence remains fully regenerable from the immutable source bundle.

## Consequences

- `processing_run` / run-key identity versions regenerable outputs.
- Manual decisions must not live only in ephemeral parser tables.
- Spike and later slices must keep source payload identity separate from regenerable aids such as the offline catalog.

## Alternatives considered

- Treat parsed database rows as authoritative — blocks reprocessing after parser fixes.
- Reconstruct human decisions from SEC files — impossible; they are independent source data.
