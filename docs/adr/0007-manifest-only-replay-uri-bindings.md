# ADR 0007: Manifest-only offline replay with authoritative URI bindings

- **Status:** Accepted
- **Date:** 2026-07-30
- **Updated:** 2026-07-31 (v3 contract corrections)

## Context

Slice 0 v1 replayed filings offline from a manifest plus regenerable catalog, but the replay worker could see online-era state, bundle promotion was not atomic, resource relationships (labels/references) were folded into one aggregate relationship hash, and the evidence hash could not cleanly separate semantic identity from operational data. The v1 design also made bundle identity sensitive to regenerable bytes and could not prove that every replay-required URI resolved to verified payload content.

v2 introduced sterile manifests, URI bindings, occurrence identities, staged promotion, and committed evidence, but review found that occurrence hashes still mixed provenance and resolved semantics, URI aliases could be inferred by content digest, promotion preceded the full semantic gate, committed inspection evidence was unreviewably large, and several completeness/error-identity gaps remained. v3 corrects those contracts without changing the overall architecture.

## Decision

Offline replay is **manifest-only**. The replay worker receives exactly three inputs: the sterile manifest bytes (verified against an expected SHA-256), the content-addressed object store, and the serialized `uri-bindings-v2` artifact. No online cache, environment, prior run state, or content-hash fallback is consulted.

1. **Sterile manifest (`manifest-v3-spike`, acquisition `acq-v2-spike`).** The manifest contains no volatile retrieval fields. `payload_hash` is the explicit `payload-v1` construction over sorted `{logical_path, sha256, byte_size}` artifact identities (unchanged). The URI-bindings pointer carries `logical_path`, `sha256`, `byte_size`, `binding_count`, `schema_version`, and `uri_identity_version`. Validation is split: `validate_manifest_structure` (inventory, uniqueness, payload hash, pointer path/SHA/size) and `validate_uri_bindings_pointer` (bytes vs pointer, parsed count/versions, binding rules). Duplicate logical paths are fatal.

2. **Authoritative URI bindings (`uri-bindings-v2`).** Bindings cover only replay-addressable loaded documents, document-valued replay references, explicit aliases, and the entry point — not images, index pages, headers, complete-submission text, or generated discovery metadata. URI association is established only through explicit local-path/retrieval provenance (`captured_artifact_by_local_path` + accession path map); content SHA verifies an already established association and never creates it. Primary URI selection is deterministic (accession → SEC archive URI; external → capture-designated canonical; additional observations → `replay_alias`). Every serialized URI must already be canonical under `uri-identity-v1`.

3. **Non-circular staged promotion.** Candidates validate under `.staging/`. A pre-promotion gate (independent of success criteria) requires: manifest/bindings valid; offline worker completed; zero network attempts; sterile cache; no unresolved documents; error policy passed; structured online/offline error identity equal; relationship and document-edge extraction complete; strict comparison passed; closure hashes equal; no fatal acquisition/worker issues. Only then does `promote_candidate` atomically rename validated bytes (or reuse an existing final bundle with **exact manifest byte equality**). Promotion certifies a **single-run replay bundle**; Criterion 9 (full-pipeline repeat) runs afterward and is not implied by final-namespace placement. Criterion 6 tests manifest-only replay and network isolation only.

4. **Three-projection occurrence identity (`xbrl-relationship-v2` / `xbrl-resource-v2`).** Occurrence identity is document URI + deterministic locator only. Canonical compared records (explicit inclusion builders) carry resolved semantics and arc/resource content and feed collection hashes. Diagnostic provenance (`source_line`, `xlink:label`) is inspection-only and enters no hash. Direct non-locator concept endpoints are extraction-incomplete. Generic 2008 element-label/element-reference arcroles are explicitly deferred/unsupported-failing. Document edges (`closure-v1` / `discovery-v1-spike`) require a deterministic filed reference occurrence; unrecovered referring elements fail document-edge extraction completeness.

5. **Fail-closed error policy (`arelle-error-policy-v2`).** Unchanged policy: recognized non-blocking diagnostics never block extraction; unrecognized codes fail closed. Rationale for the registered `invalidTransformation` codes is narrowed to retained fact objects, matching online/offline counts, and stable closure — not fact-value fidelity or complete fact occurrence identities. `semantic-run-v2` includes canonical error multiplicities (`code + document URI + multiplicity`) and compares them strictly online/offline.

6. **Non-circular semantic identity (`semantic-run-v2`).** Explicit inclusion of semantic projections, schema versions (including relationship/resource/closure/binding/identity), structured error identity, and document-edge extraction — excluding criterion 9, repeat-derived fields, samples, full-inspection digest, promotion outcome, and the hash's own value.

7. **Compact committed evidence (`evidence-v2` / `inspection-samples-v1`).** The run writes compact `inspection-core.json`, local-only `inspection-full.json`, and mandatory `inspection-samples.json`. Committed evidence is an exact byte copy of the compact core plus bindings, manifest, expectations, samples, and metadata. Samples are review aids only and are excluded from `semantic_run_hash`. `evidence_file_sha256` lists every committed evidence file except `evidence-metadata.json` (no self-digest). The exporter verifies the full-inspection digest locally and records it as non-CI provenance. Privacy checks are schema-aware over known identity/operational fields.

## Validation

Slice 0 v3 rerun (`docs/spikes/0001-arelle-offline-closure.md`, run `20260731T065515Z-ce42ca2f`, source commit `261d658539113a499f95db6527ed3ddedd7ae6d8`): all 10 criteria pass; offline replay completed with network denied from a manifest-seeded cache; online/offline document, edge, relationship, resource, and error-identity hashes match; a full repeat reproduced `payload_hash` and `semantic_run_hash`; the bundle promoted after the pre-promotion gate; 51 recognized iXBRL transformation diagnostics were recorded without blocking; committed inspection-core is compact (~5k lines).

## Consequences

- Replay correctness no longer depends on any property of the machine or cache that produced the online run.
- Bundle identity is stable across regenerable outputs and rerun-safe under atomic promotion with exact-byte reuse.
- Occurrence hashes identify filed locations; extraction disagreements surface as inconsistencies rather than unrelated occurrences.
- URI ownership cannot be inferred from coincidental identical bytes.
- Final-namespace placement means single-run replay validation succeeded, not that Criterion 9 passed.
- Resource relationships remain first-class evidence for Phase 2 metric mapping.
- Committed evidence is reviewable; full exact inspection is retained locally with a provenance digest.

## Alternatives considered

- Copying or freezing the online Arelle cache for replay — rejected; online state leaks into replay identity and is not portable.
- Aggregate relationship-set hashes — rejected; they cannot distinguish occurrences, endpoints, or multiplicity.
- Blessing Clark QName as a direct-endpoint occurrence identity — rejected; no filed locator exists to validate against.
- Digest-inferred URI aliases — rejected; identical bytes must not create URI ownership.
- Blocking on any Arelle error — rejected; EDGAR filings routinely trigger engine data-quality diagnostics, and no filing may be ignored for incompatibility.
- Free-form waiver lists for run differences — rejected; allowed diffs must name a registered normalization rule.
- Committing full relationship arrays — rejected; unreviewable and permanently expands repository history.
