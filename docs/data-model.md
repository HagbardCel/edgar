# Data model (V2 `source.*`)

**Status:** Authoritative conceptual persistence model after Phase 2B source
cutover.

Physical DDL lives in `src/edgar/db/source_schema.py` and is created by Alembic
revision `0001_source_v2` (CREATE SCHEMA `source` + all `SOURCE_TABLES`).
Fresh `alembic upgrade head` creates **only** `source.*` — no Phase-1
public-schema projection/catalog tables.

Related:

- Architecture: [`architecture.md`](architecture.md)
- Source extraction: [ADR 0011](adr/0011-source-extraction.md)
- Effective networks: [ADR 0004](adr/0004-preserve-xbrl-semantic-networks.md)
- Offline replay / URI bindings: [ADR 0007](adr/0007-manifest-only-replay-uri-bindings.md)
- Immutable raw layer: [ADR 0002](adr/0002-immutable-raw-layer.md)
- Curated registry: [ADR 0010](adr/0010-curated-semantic-registry.md)

Filesystem FilingBundles remain the offline bytes + replay contract. PostgreSQL
holds durable catalog identity and regenerable extraction evidence under
`source`.

---

## 1. Acquisition-owned catalog

```text
source.issuer
  cik                # PK; zero-padded ten-digit string

source.filing
  id                 # PK
  issuer_cik         # FK → issuer.cik
  accession          # unique; canonical dashed form
  form, filing_date, accepted_at, report_period_end, primary_document

source.document
  id                 # PK
  filing_id          # FK → filing.id
  relative_path      # unique per filing
  document_kind, source_url, sha256, byte_size, is_primary
```

Catalog writes are idempotent on accession / filing path. Bytes stay on the
filesystem; `sha256` links to CAS objects.

---

## 2. Shared concept identity

```text
source.concept
  id                 # UUID derived from expanded QName
  namespace_uri, local_name   # unique
```

Exact expanded QName is identity, not economic equivalence. Shared concepts are
upserted during extraction and never garbage-collected by extract replace.

---

## 3. XBRL extraction (report-scoped)

```text
source.xbrl_report
  filing_id + report_key   # unique
  entrypoint / binding provenance, arelle_version, extracted_at, …

source.concept_declaration   # report-scoped declaration of a concept
source.concept_label
source.concept_reference
source.context + source.context_dimension
source.unit + source.unit_measure
source.fact                  # one row per source occurrence (source_order)
source.relationship          # effective presentation / calculation / definition
source.extraction_issue      # filing- and/or report-scoped diagnostics
```

Grain notes:

- Facts and relationships are unique on `(report_id, source_order)`.
- Contexts/units retain source ids within a report.
- Dimensions are structured rows (no opaque `dimensions_json` as identity).
- Extract replace deletes extraction-owned rows for a filing and re-inserts;
  shared `source.concept` rows persist.

---

## 4. Document extraction

```text
source.document_block        # ordinal reading-order blocks per document
source.filing_section        # section_key + block range + confidence
```

Document parsing heuristics remain in `edgar.parsing`; persistence is
document-scoped under `source`, not a separate projection identity table.

---

## 5. Mapping evidence (not stored mappings)

Explain resolves Git mapping pins (`accession` + expanded QName) against
`source.concept_declaration` via every matching `source.xbrl_report` for that
filing. No PostgreSQL registry tables in Phase 2A/2B.

---

## 6. Intentionally absent (removed at V2 baseline)

These Phase-1 public tables are **not** created:

- `filing_bundle`, `content_object`, `bundle_uri_binding`, `xbrl_report_input`, …
- `semantic_projection`, `semantic_projection_attempt`, semantic child tables
- `document_projection`, `document_projection_attempt`, document child tables
- `filing_document`

Existing Phase-1 databases must be dropped/recreated; there is no in-place
upgrade from the deleted 0001–0004 migration lineage.
