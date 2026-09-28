# ADR 0014: Adopt lean mapping sequence (P0–P6)

- **Status:** Accepted
- **Date:** 2026-09-28
- **Supersedes:**
  - [ADR 0012](0012-adopt-bounded-financial-architecture.md)'s adopted sequence
    `M0 → M1A → M2 → M3 → M4` as the **next implementation order**
  - [ADR 0010](0010-curated-semantic-registry.md) and [ADR 0012](0012-adopt-bounded-financial-architecture.md)
    **write authority** for new mapping decisions in `registry.mapping_assertion`
  - [ADR 0013](0013-publication-critical-taxonomy-evidence.md)'s assignment of
    publication-critical official-taxonomy evidence specifically to **M1A**
- **Retains:**
  - [ADR 0011](0011-source-extraction.md) source-extraction invariants, including
    report-level completeness and integrity
  - exact Clark QName source identity
  - conservative semantic publication
  - existing `registry.mapping_assertion` rows as readable historical state until P3
  - the requirement that an accepted semantic decision carry evidence
- **Authoritative plan:** [docs/assessment-2026-09/plan/](../assessment-2026-09/plan/)

## Context

The September 2026 assessment ([08](../assessment-2026-09/08-migration-plan-assessment.md))
concluded that the remaining M1A–M2 machinery optimizes per-report attestation
before the core mapping-and-selection hypothesis is exercised at scale. Phase 2B/2C
source and registry baselines remain live until later consolidation (P3), but the
**implementation sequence** for canonical values should follow the lean P0–P6 plan:
fix extraction cost, walking skeleton, scale spike, then consolidate.

P0 introduces a shared taxonomy-family classifier and a narrower declaration grain
on `source.*`. That classifier is a host-prefix heuristic until taxonomy-package
provenance replaces it in a later phase.

## Decision

1. **Assurance model.** Mapping and publication quality is measured per policy
   (gold set, identity checks, external oracles), rather than requiring
   per-report or per-occurrence semantic attestation. This does **not** relax
   source-extraction completeness or integrity under ADR 0011.

2. **Mapping authority.** New mapping decisions are Git-reviewed **decision
   records**. The PostgreSQL `registry.mapping_assertion` ledger stays readable
   until P3; do not add new `propose`/`accept` features for the lean path.

3. **Standard-concept continuity.** A decision keyed on namespace **family** and
   local name (for example `us-gaap:Assets`) applies to every US-GAAP release
   where that concept exists, minus any `exclude_qnames`. Family membership uses
   the shared prefix table in `src/edgar/xbrl/taxonomy_family.py` (2009 `xbrl.us`
   and modern `fasb.org` / `xbrl.sec.gov`). Exact Clark QNames remain source
   identity. The rule that treats other `xbrl.sec.gov`, `fasb.org`, and `xbrl.us`
   hosts as `standard` and everything else as `issuer` is a **temporary stand-in**
   until taxonomy-package provenance replaces it; it is not a claim that every
   other namespace is filer-owned.

4. **Selection primitives.** EDGAR required context and XBRL OIM duplicate-fact
   consistency (interval overlap, not rounding to coarser granularity). Affirmative
   definition evidence for standard concepts may come from `MetaLinks.json` or a
   **pinned taxonomy package used as a bounded evidence artifact**. An accepted
   decision requires at least one evidence pointer. Using a package as evidence is
   not a decision to load packages into filing DTS, offline replay, or the
   `source.*` schema.

5. **Paused work.** M1A-4 (inspector), M1A-5 (official-package packets as the
   primary M1A deliverable), and M2 as written are not the next implementation.
   P1–P6 in `docs/assessment-2026-09/plan/` replace that sequence for forward work.

6. **Deferred architecture.** Storage engine choice (PostgreSQL vs DuckDB), and
   whether taxonomy packages become part of general extraction, replay, or source
   data instead of or alongside captured filing closure, wait for P2 measurements
   and a later ADR.

## Consequences

- Documentation and agent instructions treat P1 as the next phase after P0, not
  M1A-4/M2 machinery ahead of the walking skeleton.
- Phase 2C YAML and the mapping ledger remain readable; P1 adds Git decision
  records without deleting ledger history.
- Extractor version `source-extract-v6` narrows persisted declarations to the
  retained keep-set defined in P0; facts, contexts, units, and relationships
  on the acceptance corpus stay unchanged.
- ADR 0010, 0011, 0012, and 0013 remain historical and retained where this ADR
  does not explicitly supersede them.

## Alternatives considered

- **Continue M1A→M2→M3 without sequence change** — Rejected: assessment evidence
  shows late validation of the central mapping hypothesis and extraction cost
  blocking scale work.
- **Delete the mapping ledger in P0** — Rejected: P3 owns consolidation; P0 only
  changes extraction grain and governance.
