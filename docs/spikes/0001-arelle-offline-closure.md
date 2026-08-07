# Spike 0001: Arelle offline closure

**Status:** Passed (2026-07-31, v3 identity/provenance/promotion/evidence corrections; supersedes the v2 rebuild below).

The earlier “10/10” recording was invalidated (copied online cache, unconditional criteria, incorrect relationship/discovery measurements). This report replaces that evidence after an independent offline replay seeded only from the immutable bundle.

## Objective

Validate deterministic accession mirroring, DTS closure capture, and offline Arelle reload before locking the Phase 1 schema.

## Selected accession

| Field | Value |
| --- | --- |
| Company | eBay Inc. |
| CIK | `0001065088` |
| Accession | `0001065088-24-000036` |
| Form | 10-K |
| Filed | 2024-02-28 |
| Period end | 2023-12-31 |

Reason: modern Inline XBRL annual report that also anchors the micro-corpus amendment pair (`0001065088-24-000094`).

## How to run

```bash
cp .env.example .env
# Set SEC_USER_AGENT="Name email@example.com"

uv sync --extra dev
uv run python scripts/spikes/arelle_offline_closure.py \
  --cik 0001065088 \
  --accession 0001065088-24-000036 \
  --clean --repeat
```

Outputs (gitignored):

```text
var/spikes/0001065088-24-000036/
  objects/sha256/...
  bundles/<policy>/<payload-hash>/manifest.json
  runs/<run-id>/
    inspection-core.json
    quality-issues.json
    arelle-online.log
    arelle-offline.log
    run.json
    working/
    cache/offline/   # started empty; seeded from manifest only
  offline-catalog.xml  # under each run; relative paths; excluded from payload_hash
```

## Environment

| Item | Value |
| --- | --- |
| Python (uv project) | 3.12 |
| arelle-release | 2.43.1 |
| Spike script | `scripts/spikes/arelle_offline_closure.py` |
| Acquisition policy | `acq-v0-spike` |
| Catalog generator | `catalog-v0-spike` |
| Run id | `20260730T163802Z-da85b81a` |

## Corrected method (offline independence)

1. Acquire accession into content-addressed objects + draft manifest.
2. Online Arelle load in a **fresh subprocess** with an isolated empty cache.
3. Capture every closure document; map local accession paths to canonical SEC URIs (never as externals).
4. Discard the online cache.
5. Materialize a working tree from manifest objects only.
6. Create a **fresh empty** offline Arelle web cache, then **seed it only from manifested payload objects** using Arelle’s URL→cache-path layout (not a copy of the online cache).
7. Offline Arelle load in a **fresh subprocess** with `workOffline=True`, network denial (`socket` connect hooks + Arelle retrieve guard for uncatalogued HTTP URIs), and regenerable OASIS catalog (relative paths).
8. Compare documents, discovery edges, and canonical effective relationship sets.
9. Repeat the entire pipeline in another fresh run; compare payload and inspection hashes.
10. Write `inspection-core.json` only after the repeat completes.

## Live run results (corrected, 2026-07-30)

### Hashes

| Hash | Value |
| --- | --- |
| `payload_hash` | `31080ff902a7b3e98ca3962e754ad0093940e0d4efff4367b430b00c94147c97` |
| `payload_hash` (repeat) | identical |
| `closure_hash` | `df2ccb67fa74c9d429a54ccd859cfa2d90a3e11e3aa2166976a538e858f85133` (online = offline) |
| `relationship_set_hash` | `5a2e2454a166aea16a035f8055b6dfcc1fecb665de9d7b7cc61657f53111b9e4` (online = offline) |
| `inspection_hash` | `e5f357ce39559a1207a680f5f15b58899ee77426daa89bdef8b74bc89d1b30a5` |
| `inspection_hash` (repeat) | identical |
| `catalog_sha256` | `e1c240e5b6915a27062283a17a8ac0f78d0c099f8560207abf6aa12a46358d81` (excluded from payload) |

### Model counts (online = offline)

