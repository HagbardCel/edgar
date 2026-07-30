# ADR 0007: Manifest-only offline replay with authoritative URI bindings

- **Status:** Accepted
- **Date:** 2026-07-30

## Context

Slice 0 v1 replayed filings offline from a manifest plus regenerable catalog, but the replay worker could see online-era state, bundle promotion was not atomic, resource relationships (labels/references) were folded into one aggregate relationship hash, and the evidence hash could not cleanly separate semantic identity from operational data. The v1 design also made bundle identity sensitive to regenerable bytes and could not prove that every replay-required URI resolved to verified payload content.

## Decision

Offline replay is **manifest-only**. The replay worker receives exactly three inputs: the sterile manifest bytes (verified against an expected SHA-256), the content-addressed object store, and the serialized `uri-bindings-v1` artifact. No online cache, environment, prior run state, or content-hash fallback is consulted.

1. **Sterile manifest (`manifest-v2-spike`).** The manifest contains no volatile retrieval fields. `payload_hash` is the explicit `payload-v1` construction: SHA-256 over canonical JSON of sorted `{logical_path, sha256, byte_size}` artifact identities. The manifest artifact is never a payload member; `metadata/uri-bindings.json` participates exactly once through a pointer consistent with its artifact entry.

2. **Authoritative URI bindings (`uri-bindings-v1`).** Every canonical URI needed for replay (primary `document_uri` values plus `replay_aliases`) binds to a manifest-listed logical path and content hash. URI identity follows `uri-identity-v1` (scheme/host lowercase, IDNA, default-port removal, fragment removal, exact path/query octets; relative references, credentials, and whitespace rejected). Conflicting object identities, alias collisions, self-binding, unsafe paths, and manifest/hash mismatches are fatal. The manifest entrypoint must be a primary `document_uri`.

3. **Staged promotion.** Candidates validate offline under `.staging/` and promote to `bundles/acq-v1-spike/<payload_hash>/` by atomic rename of the exact validated bytes. Identical promotion identity (policy, manifest schema, entrypoint, payload hash) reuses the existing bundle; any conflict at the final path is fatal; failed candidates move to `.failed/`. Bundle directories contain only `manifest.json`; payload bytes live in the object store.

4. **Occurrence-level relationship identity.** Concept networks (presentation, calculation, definition — including custom definition-link arcroles) are separated from resource networks (concept-label, concept-reference). `relationship_occurrence_hash` covers the arc occurrence and both endpoint occurrences (XLink locator occurrences, local resource occurrences, Clark-notation concept endpoints). Identical semantic traversals through distinct occurrences retain multiplicity. Resource content fingerprints are distinct from resource occurrence identities; a fingerprint match never implies semantic equivalence.

5. **Fail-closed error policy (`arelle-error-policy-v2`).** Every EDGAR filing must be extractable. Engine data-quality diagnostics on filed content (recorded in a recognized non-blocking registry with per-code rationale) never block extraction; they are preserved with full multiplicity. Any unrecognized error code fails the run and forces review.

6. **Non-circular semantic identity (`semantic-run-v1`).** `semantic_run_hash` covers the semantic projections of both load sides, engine identity, schema versions, and success-criterion outcomes — excluding the repeat criterion, raw warnings, and operational fields. Repeat validation (criterion 9) compares payload and semantic run hashes across a full pipeline repeat without self-reference.

7. **Committed evidence.** Evidence is an exact byte copy of the promoted bundle manifest, the URI-bindings artifact, and the inspection core, plus deterministic expectation projections and metadata recording the source commit. `verify_evidence.py` (run locally and in CI) re-validates structure, hashes, binding rules, privacy (no user agents, `file:` URIs, or absolute local paths), semantic-hash recomputation, and provenance: the evidence source commit must be an ancestor of HEAD, and post-implementation changes are restricted to a deny-by-default path allowlist. CI checks out the PR head with full history.

## Validation

Slice 0 v2 rerun (`docs/spikes/0001-arelle-offline-closure.md`, run `20260730T221130Z-ed1b9c75`, source commit `a05f748ad85f36ae7cc89ab2a6489bd8ede2ebfb`): all 10 criteria pass; offline replay completed with network denied from a manifest-seeded cache; online/offline document, edge, relationship, and resource occurrence hashes match; a full repeat reproduced `payload_hash` and `semantic_run_hash`; the bundle promoted atomically; 51 recognized iXBRL transformation diagnostics were recorded without blocking.

## Consequences

- Replay correctness no longer depends on any property of the machine or cache that produced the online run.
- Bundle identity is stable across regenerable outputs and rerun-safe under atomic promotion.
- Resource relationships are first-class evidence for Phase 2 metric mapping; labels/references keep content and occurrence identities distinct.
- New Arelle failure modes cannot slip through silently: unrecognized error codes fail closed.
- Evidence provenance is enforceable in CI; documentation/evidence changes after the implementation commit are the only permitted diffs.

## Alternatives considered

- Copying or freezing the online Arelle cache for replay — rejected; online state leaks into replay identity and is not portable.
- Aggregate relationship-set hashes — rejected; they cannot distinguish occurrences, endpoints, or multiplicity.
- Blocking on any Arelle error — rejected; EDGAR filings routinely trigger engine data-quality diagnostics (e.g. legacy SEC transform namespaces), and no filing may be ignored for incompatibility.
- Free-form waiver lists for run differences — rejected; allowed diffs must name a registered normalization rule.
