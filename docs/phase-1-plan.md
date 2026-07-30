# EDGAR Scraper — Phase 1 Scaffolding Plan

**Document status:** Updated design baseline  
**Phase objective:** Establish a trustworthy, offline-replayable filing and XBRL evidence layer  
**Important boundary:** Phase 1 preserves the semantic evidence required for metric mapping, but does not yet create canonical financial metrics.

---

## 1. Objective

Build a local, reproducible foundation that can:

1. Discover selected SEC filings for a registrant.
2. Download and preserve the complete source material for each filing.
3. Parse filing metadata, documents, semantic text blocks, regulatory sections, and raw XBRL facts.
4. Preserve the XBRL semantic networks needed for later metric interpretation:
   - labels
   - references
   - role definitions
   - presentation relationships
   - calculation relationships
   - definition/dimensional relationships
   - inline fact-to-document locations
5. Persist those outputs in PostgreSQL with complete provenance.
6. Replay parsing entirely offline from preserved artifacts.
7. Expose a small command-line interface and a stable Python API.
8. Support development with local coding LLMs without making an LLM a runtime dependency of the canonical pipeline.

Phase 1 is successful when one developer can clone the repository, start PostgreSQL, ingest a small deterministic filing set, rerun the pipeline safely, and trace every parsed block, taxonomy relationship, context, unit, and fact back to the original filing artifact.

---

## 2. Why Phase 1 now includes XBRL semantic networks

Raw fact extraction alone is insufficient for reliable metric normalization.

A concept name such as `Revenues`, `SalesRevenueNet`, or a company extension does not by itself establish economic equivalence. Later mapping decisions need evidence about:

- the concept's labels and documentation
- its location in a statement presentation tree
- whether it is a subtotal or component in a calculation tree
- dimensional/domain relationships
- the extended-link role representing the statement
- issuer-specific taxonomy extensions
- historical use in comparable periods
- the exact inline location in the rendered filing

Therefore, Phase 1 must preserve this evidence even though canonical metric mapping remains a Phase 2 concern.

---

## 3. Phase boundary

### In scope

- SEC registrants identified by CIK
- Forms `10-K`, `10-K/A`, `10-Q`, and `10-Q/A`
- Filing discovery through SEC submission metadata
- Retrieval of:
  - filing index
  - primary filing document
  - complete submission text
  - Inline XBRL/XBRL attachments
  - taxonomy schema and linkbases
  - relevant exhibits
- Immutable local raw-artifact storage
- SHA-256 manifests and retrieval provenance
- Filing/document metadata
- Semantic HTML block extraction
- Form-specific section extraction
- Raw Inline XBRL/XBRL extraction:
  - concepts
  - labels
  - references
  - extended-link roles
  - contexts
  - dimensions
  - units
  - facts
  - presentation relationships
  - calculation relationships
  - definition relationships
- Versioned parser runs and structured quality issues
- Local PostgreSQL
- Alembic migrations
- CLI commands
- Unit and integration tests
- Offline fixture replay
- Optional local-LLM client for development experiments and ambiguous-parser diagnostics

### Explicitly out of scope

- Full EDGAR backfill
- `8-K`, `20-F`, `40-F`, `6-K`, proxy statements, and registration statements
- Canonical financial metric definitions
- Concept-to-metric mappings
- Mapping review workflows
- Derived financial metrics
- Market prices, corporate actions, and return labels
- Embeddings or a vector database
- Production LLM-based section or metric extraction
- Distributed queues or orchestration
- Web UI
- Cloud deployment
- Analyst consensus data
- Research dataset generation

These exclusions are architectural guardrails. Phase 1 must leave clean, evidence-rich extension points for later phases.

---

## 4. Architectural principles

### 4.1 Immutable evidence, versioned interpretation

Raw SEC responses and filing artifacts are append-only. Parser outputs may be regenerated and superseded, but source files and their hashes remain unchanged.

### 4.2 Lossless before convenient