| Metric | Count |
| --- | --- |
| Concepts | 18,527 |
| Contexts | 521 |
| Units | 9 |
| Facts | 2,093 |
| Presentation relationships (effective) | 1,516 |
| Calculation relationships (effective) | 241 |
| Definition relationships (effective) | 1,801 |
| Other relationships (effective) | 2,606 |
| Closure documents | 25 |
| Discovery edges | 79 |

Effective relationship totals come from `ModelXbrl.relationshipSet(...).modelRelationships`, deduplicated by canonical relationship key — not from `baseSets` list lengths.

### Offline network evidence (criterion 6)

| Field | Value |
| --- | --- |
| `offline_network_attempt_count` | 0 |
| `offline_cache_started_empty` | true |
| `offline_cache_populated_from_manifest` | true |
| `work_offline` | true |
| `deny_network` | true |

### SGML reconciliation (criterion 3)

Measured fields include `sgml_document_count`, `matched_submitted_files`, `missing_directory_files` (empty), and `generated_directory_extras` (directory-only artifacts such as index/complete-submission files expected to be absent from SGML `<DOCUMENT>` FILENAME inventory). Criterion 3 passed with no missing directory files for SGML filenames.

### Fact locator statistics (full coverage)

| Field | Value |
| --- | --- |
| Facts | 2,093 |
| With `id` | 2,093 (100%) |
| Without `id` | 0 |
| Duplicate IDs within a document | 0 |
| Duplicate IDs across documents | 0 |
| Facts sharing a source line | 2,093 |
| Numeric / non-numeric | 1,908 / 185 |
| Nil facts | 3 |
| Inline facts | 2,093 |
| Continuation-start facts / chains | 0 / 0 |

**Conclusion for Slice 2:** these fields are available **candidates** for the occurrence model. A source line is not an occurrence identifier (many facts share lines). Do not lock `source_inline_id + document + sourceline` from this single filing.

### Success criteria

All 10 criteria **PASS**, with measured fields in `inspection-core.json` for each criterion. No criterion was hard-coded.

## Bugs found / fixed during remediation

- Completeness path used dashed accession for `{accession}.txt` (fixed earlier).
- Offline reload previously copied the online cache — replaced with empty cache + manifest seeding.
- Criteria 6/10 were unconditional; criterion 3 only checked for a complete-submission artifact; criterion 9 reused the first inspection hash — all replaced with measured checks and a real full-pipeline repeat.
- Relationship totals used `baseSets` lengths; discovery edges read singular `referenceType` — replaced with effective `modelRelationships` and plural `referenceTypes` (arcrole before role).
- Local accession files were recaptured as externals — fixed via path→artifact→canonical SEC URI mapping.
- `--accession` path traversal on `--clean` — fixed with strict accession/CIK validation and path containment.
- Bundle identity wrongly treated regenerable catalog bytes as integrity conflicts across runs — payload identity only.

## Design notes confirmed

- `metadata/discovery.json` is payload-included and excludes mutable issuer `company_name`
- Raw submissions JSON is excluded from `payload_hash`
- Complete submission kept under `accession/{accession}.txt`
- Offline catalog is regenerable, relative-path, and excluded from `payload_hash`
- Immutable bundles live under `bundles/<policy>/<payload-hash>/`; execution evidence under `runs/<run-id>/`
- Inspection-core hash excludes absolute paths and raw Arelle logs (logs referenced by SHA-256 only)

## ADR impact

ADR 0004 (preserve XBRL semantic networks) moves **Proposed → Accepted**: offline Arelle reload reproduced online concept/context/unit/fact counts and canonical effective relationship-set hashes for this fixture under independent subprocess isolation and network denial.

ADR 0005 (amendment `amends` semantics) is **Accepted** independently of this spike.

ADR 0006 remains **Proposed** pending durable persistence of regenerable outputs in Phase 1A/1B.

## Follow-ups for durable slices

1. Persist effective relationship records using the canonical key fields validated here.
2. Treat fact locator fields as candidates for the Slice 2 occurrence model; validate continuation chains on a filing that has them.
3. Keep HTML-index-only vs JSON-only inventory differences as documented reconciliation rules, not fatals.

---

## v2 rebuild (2026-07-30): authoritative URI bindings, sterile manifest, occurrence identities

