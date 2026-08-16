# ADR 0008: Lean XBRL semantic projection

- **Status:** Accepted
- **Date:** 2026-08-07

## Context

Slice 0 proved that Phase 1 needs Arelle as the authoritative offline XBRL engine, immutable FilingBundles with explicit URI → artifact resolution, effective presentation / calculation / definition relationships, labels and references, and fail-closed handling of unrecognized diagnostics ([ADR 0004](0004-preserve-xbrl-semantic-networks.md), [ADR 0007](0007-manifest-only-replay-uri-bindings.md), [spike conclusions](../spikes/0001-arelle-offline-closure.md)).

ADR 0007 also states that Slice-0 occurrence hashes, `semantic_run_hash`, sterile-manifest ceremony, and related wire formats are verification mechanisms—not mandatory production APIs. Exact production persistence details were deferred to a subsequent ADR.

The provisional Phase 1 plan sketched a model that conflated interpretation identity with execution metadata, treated concept QNames as globally immutable declarations, proposed opaque `dimensions_json`, and risked encoding Slice-0 hash frameworks as production keys. SEC filings may also present a primary Inline XBRL report as a multi-document IXDS, so a singular URI entrypoint is too narrow.

[ADR 0006](0006-regenerable-parser-outputs-vs-curated-overlays.md) (Proposed) discusses regenerable parser outputs versus curated overlays. This ADR makes the narrow XBRL projection decision **independently** and does not depend on ADR 0006 acceptance.

## Decision

Phase 1 uses a **thin Arelle semantic projection**:

1. **Adapter boundary.** Arelle objects stay inside the XBRL adapter. Domain and persistence see resolved semantic records only—not `ModelXbrl`, raw XLink tables, or Slice-0 inspection / hash APIs.

2. **Report input.** An `xbrl_report_input` / replay entrypoint is the complete Arelle load input for one XBRL report: one URI binding, or a deterministically identified collection of URI bindings sufficient to reproduce an IXDS. Ordering-as-identity is deferred. `semantic_projection` identity includes `filing_bundle` + `xbrl_report_input` + projection version + Arelle version + semantic configuration fingerprint. Phase 1 requires the primary SEC IXDS / report; other independently processed report types may be deferred explicitly. Production must not assume one report ≡ one source document URI.

3. **Component-level attempt vs projection.** Interpretation identity (`semantic_projection`) is separate from operational execution metadata (component-level projection attempt). Many attempts may associate with one projection; a projection must not have a single owning attempt id. Zero-or-one cardinality is component-level (one report input), not batch / orchestration. Status is two-level and illustrative (operational vs semantic completeness). `quality_issue` scopes operational vs semantic vs document. Parallel: `document_projection` identity is `(filing_document_id, parser_version, parser_config_fingerprint)` with bundle identity transitive via `filing_document → bundle_artifact`; bundle + parser version alone is insufficient.

4. **Concept identity vs declaration.** Exact expanded QName (`concept_identity`) is distinct from projection-scoped `concept_declaration`. QName identity is not economic equivalence. QName-valued fields use namespace URI + local name (or equivalent); source prefixes never define semantic identity.

5. **Contexts and dimensions.** Normalize reported context dimensions (no canonical `dimensions_json`). Dimension and explicit-member refs are declaration-scoped; retain `context_element` (`segment` | `scenario`). Record filed dimensions only—never invent dimensional default members into context rows. Typed member XML is namespace-complete / lossless; hash is an integrity aid only. Period kinds are `instant` | `duration` | `forever` with no silent coercion. Non-dimensional segment / scenario content is preserved or marks the projection incomplete.

6. **Facts.** One row per source occurrence (binding + deterministic locator). FKs: concept declaration, context, nullable unit. Authoritative source + locator; adapter-retained lexical value (versioned extraction semantics); Arelle resolved typed value where produced; status distinguishes valid / nil / invalid / unresolved. No uniqueness on `(concept, context, unit, value)`. Phase 1 models item facts; unsupported structures (e.g. tuples) fail semantic completeness rather than disappearing.

7. **Relationships.** Persist Arelle effective presentation / calculation / definition networks. Endpoints are concept declarations. **`link_role_uri` and `arcrole_uri` are required**; `network_type` may be stored or derived. Defer raw XLink archaeology.

8. **Labels, references, roles.** Preserve supported concept-label / concept-reference occurrences with distinct `link_role_uri`, `arcrole_uri`, and `resource_role_uri`. Unsupported resource classes fail completeness explicitly. Role and arcrole declarations carry definition, `used_on`, source provenance; arcroles also carry `cycles_allowed`. URI alone is not declaration identity.

9. **Units.** Source unit id, binding + locator, numerator / denominator measures as expanded QNames.

10. **Fail-closed diagnostics.** Unrecognized Arelle diagnostics prevent clean / complete status without mandatory filing discard. A diagnostic may be complete-compatible only when it concerns filed content and the projection faithfully represents affected structures and their semantic validity state (including invalid facts as invalid); any loss of claimed evidence must independently produce a fatal semantic issue. Incoherent materialization may leave no projection.

11. **Provenance and bundle.** Prefer `source_bundle_uri_binding_id` + locator. A FilingBundle comprises payload, report inputs, and URI bindings; `payload_hash` alone (or filing + policy + `payload_hash`) is incomplete bundle identity. No new permanent production `bundle_hash`. No Slice-0 wire formats as production APIs.

Authoritative field-level detail: [`docs/data-model.md`](../data-model.md).

## Consequences

- Implementation PRs (acquisition, catalog, Arelle projection, documents) share one conceptual contract.
- Exact reruns are idempotent at projection identity without deleting prior versions when parser configuration changes.
- Multi-document IXDS and multi-document text parsing remain distinguishable.
- Phase 2 metric mapping can join on exact QName identity without mistaking it for economic equivalence.
- Schema is larger than fact-only extraction, consistent with ADR 0004.

## Alternatives considered

- Singular `entrypoint_binding_id` / one-URI-per-report assumption — rejected; SEC IXDS may be multi-document.
- Document projection keyed only by bundle + parser version — rejected; collisions across documents in one bundle.
- Conflated `semantic_run` mixing interpretation identity with execution metadata — rejected; breaks idempotent reruns.
- Owning `processing_run_id` on projection — rejected; many attempts may revalidate one projection.
- Incomplete filing + policy + `payload_hash` as complete FilingBundle identity — rejected; URI bindings are a separate replay contract.
- Monolithic global `xbrl_concept` equating QName with forever-stable declaration — rejected for issuer extensions and DTS-specific provenance.
- Opaque `dimensions_json` as canonical — rejected; query and mapping needs structured rows.
- Fabricating dimensional defaults into context rows — rejected; defaults live in definition relationships.
- Fact uniqueness on `(concept, context, unit, value)` — rejected; occurrences must survive.
- Relationship endpoints as bare global identities; omitting link / arcrole — rejected; contradicts ADR 0004.
- Prefix-dependent QName identity — rejected; prefixes are serialization.
- Prescribing a new Inline-XBRL “pre-transformation” pseudo-standard in this ADR — rejected; adapter documents versioned extraction; Arelle remains authority.
- Slice-0 hash / promotion frameworks as production APIs — rejected by ADR 0007.
- Full DTS / `ModelXbrl` persistence or Phase-1 tuple persistence — rejected as premature for SEC Phase 1 scope.
