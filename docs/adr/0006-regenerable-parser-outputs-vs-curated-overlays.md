# ADR 0006: Regenerable parser outputs vs curated overlays

- **Status:** Accepted (amended 2026-08-16 for V2 `source.*`)
- **Date:** 2026-07-30

## Context

The project must support parser improvements without losing reproducibility or expensive human semantic work.

## Decision

Treat three classes of data differently:

1. **Authoritative and immutable** — downloaded SEC artifacts, per-filing manifests, artifact hashes, filesystem FilingBundles.
2. **Regenerable** — `source.*` XBRL and document extraction rows, extraction issues, later derived metrics / research datasets. Replaced atomically per filing on extract rerun.
3. **Curated source data** — human mapping/review decisions: Git-authoritative JSON under `semantic-registry/` (see [ADR 0010](0010-curated-semantic-registry.md)), reviewed via Git and backed up like other source artifacts. PostgreSQL holds `source.*` filing/XBRL evidence and later observations only.

Phase 2 proceeds without re-downloading filings when local bundles exist. All parsed evidence remains fully regenerable from the immutable FilingBundle.

## Consequences

- Regenerable outputs are versioned by parser/Arelle versions recorded on `source.*` rows, not by Phase-1 projection identity tables.
- Manual decisions must not live only in ephemeral parser tables.
- Spike and later slices must keep source payload identity separate from regenerable aids.

## Alternatives considered

- Treat parsed database rows as authoritative — blocks reprocessing after parser fixes.
- Reconstruct human decisions from SEC files — impossible; they are independent source data.