**Status:** All 10 criteria **PASS**. Run id `20260730T221130Z-ed1b9c75`; source commit `a05f748ad85f36ae7cc89ab2a6489bd8ede2ebfb`; committed evidence under `fixtures/manifests/0001065088-24-000036/` (verified offline by `scripts/spikes/verify_evidence.py`, also in CI).

The v2 rebuild replaces the v1 replay contract end to end:

- **Sterile manifest** (`manifest-v2-spike`): no volatile retrieval fields; `payload_hash` built by the explicit `payload-v1` construction over sorted artifact identities; the manifest artifact itself is never a payload member; `uri-bindings.json` participates exactly once via a pointer consistent with the artifact entry.
- **Authoritative URI bindings** (`uri-bindings-v1`): every replay-required canonical URI (document_uris + replay aliases) binds to a manifest-listed logical path and content hash. The entrypoint must be a primary `document_uri`. Binding-rule violations (conflicting object identities, alias collisions, self-binding, manifest/hash mismatches) are fatal.
- **Manifest-only offline worker**: the replay subprocess receives only the sterile manifest bytes (verified against an expected SHA-256), the object store, and the serialized bindings — no online cache, environment, or digest fallbacks. A fresh Arelle web cache is seeded from the bindings; network is denied.
- **Staged promotion**: bundle candidates validate offline under `.staging/` and promote to `bundles/acq-v1-spike/<payload_hash>/` by atomic rename of the exact validated bytes. Identical promotion identity reuses the existing bundle; any conflict at the final path is fatal; failed candidates are moved to `.failed/`.
- **Occurrence identities**: relationships are partitioned into concept networks (presentation, calculation, definition — including custom definition-link arcroles) and resource networks (concept-label, concept-reference). `relationship_occurrence_hash` covers the arc occurrence plus both endpoint occurrences (XLink locator occurrences, local resource occurrences, Clark-notation concept endpoints). Resource `content` fingerprints (exact Unicode text, ordered reference parts with subtree C14N) are distinct from resource `occurrence` identities (document + deterministic element locator).
- **Synthetic partition**: engine-created documents/edges (e.g. inline document sets) are inventoried and hashed separately with their own strict online/offline comparison invariant. eBay fixture: 0 synthetic documents, 0 synthetic edges.
- **Fail-closed error policy** (`arelle-error-policy-v2`): every EDGAR filing must be extractable — engine data-quality diagnostics on filed content never block extraction; unknown error codes fail the run. The 51 deterministic `ix11.10.1.2/ix11.11.1.2:invalidTransformation` diagnostics (legacy SEC transform namespace unrecognized by Arelle's iXBRL 1.1 registry) are recorded with full multiplicity and do not block.
- **Non-circular semantic identity** (`semantic-run-v1`): `semantic_run_hash` covers the semantic projections of both load sides, engine identity, schema versions, and success-criterion outcomes — excluding the repeat criterion, raw warnings, and operational fields. Criterion 9 compares payload and semantic run hashes across a full pipeline repeat.

### v2 hashes and counts (online = offline)

| Item | Value |
| --- | --- |
| `payload_hash` (repeat-identical) | `707e77bf5ce3fa2a7235446a151e4f0d30f057c7d8a8e6ba7030008332b81e59` |
| `closure_hash` | `81676fc69be3a570948a3ad53d29bc3e3795c9e7ff28e1e5b73da7345454b79e` |
| `semantic_run_hash` (repeat-identical) | `399e95c3385f5df9df9571ffd1f1eb4dc688f7d62705db8a45480dcb5283b05f` |
| Concept relationship occurrence hash | `06554a5ce0b400aa253a5959e9ad5dd353c330bded83aa47b14efdb26b34f8b2` |
| Resource relationship occurrence hash | `a0a23b5bbccd8f43f506c1cc78056a0afc7de7417bf3e2384e0b2514be48d412` |
| Bundle artifacts / URI bindings | 186 / 180 |
| Concepts / contexts / units / facts | 18,527 / 521 / 9 / 2,093 |
| Presentation / calculation / definition | 1,516 / 241 / 1,801 |
| Concept-label / concept-reference | 2,190 / 0 |
| Closure documents / discovery edges | 25 / 79 |
| Unstable endpoints / unsupported failing / duplicate inconsistencies | 0 / 0 / 0 |
| Recognized non-blocking diagnostics (ix transforms) | 51 (multiplicity preserved) |

The unsupported-arcrole inventory is exhaustive: every encountered arcrole is classified supported (registry definition arcroles: `all`, `dimension-default`, `dimension-domain`, `domain-member`, `hypercube-dimension`), excluded (none), or unsupported-failing (none).

### v2 evidence and verification

- `fixtures/manifests/0001065088-24-000036/` contains exact byte copies of the promoted `bundle-manifest.json`, `uri-bindings.json`, and `inspection-core.json`, plus deterministic `acquisition-expectations.json` / `parser-expectations.json` projections and `evidence-metadata.json` (source commit, run id, evidence file hashes).
- `scripts/spikes/verify_evidence.py` checks JSON well-formedness, sterile-manifest validity, pointer hash consistency, binding rules, expectation projections, privacy (no user agents, `file:` URIs, or absolute local paths), non-circular `semantic_run_hash` recomputation, and provenance (source commit ancestry; deny-by-default path allowlist for post-implementation changes). CI runs it on every push/PR.

### ADR impact (v2)

ADR 0007 (manifest-only replay with authoritative URI bindings) is **Accepted** with this run. ADR 0004 remains Accepted; its relationship-preservation requirement is now realized with occurrence-level identities rather than aggregate set hashes.

---

## v3 corrections (2026-07-31): purified identities, explicit provenance, compact evidence

**Status:** All 10 criteria **PASS**. Run id `20260731T065515Z-ce42ca2f`; implementation commit `261d658539113a499f95db6527ed3ddedd7ae6d8`; committed evidence under `fixtures/manifests/0001065088-24-000036/` (verified offline by `scripts/spikes/verify_evidence.py`).

v3 corrects the identity and promotion contracts after the v2 review:

- **Three-projection occurrence model** (`xbrl-relationship-v2` / `xbrl-resource-v2`): occurrence identity is document URI + deterministic locator only; canonical compared records carry resolved semantics and arc/resource content; diagnostic provenance (`source_line`, `xlink:label`) enters no hash. Direct non-locator concept endpoints are extraction-incomplete (Clark QName is never an occurrence identity). Inspection records are shaped as `{canonical_record, diagnostic_provenance}`; collection hashes use `canonical_record` only.
- **Explicit URI provenance** (`acq-v2-spike`): `captured_artifact_by_local_path` associates online local paths to exact artifacts; content SHA verifies the association and never selects it. Bindings cover only replay-addressable loaded documents (25 for this fixture), not images/index/headers/complete-submission text. Primary URI selection is deterministic (accession → archive URI; external → capture-designated canonical; additional observations → `replay_alias`).
- **Expanded manifest pointer** (`manifest-v3-spike` / `uri-bindings-v2`): pointer carries `binding_count`, `schema_version`, and `uri_identity_version`; validation is split into `validate_manifest_structure` and `validate_uri_bindings_pointer`, shared by candidate construction, offline worker, and evidence verification. Serialized binding URIs must already be canonical.
- **Non-circular pre-promotion gate**: promotion runs only after strict online/offline equality, extraction completeness (relationships + document edges), error-policy/error-identity success, and network isolation. Promotion certifies a **single-run replay bundle**, not Criterion 9 repeat determinism. Criterion 6 tests manifest-only replay and network isolation only. Exact manifest-byte equality is required on reuse; staging is cleaned after `reused_existing`.
- **Fail-closed extraction**: relationship-set load failures and endpoint-family mismatches fail completeness with stable codes. Generic resource arcroles `http://xbrl.org/arcrole/2008/element-label` and `http://xbrl.org/arcrole/2008/element-reference` are explicitly deferred/unsupported-failing. Document-edge extraction requires a deterministic filed reference occurrence (`closure-v1`); unrecovered referring elements fail completeness (multisets may be retained for diagnosis only).
- **Strict structured-error comparison** (`semantic-run-v2`): online/offline equality over `code + document URI + multiplicity`; source line is evidence-only. The 51 recognized `invalidTransformation` diagnostics prove retained fact objects and stable counts/closure — not fact-value fidelity or complete fact occurrence identities.
- **Compact evidence** (`evidence-v2` / `inspection-samples-v1`): the run writes compact `inspection-core.json`, local-only `inspection-full.json`, and mandatory `inspection-samples.json`. Committed evidence is an exact byte copy of the compact core (~5k lines vs ~874k previously). Samples are excluded from `semantic_run_hash`. The exporter verifies the full-inspection digest locally and records it as non-CI provenance. `evidence-metadata.json` is not self-hashed.

### v3 hashes and counts (online = offline)

| Item | Value |
| --- | --- |
| `payload_hash` (repeat-identical) | `aa744cbb4c56d55163f6fcf37bdd5f519f41c3f97976b55c47ea93536843909a` |
| `closure_hash` | `32c8c2f3ed7fd01c37c5a0aa438feb875da5185f79582501caa08fd57aca020a` |
| `semantic_run_hash` (repeat-identical) | `6a8ad055258229e56477c541eca03732962b601c631671f5c64f063f469efd49` |
| Concept relationship occurrence hash | `180097534c9b9122dd33372c62057785f14b7232526220303c0a0b6efdff8a1f` |
| Resource relationship occurrence hash | `f64dc0655562b24323909e84ac1b720d5f2492ce3ec024438ba864669ccd8be0` |
| Bundle artifacts / URI bindings | 186 / 25 |
| Concepts / contexts / units / facts | 18,527 / 521 / 9 / 2,093 |
| Presentation / calculation / definition | 1,516 / 241 / 1,801 |
| Concept-label / concept-reference | 2,190 / 0 |
| Closure documents / discovery edges | 25 / 79 |
| Unstable endpoints / edge extraction incomplete / duplicate inconsistencies | 0 / 0 / 0 |
| Recognized non-blocking diagnostics (ix transforms) | 51 (multiplicity preserved) |

### ADR impact (v3)

ADR 0007 remains **Accepted** and is amended for the v3 contracts (three-projection identities, explicit provenance, non-circular gate with single-run certification, compact non-self-referential evidence, deferred 2008 generic arcroles).

---

## Conclusions vs production commitments

**Slice 0 establishes semantic and replay requirements, not production module boundaries, persistence schemas, serialization formats, or fixture layout.**

| Carry forward | Do not carry forward as production API/model |
| --- | --- |
| Arelle as authoritative XBRL semantic engine | Replication of `ModelXbrl` / the entire loaded DTS in PostgreSQL |
| Effective presentation, calculation and definition relationships | Raw XLink locator/arc/linkbase tables |
| Immutable filing bundle and deterministic offline replay | Every Slice 0 hash and serialization version |
| Explicit URI→artifact resolution for replay-required documents | `uri-bindings-v2` serialization as a permanent application API |
| Atomic immutable artifact publication | Staged promotion identity / sterile-manifest-v3 ceremony |
| Unknown Arelle diagnostics must not silently yield a successful semantic extraction | `semantic-run-v2` error identity / code+URI+multiplicity hashing and online/offline hash equivalence |
| Arelle-exposed labels and references as semantic inputs for mapping | Generic graph-edge persistence model for resource relationships |
| Source locators where required for provenance or occurrence semantics | Multi-projection occurrence-hash framework |
| Semantic fixture assertions | Giant inspection snapshots as the normal fixture pattern |

The diagnostics invariant is about **truthfulness**, not a prescribed runtime failure mode. Production may retain artifacts and diagnostics and mark extraction incomplete / needs classification; it need not throw away the filing. Exception-versus-status mechanics are a later production design choice.

The committed multi-file evidence package is a Slice 0 verification fixture, not the default production fixture structure.

### Next steps (high-level)

1. Bound Slice-0 provenance (freeze the evidence package, not the repository).
2. Post-spike architecture / data-model simplification.
3. Filesystem-first durable acquisition + offline replay.
4. Database / catalog foundation.
5. Thin Arelle persistence projection.
6. Document text structure.
7. Phase-1 acceptance; retire Slice-0 executable machinery and semantic verifier/CI, while retaining the compact historical evidence package and a minimal byte-immutability check against its boundary commit.