Do not collapse distinct concepts, contexts, dimensions, units, relationships, or document occurrences merely because they appear economically similar.

### 4.3 Offline reproducibility

Once an accession has been downloaded, all parsing, validation, and database loading must work without network access.

### 4.4 Idempotency

Repeating discovery, retrieval, parsing, or loading must not create duplicate filings, documents, artifacts, blocks, taxonomy resources, contexts, units, facts, or relationships.

### 4.5 Traceability

Every parsed value must retain enough provenance to locate its source:

- accession number
- filing document
- source artifact and SHA-256
- DOM/XPath or Inline XBRL identifier
- taxonomy/linkbase source
- parser version
- ingestion run

### 4.6 Deterministic core pipeline

The ingestion and parsing path must not require an LLM. Local LLMs may help write code, diagnose failures, propose tests, or rank ambiguous candidates experimentally. Their outputs must never silently replace deterministic source parsing.

### 4.7 Point-in-time semantics from the beginning

Store separately:

- SEC acceptance timestamp
- filing date
- report-period end
- amendment status
- source retrieval time
- parser-run time

### 4.8 Small vertical slices

Implement one complete path before broadening coverage:

```text
CIK
  -> submissions metadata
  -> accession
  -> immutable filing bundle
  -> artifact manifest
  -> filing/document records
  -> semantic blocks and sections
  -> XBRL taxonomy resources and networks
  -> contexts, units, and facts
  -> quality report
```

---

## 5. Local technology stack

### Core

- Python managed with `uv`
- PostgreSQL in Docker Compose
- SQLAlchemy 2-style ORM/Core
- Alembic migrations
- Pydantic settings and boundary models
- `httpx` for SEC HTTP access
- `lxml` for HTML/XML parsing
- Arelle behind an internal adapter
- Typer for the CLI
- pytest
- Ruff
- Pyright or mypy; select one and enforce it consistently

### Deferred until later phases

- DuckDB and Parquet analytical exports
- search index
- vector database
- workflow orchestrator
- cloud object storage

### Local storage

```text
var/
  raw/
    sec/
      {cik_10_digit}/
        {accession_without_dashes}/
          manifest.json
          filing-index.html
          complete-submission.txt
          documents/
          xbrl/
          exhibits/
  derived/
    parser-runs/
  cache/
  logs/
```

The database stores relative paths, hashes, content types, and provenance. Large source files are not stored as PostgreSQL blobs.

### Local LLM interface

```dotenv
LLM_ENABLED=false
LLM_BASE_URL=http://127.0.0.1:1234/v1
LLM_API_KEY=local
LLM_MODEL=
LLM_TIMEOUT_SECONDS=120
```

The repository must remain fully functional with `LLM_ENABLED=false`.

---

## 6. Proposed repository structure

```text
edgar-scraper/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── compose.yaml
├── Makefile
├── .env.example
├── .gitignore
├── alembic.ini
├── migrations/
├── docs/
│   ├── phase-1-plan.md
│   ├── project-roadmap.md
│   ├── metric-semantics.md
│   ├── architecture.md
│   ├── data-model.md
│   ├── fixture-policy.md
│   └── adr/
│       ├── 0001-postgres-and-filesystem.md
│       ├── 0002-immutable-raw-layer.md
│       ├── 0003-no-llm-in-critical-path.md
│       └── 0004-preserve-xbrl-semantic-networks.md
├── src/
│   └── edgar_scraper/
│       ├── cli.py
│       ├── config.py
│       ├── logging.py
│       ├── domain/
│       ├── db/
│       ├── sec/
│       ├── storage/
│       ├── ingestion/
│       ├── parsing/
│       ├── xbrl/
│       │   ├── adapter.py
│       │   ├── arelle_adapter.py
│       │   ├── concepts.py
│       │   ├── resources.py
│       │   ├── relationships.py
│       │   ├── contexts.py
│       │   ├── facts.py
│       │   └── normalize.py
│       └── llm/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── fixtures/
├── scripts/
└── notebooks/
    └── exploration/
```

---

