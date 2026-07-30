# Spike 0001: Arelle offline closure

**Status:** Passed (2026-07-30).

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
  working/
  cache/online/
  cache/offline/
  offline-catalog.xml
  manifest.json
  inspection.json
  quality_issues.json
```

## Environment

| Item | Value |
| --- | --- |
| Python (uv project) | 3.12 |
| arelle-release | 2.43.1 |
| Spike script | `scripts/spikes/arelle_offline_closure.py` |
| Acquisition policy | `acq-v0-spike` |
| Catalog generator | `catalog-v0-spike` |

## Live run results (2026-07-30)

### Hashes

| Hash | Value |
| --- | --- |
| `payload_hash` | `163cb7218bf17f3f5fab8aaae629363827028d8993ded8e38f743651efedb77d` |
| `closure_hash` | `5d9619034e9f86852da78cb62a162cf61adfb73729f02718f0df833979bc73f0` |
| `inspection_hash` | `9391e12f48739000412ae0a646bc47a50c03b1279d641d1f118111687ce26020` |
| `catalog_sha256` | `7c53407bd01cdf054a80b14de092e7c7ef074d637d0c87c9a4b1eb8ae50149bb` (excluded from payload) |

Online and offline `closure_hash` matched. `--repeat` reacquisition produced the same `payload_hash`.

### Model counts (online = offline)

| Metric | Count |
| --- | --- |
| Concepts | 18,527 |
| Contexts | 521 |
| Units | 9 |
| Facts | 2,093 |
| Presentation relationships | 655 |
| Calculation relationships | 150 |
| Definition relationships | 1,440 |
| Other relationships | 125 |
| Closure documents | 25 |
| Discovery edges | 75 |

### URI resolution

- Accession entrypoint: `accession/ebay-20231231.htm` (Inline XBRL).
- Online load with isolated Arelle web cache completed with zero unresolved DTS documents.
- External taxonomy/schema/linkbase documents were captured into `external/{sha256_of_uri}/...` and added to the offline catalog.
- Offline reload used `workOffline=True`, a copied cache, and OASIS XML catalog; counts and document sets matched online.

### Fact locator fields (Arelle)

Sampled facts expose:

| Field | Observed |
| --- | --- |
| `id` | Present (e.g. `f-32`) — strong occurrence key candidate |
| `sourceline` | Present |
| `document_uri` | Present |
| `context_id` / `unit_id` | Present |
| `elementXpath` / `xpath_hint` | `None` in samples |

**Decision influence:** prefer `source_inline_id` + source document + sourceline for `occurrence_hash`; do not rely on XPath from Arelle unless a later spike finds a stable alternative.

### Quality issues

1. `info INDEX_JSON_ONLY_ENTRIES` — `index.json` lists SEC-generated renderings (R*.htm, Show.js, etc.) not present in the HTML index table. Expected; directory JSON remains the authoritative accession inventory.

### Success criteria

All 10 criteria **PASS**.

## Bugs found during the run

- Completeness check incorrectly expected `accession/{dashless}.txt`. SEC names the complete submission `accession/{accession}.txt` (dashed). Fixed before recording this report.

## Design notes confirmed

- `metadata/discovery.json` is payload-included; raw submissions JSON is not
- Complete submission kept only under `accession/{accession}.txt`
- Offline catalog stored and hashed but excluded from `payload_hash`
- Inspection JSON uses sorted keys, decimal strings, canonical comparison inputs
- Closure hash uses exact NUL/LF byte serialization

## ADR impact

ADR 0004 (preserve XBRL semantic networks) can move from **Proposed → Accepted**: offline Arelle reload reproduced online closure counts and relationship-network totals for this fixture.

ADR 0006 remains **Proposed** pending durable persistence of regenerable outputs in Slice 1/2, but the catalog-vs-payload separation was validated here.

## Follow-ups for durable slices

1. Normalize Arelle local working-path URIs back to original SEC/HTTP URIs in entry-point and document identity fields.
2. Persist `id` + `sourceline` as occurrence locators in Slice 2 fact model.
3. Treat HTML-index-only vs JSON-only inventory differences as documented reconciliation rules, not fatals.
