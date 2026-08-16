# ADR 0011: Source-schema extraction (V2 cutover)

- **Status:** Accepted
- **Date:** 2026-08-16
- **Supersedes:** [ADR 0008](0008-lean-xbrl-semantic-projection.md) for
  production persistence identity

## Context

Phase 1 persisted XBRL and document evidence as public-schema
`semantic_projection` / `document_projection` rows with attempt metadata and
config-fingerprint identity. Phase 2A remounted mapping explain onto pinned
source evidence. Phase 2B completes the cutover: PostgreSQL’s live surface is
`source.*` only; filesystem FilingBundles remain the offline bytes/replay
contract.

## Decision

1. **V2 Alembic baseline** — Revision `0001_source_v2` creates schema `source`
   and all `SOURCE_TABLES`. Fresh upgrades do not create Phase-1 projection or
   public catalog tables. Phase-1 DBs must be recreated.

2. **Native extract path** — `edgar filings extract` catalogs into
   `source.issuer` / `filing` / `document`, runs the isolated Arelle worker with
   `operation=extract`, receives a lossless native `ReportExtraction` wire
   payload (`extraction_payload`), parses documents, and persists atomically via
   `persist_extraction`. There is no Phase-1 `SemanticProjectionData` wrapper,
   parent-side adaptation, or `source_adapt` step. Provenance
   (`source_document_relative_path`) is resolved inside the extractor.

3. **One item → one fact or fail** — Every yield of the authoritative
   `_iter_item_facts` iterator produces exactly one `FactRecord` whose
   `source_order` is that iterator ordinal, or the report extraction fails.
   Representable unresolved values may persist (`value_status` invalid /
   unresolved / nil). Unrepresentable mandatory identity/context/provenance
   aborts. Counts must satisfy
   `arelle_item_fact_count == len(facts) == persisted source.fact`.

4. **Fail-closed fatality** — Two outcomes only: a complete `ReportExtraction`
   (may carry explicit nonfatal issues) or fatal failure (no
   `ReportExtraction`, no snapshot replacement). Former Phase-1 incomplete
   conditions are fatal unless listed on the V2 nonfatal allow-list
   (`DEFERRED_ARCROLE`, `UNSUPPORTED_ARCROLE`, `EXCLUDED_ARCROLE`, and
   still-emitted fact defects). A fatal failure of any report aborts the entire
   `FilingExtraction`. Persist refuses `severity="fatal"` rows.

5. **No projection identity tables** — Interpretation evidence is filing- and
   report-/document-scoped under `source`. Operational attempt tables and
   verified-reuse projection identity are removed from the live path.
   `SemanticConfig` holds policy knobs only (no `projection_version` /
   config-fingerprint identity).

6. **Arelle adapter retained** — Adapter boundaries, effective networks,
   fail-closed diagnostics, and Decimal/numeric fidelity from ADR 0008 remain.
   Only the PostgreSQL projection lifecycle is superseded.

7. **Registry evidence** — Mapping explain continues to resolve accession +
   expanded QName against `source.*` ([ADR 0010](0010-curated-semantic-registry.md)).

8. **Corpus comparison** — Acceptance uses three layers: (A) internal source
   completeness, (B) re-extraction idempotency, (C) committed cutover probes
   (`fixtures/acceptance/corpus_probes.json`). Canonical Make target:
   `make corpus-acceptance`.

## Consequences

- Docs and AGENTS describe V2 only.
- Residue of Phase-1 projection lifecycle must not remain executable in `src/` /
  tests (`tests/unit/test_residue_deny_list.py`).
- Applicability / candidate selection (formerly sketched as Phase 2B) is deferred
  to Phase 2C+.

## Alternatives considered

- Dual-write Phase-1 + `source.*` indefinitely — rejected; complexity and drift.
- In-place Alembic upgrade from 0004 — rejected; clean V2 baseline is clearer.
- Dropping the Arelle worker — rejected; offline fidelity requires it.
- Parent-side adaptation of Phase-1 projection payloads — rejected; native V2
  wire is the cutover boundary.
