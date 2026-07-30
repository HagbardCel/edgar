# Spike 0001: Arelle offline closure

**Status:** Passed (2026-07-30, corrected remediation rerun).

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
