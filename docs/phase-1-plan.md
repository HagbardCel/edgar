# edgar — Phase 1 Scaffolding Plan

**Document status:** Reconciled with post–Slice 0 production architecture and [`docs/data-model.md`](data-model.md) (PR #3)

**Phase objective:** Establish a trustworthy, offline-replayable filing and XBRL evidence layer

**Important boundary:** Phase 1 preserves the semantic evidence required for metric mapping, but does not yet create canonical financial metrics.

**Authoritative model:** Conceptual persistence contracts live in [`docs/data-model.md`](data-model.md) and [ADR 0008](adr/0008-lean-xbrl-semantic-projection.md). This plan describes sequencing and capabilities; it must not contradict those documents.

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
- Versioned semantic/document projections plus operational attempts, and structured quality issues
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

Every parsed or projected value must be traceable through the persisted model to its source evidence and logical interpretation:

- accession number / filing
- FilingBundle
- the applicable `semantic_projection` or `document_projection`
- source artifact / URI binding and locator where applicable
- projection/parser version

Operational acquisition and projection attempts remain separately traceable where relevant. Do not require a single owning ingestion run on a projection. Globally reusable identity records need not themselves own a projection when projection-scoped records provide that traceability.

### 4.6 Deterministic core pipeline

The ingestion and parsing path must not require an LLM. Local LLMs may help write code, diagnose failures, propose tests, or rank ambiguous candidates experimentally. Their outputs must never silently replace deterministic source parsing.

### 4.7 Point-in-time semantics from the beginning

Store separately:

- SEC acceptance timestamp
- filing date
- report-period end
- amendment status
- source retrieval time (acquisition observation)
- projection-attempt start/finish timestamps
- projection materialization timestamps if retained as metadata, **never** as interpretation identity

Logical `semantic_projection` / `document_projection` identity remains bundle + report input or parse target + versions/config—not wall-clock time. Multiple attempts may revalidate the same projection.

### 4.8 Small vertical slices and Phase 1 gates

Slice 0 validates the acquisition and offline-replay approach.

After Slice 0:

```text
Slice 0
  → Phase 1A filesystem acquisition
  → DB/catalog foundation
       ├→ Phase 1B XBRL projection
       └→ Phase 1C document projection
  → Phase 1D acceptance
```

Phase 1B and 1C may proceed in parallel after a valid immutable FilingBundle exists **and** catalog foundation is in place. Do not claim that raw retrieval and parsing run in parallel with acquisition: parsers start only after Phase 1A produces a valid immutable bundle and the catalog can record it.

Parser outputs are versioned, regenerable materializations (`semantic_projection` / `document_projection`) of immutable filing bundles, with separate operational attempts. Curated review and mapping decisions are separate, non-regenerable source data that must be transactionally stored, exported and backed up.

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

Content-addressed immutable bytes and FilingBundle identity ([ADR 0001](adr/0001-postgres-and-filesystem.md), [ADR 0002](adr/0002-immutable-raw-layer.md), [`docs/architecture.md`](architecture.md)):

```text
var/   # or configured data root
  objects/
    sha256/
      {aa}/
        {sha256}
  bundles/                 # layout illustrative; implementation may vary
    .../                   # FilingBundle: artifacts, report inputs, URI bindings
  derived/                 # regenerable parser / projection outputs
  cache/
  logs/
```

- Immutable bytes live under `objects/sha256/{aa}/{sha256}`.
- `payload_hash` identifies the deterministic payload snapshot/inventory under the applicable payload-hash contract; exact production hash construction is deferred. URI bindings are a separate replay contract. `payload_hash` is not a complete FilingBundle identity.
- A FilingBundle is an immutable replay snapshot (filing, acquisition policy/version, payload, report inputs, URI bindings)—not an accession-path mutable tree.
- The database stores relative paths, hashes, content types, and provenance. Large source files are not stored as PostgreSQL blobs.

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

Illustrative layout (package name is `edgar`; modules appear as implementation proceeds):

```text
edgar/
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
│   ├── spikes/
│   └── adr/
│       ├── 0001-postgres-and-filesystem.md
│       ├── 0002-immutable-raw-layer.md
│       ├── 0003-no-llm-in-critical-path.md
│       ├── 0004-preserve-xbrl-semantic-networks.md
│       ├── 0005-amendment-restatement-semantics.md
│       ├── 0006-regenerable-parser-outputs-vs-curated-overlays.md
│       ├── 0007-manifest-only-replay-uri-bindings.md
│       └── 0008-lean-xbrl-semantic-projection.md
├── src/
│   └── edgar/
│       ├── cli.py
│       ├── config.py
│       ├── domain/
│       ├── db/
│       ├── sec/
│       ├── storage/
│       ├── ingestion/
│       ├── parsing/
│       ├── xbrl/          # thin Arelle adapter + projection (no ModelXbrl leakage)
│       └── llm/           # optional; never required for canonical path
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── fixtures/
├── scripts/
│   └── spikes/            # historical Slice 0; not a production import surface
├── fixtures/
└── notebooks/
    └── exploration/
```

---

## 7. Phase 1 data model

**Superseded as the authoritative conceptual model.** Use [`docs/data-model.md`](data-model.md) and [ADR 0008](adr/0008-lean-xbrl-semantic-projection.md).

The provisional sketches formerly in this section (global monolithic `xbrl_concept`, opaque `dimensions_json`, production `relationship_hash` / `fact_hash` / `context_hash`, accession-path artifacts as the primary model) are obsolete. Required distinctions that survive include:

- issuer / filing catalog with point-in-time timestamp separation
- FilingBundle, content objects, bundle artifacts, URI bindings, and multi-document `xbrl_report_input` (IXDS)
- component-level projection attempts vs `semantic_projection` / `document_projection` (with `document_parse_target`)
- concept identity vs concept declaration; declaration-endpoint relationships with required `link_role_uri` and `arcrole_uri`
- normalized reported context dimensions (no fabricated defaults); fact occurrences with source + locator and value fidelity
- quality issues scoped to operational vs semantic vs document

Use internal immutable keys, preserve natural identifiers, and enforce uniqueness at the database level when physical schema is introduced. Do not encode Slice-0 serialization or semantic-hash frameworks as permanent production APIs.

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

**Authoritative post–Slice 0 implementation dependency order** (capability names below may still use historical milestone numbers in older prose):

```text
filesystem acquisition → DB/catalog foundation → XBRL / document projections → acceptance
```

Milestone sections below are reordered to match that dependency.

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
- production architecture and conceptual data model ([`docs/architecture.md`](architecture.md), [`docs/data-model.md`](data-model.md), ADR 0008)

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

## Milestone 2 — SEC client, discovery, and filesystem acquisition

### Deliverables

- one shared SEC HTTP client
- identifying user agent
- conservative request limiter
- bounded concurrency
- retry and timeout policy
- submissions parsing
- archive-path resolution
- content-addressed object storage
- immutable FilingBundle publication (artifacts, report inputs, URI bindings)
- offline bundle validation / Arelle smoke load with networking denied
- mocked contract tests
- opt-in live smoke test

Suggested defaults:

```dotenv
SEC_REQUESTS_PER_SECOND=5
SEC_MAX_CONCURRENCY=2
```

### Exit criteria

- one filing can be acquired as a complete, verified immutable FilingBundle with content-object and payload integrity validated.
- verified artifacts are not overwritten with different bytes.
- altered artifacts fail deterministic hash validation.
- offline Arelle load works without network and without ambient cache leakage.
- URI ownership is explicit (SHA equality never creates URI ownership).

---

## Milestone 3 — Database skeleton and catalog foundation

### Deliverables

- SQLAlchemy models aligned with [`docs/data-model.md`](data-model.md)
- initial Alembic migrations
- repositories for:
  - issuers and filings
  - FilingBundles, content objects, artifacts, URI bindings
  - projection attempts / quality issues (as needed for catalog)
  - later: text and XBRL projection tables as those milestones land
- transactional filing / bundle operations

### Exit criteria

- migrations create the Phase 1 catalog schema needed for acquisition persistence.
- repeated inserts do not duplicate natural entities.
- failed operations roll back correctly.
- raw artifacts are not deleted with parser outputs.

---

## Milestone 4 — Filing-document and semantic-block parsing

### Deliverables

- bundle-scoped `filing_document` / `document_parse_target` identity
- `document_projection` keyed by bundle + parse target + parser/config
- ordered block tree
- headings, paragraphs, lists, tables, footnotes, signatures
- source locators (`locator_scheme` + `locator_value`)
- parser-version / projection records
- golden tests

### Exit criteria

- stored blocks reconstruct document reading order.
- every block traces to a source locator.
- multiple documents in one bundle produce distinct document projections.
- exact reruns of the same parse target reuse the same logical projection.
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

## Milestone 6 — Thin Arelle semantic projection (taxonomy and networks)

### Deliverables

- internal XBRL adapter protocol (Arelle objects do not escape the adapter)
- `semantic_projection` for primary `xbrl_report_input` (including multi-document IXDS)
- concept identity vs concept declaration
- supported labels and references (distinct link / arcrole / resource roles)
- role and arcrole declarations
- effective presentation, calculation, and definition relationships (`link_role_uri` + `arcrole_uri` required)
- source URI-binding + locator provenance
- relationship-network inspection CLI

### Exit criteria

- a complete statement presentation tree can be reconstructed for fixture roles, including link-role and arcrole identity.
- calculation weights and orders are preserved.
- extension concepts and relationships are retained.
- concept labels and references are queryable as supported occurrences.
- exact reruns reuse the same logical `semantic_projection`; parser/config changes coexist as new projections.

---

## Milestone 7 — Context, unit, and fact extraction

### Deliverables

- contexts with period kinds `instant` | `duration` | `forever`
- normalized reported dimensions (segment/scenario; no fabricated defaults)
- units with expanded-QName measures
- fact occurrences with concept declaration / context / nullable unit FKs
- retained lexical and Arelle-resolved typed values where produced
- nil / invalid / unresolved distinguishable
- scale/sign/decimals/precision and other interpretation-relevant attributes
- source binding + locator (not Arelle object ids)
- quality rules scoped to semantic projection

### Exit criteria

- facts are queryable by accession, concept, period, dimensions, unit, and statement role.
- exact decimal values round-trip.
- extension facts are retained.
- duplicate source occurrences are not destructively collapsed.
- unrecognized Arelle diagnostics prevent clean/complete status without mandatory filing discard.

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

1. Repository bootstrap and documentation (including production architecture / data model — PR #3).
2. Slice 0 acquisition/offline-replay spike (complete; provenance bounded).
3. Phase 1A — Filesystem-first acquisition foundation (identifiers, CAS storage, SEC client, immutable FilingBundles, offline smoke load).
4. Database / catalog foundation for issuer, filing, and bundle metadata.
5. Phase 1B — Thin Arelle semantic projection and Phase 1C — Document structure in parallel after catalog exists.
6. Phase 1D — Integration, idempotency acceptance, and hardening; retire Slice-0 executable machinery while retaining frozen evidence + minimal immutability guard.
7. Frozen fixture corpus expansion.
8. Provenance inspection commands.
9. Phase 2 mapping-readiness review.

Do not begin canonical metric mapping until Phase 1 fixtures demonstrate reliable taxonomy, network, context, dimensional, and provenance handling.
