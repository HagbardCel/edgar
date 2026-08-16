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

2. **Live extract path** — `edgar filings extract` catalogs into
   `source.issuer` / `filing` / `document`, runs the isolated Arelle worker with
   `operation=extract`, adapts records, parses documents, and persists
   atomically via `persist_extraction`.

3. **No projection identity tables** — Interpretation evidence is filing- and
   report-/document-scoped under `source`. Operational attempt tables and
   verified-reuse projection identity are removed from the live path.

4. **Arelle adapter retained** — Adapter boundaries, effective networks, fail-closed
   diagnostics, and Decimal/numeric fidelity from ADR 0008 remain. Only the
   PostgreSQL projection lifecycle is superseded.

5. **Registry evidence** — Mapping explain continues to resolve accession +
   expanded QName against `source.*` ([ADR 0010](0010-curated-semantic-registry.md)).

## Consequences

- Docs and AGENTS describe V2 only.
- Residue of Phase-1 projection lifecycle must not remain executable in `src/` /
  tests.
- Applicability / candidate selection (formerly sketched as Phase 2B) is deferred
  to Phase 2C+.

## Alternatives considered

- Dual-write Phase-1 + `source.*` indefinitely — rejected; complexity and drift.
- In-place Alembic upgrade from 0004 — rejected; clean V2 baseline is clearer.
- Dropping the Arelle worker — rejected; offline fidelity requires it.
