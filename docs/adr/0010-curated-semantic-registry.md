# ADR 0010: Git-authoritative curated semantic registry

## Status

Accepted (lean Phase 2A); amended 2026-08-16 for V2 `source.*` evidence provenance

## Context

Phase 2A introduces a human-reviewed metric ontology and curated XBRL concept→metric mapping registry. Pre-production scope must stay lean: Git JSON is the sole registry store; PostgreSQL holds filing/XBRL evidence only.

## Decision

1. **Git authority** — `semantic-registry/` holds families, metric definitions, and mapping rules. No PostgreSQL registry tables, sync command, revision log, or format-version migration framework.

2. **Economic versioning** — `definition_version` on metric definitions versions economic semantics. Whole-registry `registry_hash` identifies the loaded registry content for provenance.

3. **Evidence identity** — Mapping rules pin `SourceConceptEvidence` using canonical accession + expanded QName only. Explain resolves every matching `source.concept_declaration` across that filing's `source.xbrl_report` rows (one section per report; never merge or pick a single report). Do not pin installation-local opaque ids, bundle fingerprints, or Phase-1 projection versions. Provenance is `source.*` after the Phase 2B cutover ([ADR 0011](0011-source-extraction.md)).

4. **Immutable rule governance** — Approved `rule_key` values are not edited for semantic changes. Corrections add a new `rule_key` with `supersedes`. Superseded rules remain in `mapping-rules.json`. Enforcement is Git review + tests + policy, not DB immutability.

5. **CLI split** — `metrics list/show` and `mappings list/export` read Git only. `mappings explain` resolves pinned source.* evidence against PostgreSQL but does **not** implement scope-based applicability (deferred to Phase 2C+; formerly sketched as Phase 2B).

6. **Pre-production compatibility** — Application supports the current registry shape only. `definition_version` is the sole economic semantics version field. Format changes require editing code, JSON, and tests together. No registry serialization-version framework or upgrade dispatcher.

This ADR refines the storage-authority detail in [ADR 0006](0006-regenerable-parser-outputs-vs-curated-overlays.md): curated metric definitions and mapping rules are Git-authoritative, not PostgreSQL tables.

## Consequences

- Registry changes are reviewed as JSON diffs with deterministic `registry_hash`.
- Evidence portability is verified by resolving accession + QName against `source.*` for any local catalog/extract of that filing (multi-report filings return every matching report).
- Applicability, candidate selection, and overlapping-rule precedence remain deferred past the source cutover.