## 7. Phase 1 data model

Use internal immutable keys, preserve natural identifiers, and enforce uniqueness at the database level.

### 7.1 Operational provenance

#### `ingestion_run`

- `id`
- `run_type`
- `started_at`
- `finished_at`
- `status`
- `code_version`
- `config_json`
- `error_summary`

#### `parser_version`

- `id`
- `component`
- `version`
- `git_commit`
- `configuration_hash`
- `created_at`

#### `quality_issue`

- `id`
- `filing_id`
- `document_id`
- `component`
- `severity`
- `code`
- `message`
- `context_json`
- `parser_version_id`
- `created_at`

Example stable codes:

```text
PRIMARY_DOCUMENT_NOT_FOUND
SECTION_SEQUENCE_INVALID
ARTIFACT_HASH_MISMATCH
XBRL_CONTEXT_UNRESOLVED
XBRL_ROLE_UNRESOLVED
XBRL_RELATIONSHIP_ENDPOINT_MISSING
DUPLICATE_FACT_OCCURRENCE
```

### 7.2 Issuer, filing, and artifacts

#### `issuer`

- `id`
- `cik`
- `legal_name`
- `sic`
- `fiscal_year_end`
- timestamps

Unique: `cik`.

#### `filing`

- `id`
- `issuer_id`
- `accession_number`
- `form_type`
- `base_form_type`
- `is_amendment`
- `filed_date`
- `accepted_at`
- `report_period_end`
- `primary_document_name`
- `sec_archive_path`
- `discovered_at`
- `retrieved_at`
- `parse_status`

Unique: `accession_number`.

#### `filing_document`

- `id`
- `filing_id`
- `sequence`
- `filename`
- `document_type`
- `description`
- `content_type`
- `role`
- `is_primary`
- `artifact_id`

#### `artifact`

- `id`
- `filing_id`
- `kind`
- `relative_path`
- `source_url`
- `sha256`
- `byte_size`
- `content_type`
- HTTP metadata
- `retrieved_at`

#### `artifact_manifest`

- `id`
- `filing_id`
- `manifest_version`
- `manifest_sha256`
- `relative_path`
- `created_at`

### 7.3 Text structure

#### `document_block`

- `id`
- `filing_document_id`
- `parent_block_id`
- `ordinal`
- `ordinal_path`
- `block_type`
- `heading_level`
- `plain_text`
- `normalized_text`
- `source_xpath`
- `source_anchor`
- `content_hash`
- `parser_version_id`

Initial block types:

```text
heading
paragraph
list
list_item
table
caption
footnote
signature
other
```

#### `filing_section`

- `id`
- `filing_id`
- `filing_document_id`
- `canonical_section_code`
- `raw_heading`
- `part_number`
- `item_number`
- `ordinal`
- `start_block_id`
- `end_block_id`
- `plain_text`
- `text_hash`
- `extraction_method`
- `confidence`
- `parser_version_id`

### 7.4 XBRL concepts and semantic resources

#### `xbrl_concept`

- `id`
- `taxonomy_uri`
- `namespace`
- `local_name`
- `qname`
- `data_type`
- `period_type`
- `balance_type`
- `substitution_group`
- `is_abstract`
- `is_nillable`
- `is_standard_taxonomy`

Unique identity must account for taxonomy namespace and local name.

#### `xbrl_label`

One concept can have multiple labels.

- `id`
- `concept_id`
- `role_uri`
- `language`
- `text`
- `source_artifact_id`

Examples include standard, terse, verbose, total, negated, period-start, and period-end labels.

#### `xbrl_reference`

- `id`
- `concept_id`
- `role_uri`
- `reference_parts_json`
- `source_artifact_id`

Preserve authoritative reference parts rather than flattening them into one string.

#### `xbrl_role_type`

- `id`
- `filing_id`
- `role_uri`
- `definition`
- `used_on_json`
- `source_artifact_id`

#### `xbrl_arcrole_type`

