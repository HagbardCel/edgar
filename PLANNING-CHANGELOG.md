# Planning Artifact Update

## 2026-07-31 — Slice 0 v3 review corrections

- Purified occurrence hashes (xbrl-relationship-v2 / xbrl-resource-v2): document URI + locator only; three-projection model with explicit `canonical_record` / `diagnostic_provenance`; no direct-concept exception.
- Explicit URI provenance (`acq-v2-spike`): `captured_artifact_by_local_path` replaces digest inference; bindings restricted to replay-addressable documents; deterministic primary/alias selection.
- Expanded manifest pointer (`manifest-v3-spike`) with binding count + schema/identity versions; split `validate_manifest_structure` / `validate_uri_bindings_pointer`; strict `uri-bindings-v2` parser.
- Non-circular pre-promotion gate (single-run certification); exact manifest-byte reuse; fail-closed relationship and document-edge extraction (`discovery-v1-spike`, `closure-v1`).
- Strict structured-error comparison; `semantic-run-v2` with error multiplicities and full schema-version map.
- Compact run-generated evidence (`evidence-v2`, `inspection-samples-v1`); exporter-verified full digest; schema-aware privacy.

## 2026-07-30 — Slice 0 review remediation

- Demoted spike report to Failed/Provisional; demoted ADR 0004 to Proposed pending corrected rerun.
- Added ADR 0005 (Accepted): amendment uses directed `amends`, not filing-wide supersession.
- Encoded Phase 1A → parallel 1B/1C → 1D gates and regenerability wording in `phase-1-plan.md` and `project-roadmap.md`.
- Converted `fixtures/corpus.yaml` to real parseable YAML.
- Remediated spike: independent offline subprocess (empty cache + network guard), measured criteria, canonical relationship sets, SGML reconciliation, streaming `fetch_to_store`, immutable bundles vs versioned runs, CI workflow.

## 2026-07-30 — Slice 0 scaffolding

- Removed root planning `manifest.json` (Git is source of truth for repo files).
- Added `README.md`, `LICENSE` (Apache-2.0), `.env.example`, `pyproject.toml`.
- Added `docs/architecture.md`, `docs/fixture-policy.md`, ADRs 0001–0003 (Accepted), 0004/0006 (Proposed).
- Selected spike + five-filing corpus in `fixtures/corpus.yaml` (eBay 10-K/10-K/A, Walmart 10-K, JPM 10-Q, KO 10-Q).
- Implemented Slice 0 spike: `scripts/spikes/arelle_offline_closure.py` + `spike_lib/`.
- Added hashing unit tests; spike report stub at `docs/spikes/0001-arelle-offline-closure.md`.

## Earlier planning updates

### `docs/phase-1-plan.md`

Changes:

- Added XBRL labels and references to Phase 1.
- Added role and arcrole definitions.
- Added presentation, calculation, and definition networks.
- Added inline fact-to-document provenance.
- Expanded schema, CLI, tests, fixtures, and acceptance criteria.
- Clarified that canonical metric mapping remains out of scope.
- Added a Phase 2 readiness gate so mappings can begin without reparsing source filings.

### `AGENTS.md`

Changes:

- Added semantic-fidelity invariants.
- Prohibited name- or label-only metric equivalence.
- Added preservation requirements for taxonomy networks.
- Added later-phase metric mapping rules and LLM restrictions.
- Added relationship-specific test and completion requirements.
- Added references to the full project roadmap and metric-semantics document.
- Updated read-first list for architecture, fixture policy, data-model, and ADRs.

### New: `docs/metric-semantics.md`

Defines:

- raw fact, filed observation, canonical metric, and research feature layers
- metric-family and measurement-contract model
- typed mapping relationships
- global/industry/issuer/period scopes
- candidate generation, hard checks, evidence scoring, validation, and review
- quality tiers
- local-LLM role
- research sensitivity requirements

### New: `docs/project-roadmap.md`

Defines the complete project from product specification through:

1. filing/XBRL foundation
2. metric ontology and mapping
3. period/restatement normalization
4. historical scaling
5. security and market data
6. empirical research datasets
7. filing text intelligence
8. analytical applications
9. operational hardening