- `id`
- `filing_id`
- `arcrole_uri`
- `definition`
- `cycles_allowed`
- `used_on_json`
- `source_artifact_id`

### 7.5 XBRL relationship networks

Use a generic relationship table plus typed views or repository methods.

#### `xbrl_relationship`

- `id`
- `filing_id`
- `network_type`
- `role_uri`
- `arcrole_uri`
- `source_concept_id`
- `target_concept_id`
- `order_value`
- `weight`
- `preferred_label_role`
- `closed`
- `usable`
- `target_role_uri`
- `attributes_json`
- `source_artifact_id`
- `relationship_hash`
- `parser_version_id`

`network_type` initially includes:

```text
presentation
calculation
definition
```

This table must preserve issuer extension relationships as filed.

### 7.6 Contexts, units, and facts

#### `xbrl_context`

- `id`
- `filing_id`
- `source_context_id`
- `entity_identifier`
- `period_type`
- `period_start`
- `period_end`
- `instant_date`
- `dimensions_json`
- `scenario_xml_hash`
- `context_hash`

#### `xbrl_unit`

- `id`
- `filing_id`
- `source_unit_id`
- `numerator_measures_json`
- `denominator_measures_json`
- `canonical_unit`
- `unit_hash`

#### `xbrl_fact`

- `id`
- `filing_id`
- `filing_document_id`
- `concept_id`
- `context_id`
- `unit_id`
- `raw_value`
- `numeric_value`
- `text_value`
- `decimals`
- `precision`
- `scale`
- `sign`
- `is_nil`
- `inline_fact_id`
- `source_xpath`
- `source_artifact_id`
- `fact_hash`
- `parser_version_id`

Financial values use Python `Decimal` and PostgreSQL `NUMERIC`.

Do not deduplicate facts solely because concept, context, unit, and value are equal. Preserve source occurrences or explicitly represent occurrence equivalence.

---

## 8. CLI contract

```bash
# Infrastructure
uv run edgar db check
uv run edgar db upgrade

# Discovery
uv run edgar filings discover \
  --cik 0000320193 \
  --forms 10-K,10-Q \
  --since 2024-01-01

# Retrieval
uv run edgar filings retrieve \
  --accession 0000320193-25-000079

# Offline parsing
uv run edgar filings parse \
  --accession 0000320193-25-000079 \
  --offline

# Bounded end-to-end sync
uv run edgar filings sync \
  --cik 0000320193 \
  --forms 10-K,10-Q \
  --since 2024-01-01 \
  --limit 8

# Inspection
uv run edgar filings show --accession ...
uv run edgar filings issues --accession ...
uv run edgar xbrl concepts --accession ...
uv run edgar xbrl network --accession ... --role-uri ... --type presentation
uv run edgar xbrl facts --accession ... --concept ...

# Fixture validation
uv run pytest tests/integration/test_fixture_replay.py
```

Every mutating command should support, where meaningful:

- `--dry-run`
- `--json`
- deterministic non-zero exit codes
- idempotent reruns

---

## 9. Milestones

## Milestone 0 — Decisions and invariants

### Deliverables

- repository initialized with `uv`
- `AGENTS.md`
- Phase 1 plan
- project roadmap
- metric-semantics specification
- architecture decision records
- `.env.example`
- fixture policy

### Exit criteria

A new contributor can identify project scope, commands, semantic invariants, and phase boundaries from repository documentation alone.

---

## Milestone 1 — Development environment and quality gates

### Deliverables

- `pyproject.toml`
- pinned `uv.lock`
- Compose PostgreSQL
- configuration and structured logging
- Ruff, type checker, pytest
- test markers
- developer commands

### Exit criteria

- `make check` succeeds from a clean clone after documented setup.
- unit tests require no network or database.
- integration tests run against local PostgreSQL.

---

## Milestone 2 — Database skeleton and repositories

### Deliverables

- SQLAlchemy models
- initial Alembic migrations
- repositories for:
  - issuers
  - filings
  - artifacts
  - text
  - XBRL taxonomy resources
  - XBRL relationships
  - contexts, units, and facts
  - quality issues
- transactional filing operations

### Exit criteria

- migrations create the complete Phase 1 schema.
- repeated inserts do not duplicate natural entities.
- failed operations roll back correctly.
- raw artifacts are not deleted with parser outputs.

---

## Milestone 3 — SEC client, discovery, and raw retrieval

### Deliverables

- one shared SEC HTTP client
- identifying user agent
- conservative request limiter
- bounded concurrency
- retry and timeout policy
- submissions parsing
- archive-path resolution
- atomic retrieval
- artifact manifests
- offline bundle validation
- mocked contract tests
- opt-in live smoke test

Suggested defaults:

```dotenv
SEC_REQUESTS_PER_SECOND=5
SEC_MAX_CONCURRENCY=2
```

### Exit criteria

- one filing can be downloaded as a complete hashed bundle.
- verified artifacts are not unnecessarily redownloaded.
- altered artifacts fail deterministic hash validation.
- downstream parsing works without network access.

---

## Milestone 4 — Filing-document and semantic-block parsing

### Deliverables

- deterministic primary-document selection
- ordered block tree
- headings, paragraphs, lists, tables, footnotes, signatures
- source locators
- stable content hashes
- parser-version records
- golden tests

### Exit criteria

- stored blocks reconstruct document reading order.
- every block traces to a source locator.
- same parser version produces stable hashes.
- normalization edge cases are tested.

---

## Milestone 5 — Regulatory section extraction

### Initial vocabulary

For `10-K`:

```text
part_1.item_1.business
part_1.item_1a.risk_factors
part_1.item_1b.unresolved_staff_comments
part_1.item_1c.cybersecurity
part_2.item_7.mda
part_2.item_7a.market_risk
part_2.item_8.financial_statements
```

For `10-Q`:

```text
part_1.item_1.financial_statements
part_1.item_2.mda
part_1.item_3.market_risk
part_1.item_4.controls_and_procedures
part_2.item_1.legal_proceedings
part_2.item_1a.risk_factors
```

### Extraction logic

1. Generate candidates.
2. Apply normalized form-specific patterns.
3. distinguish table-of-contents occurrences.
4. enforce valid part/item ordering.
5. select boundaries.
6. persist confidence and method.
7. emit structured issues for missing or ambiguous sections.

### Exit criteria

- fixture sections are extracted correctly.
- table-of-contents headings are not selected as body sections.
- missing sections create warnings, not fabricated text.
- section text is reproducibly derived from source blocks.

---

## Milestone 6 — XBRL taxonomy and semantic-network extraction

### Deliverables

- internal XBRL adapter protocol
- Arelle adapter
- concepts and schema attributes
- labels and references
- role and arcrole definitions
- presentation relationships
- calculation relationships
- definition/dimensional relationships
- source-artifact provenance
- relationship-network inspection CLI

### Exit criteria

- a complete statement presentation tree can be reconstructed for fixture roles.
- calculation weights and orders are preserved.
- extension concepts and relationships are retained.
- concept labels and references are queryable by role and language.
- relationship endpoints and role references validate.

---

## Milestone 7 — Context, unit, and fact extraction

### Deliverables

- instant and duration contexts
- explicit and typed dimensions
- units
- numeric and non-numeric facts
- nil facts
- scale/sign/decimals/precision
- inline document positions
- stable hashes
- quality rules

### Exit criteria

- facts are queryable by accession, concept, period, dimensions, unit, and statement role.
- exact decimal values round-trip.
- extension facts are retained.
- duplicate source occurrences are not destructively collapsed.

---

## Milestone 8 — End-to-end fixture acceptance

### Fixture corpus

Use approximately six to ten heterogeneous filings:

- at least two `10-K`
- at least two `10-Q`
- at least one amendment
- multiple industries
- material extension concepts
- awkward HTML
- dimensional disclosures
- multiple statement roles
- at least one taxonomy transition case

### Acceptance command

```bash
make phase1-acceptance
```

It should:

1. verify PostgreSQL
2. apply migrations
3. load frozen raw fixtures
4. parse all fixtures offline
5. validate hashes
6. validate expected sections
7. validate taxonomy resources and network counts
8. validate facts and contexts
9. rerun the same pipeline
10. confirm stable hashes and no duplicate rows
11. produce a machine-readable report

### Exit criteria

- full acceptance succeeds offline.
- second run changes no canonical row counts.
- failures identify accession, component, issue code, and source.
- XBRL statement trees and facts can be traced to original artifacts.
- Phase 2 can evaluate metric mappings without reparsing source files.

---

## 10. Phase 1 demonstration queries

At completion, document queries for:

- filing inventory
- extracted sections
- concepts with all labels
- statement presentation tree
- calculation children and weights
- dimensional domain/member relationships
- facts for a concept
- fact-to-document provenance
- parser and artifact lineage

A Phase 2 readiness query should return, for one filed fact:

```text
issuer and accession
concept QName
all labels and references
statement role
presentation parents and children
calculation parents and children
period and dimensions
unit
value
inline source location
artifact hash
parser version
```

---

## 11. Testing strategy

### Unit tests

Cover:

- CIK and accession normalization
- SEC URL construction
- manifest hashing
- atomic writes
- rate limiting with fake time
- HTML normalization
- section candidate generation
- section sequence resolution
- taxonomy resource parsing
- relationship normalization
- exact decimal parsing
- stable hashes

### Integration tests

Cover:

- migrations
- repositories and rollback
- offline fixture replay
- idempotency
- block and section persistence
- taxonomy resource persistence
- network reconstruction
- context/unit/fact persistence
- provenance queries

### Golden tests

Golden updates must be explicit and reviewed. A parser change must not automatically rewrite expected outputs.

### Core invariants

- timestamps are timezone-aware
- artifact hashes match files
- section ranges are ordered
- duration contexts have start/end
- instant contexts have instant date
- facts use exact decimal semantics
- relationship endpoints exist
- network roles resolve
- reprocessing does not increase row counts
- raw distinctions are not lost

---

## 12. Definition of Phase 1 done

- [ ] Clean local setup is reproducible.
- [ ] PostgreSQL schema is migration-managed.
- [ ] Bounded filings can be discovered and retrieved.
- [ ] Every artifact has a verified SHA-256 manifest entry.
- [ ] Parsing replays with network disabled.
- [ ] Filing documents become ordered semantic blocks.
- [ ] Target sections are extracted with provenance.
- [ ] XBRL concepts and schema properties are persisted.
- [ ] Labels and references are persisted.
- [ ] Role and arcrole definitions are persisted.
- [ ] Presentation, calculation, and definition networks are persisted.
- [ ] Contexts, dimensions, units, and facts are persisted.
- [ ] Numeric facts use exact decimals.
- [ ] Inline fact locations are retained where available.
- [ ] Parser outputs reference parser versions.
- [ ] Quality issues are structured and queryable.
- [ ] Fixture acceptance is deterministic and idempotent.
- [ ] Local LLMs are optional and isolated.
- [ ] Metric mapping can begin without reparsing raw filings.
- [ ] `make check` and `make phase1-acceptance` pass.

---

## 13. First implementation sequence

1. Repository bootstrap and documentation.
2. Identifier value objects.
3. Storage abstraction, atomic writes, and manifests.
4. PostgreSQL schema and migrations.
5. SEC client and submissions discovery.
6. Filing-bundle retrieval and offline validation.
7. Frozen fixture corpus.
8. Semantic HTML parser.
9. Regulatory section extractor.
10. XBRL concepts, labels, references, and roles.
11. Presentation/calculation/definition networks.
12. Contexts, units, and facts.
13. Provenance inspection commands.
14. End-to-end idempotency acceptance.
15. Phase 2 mapping-readiness review.

Do not begin canonical metric mapping until Phase 1 fixtures demonstrate reliable taxonomy, network, context, dimensional, and provenance handling.
