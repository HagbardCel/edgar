# AGENTS.md

## Project mission

Build a reproducible, point-in-time-aware platform for SEC company filings.

The system preserves immutable filing evidence; parses deterministic document structure and XBRL semantics; creates versioned canonical metrics; joins filings to historical securities and market outcomes; and supports reproducible quantitative and textual research.

**Phase 2A is complete.** **Phase 2B source cutover is complete.** **Phase 2C
canonical registry and mapping ledger is complete.** Do not implement
applicability, candidate selection, or `metric_observation` until a frozen
Phase 2D+ plan exists. Phase 2A/2B/2C invariants remain in force.

See `docs/phase-2-plan.md`, `docs/normalization.md`,
[ADR 0010](docs/adr/0010-curated-semantic-registry.md),
and [ADR 0011](docs/adr/0011-source-extraction.md).

Optimize for:

- correctness
- provenance
- semantic fidelity
- idempotency
- offline replay
- testability
- conservative interpretation

Do not optimize for breadth or ingestion speed before the relevant phase gate is satisfied.

---

## Read this first

Before changing code:

1. Read this file.
2. Read `docs/phase-2-plan.md` and `docs/phase-1-plan.md`.
3. Read `docs/project-roadmap.md`.
4. Read `docs/architecture.md`, `docs/development.md`, `docs/normalization.md`, and `docs/fixture-policy.md`.
5. Read `docs/data-model.md` and `docs/data-quality.md`.
6. Read `docs/metric-semantics.md` for any XBRL or financial-metric work.
7. Read relevant ADRs under `docs/adr/`.
8. Inspect nearest tests and interfaces.
9. Check the git diff before editing.
10. Keep the change within completed Phase 2A/2B/2C invariants unless the task
    explicitly changes scope. Do not implement Phase 2D+ until its plan is frozen.

Priority when requirements conflict:

1. source integrity and semantic correctness
2. explicit user requirements
3. documented invariants and tests
4. ADRs
5. existing conventions
6. convenience

Never infer success from plausible code. Run the relevant checks.

---

## Phase 2A invariants (historical Git registry)

Phase 2A is complete and **superseded as live mapping authority** by Phase 2C.
Retain the historical tree under `semantic-registry/` as an archive only.

- Historical Git JSON families / v1 metric definitions / mapping-rules
- Historical `definition_version` + whole-registry `registry_hash`
- Do not load `semantic-registry/` from production code

## Phase 2C invariants (canonical registry and mapping ledger)

Phase 2C is complete. Continue to maintain:

- Git-authoritative `registry/metrics.yml` (reported metric contracts)
- `definition_hash` (mapping-review hash) and semantic registry hash
- PostgreSQL `registry.canonical_metric` as a YAML mirror (not definition authority)
- Append-only `registry.mapping_assertion` ledger; claim identity includes
  `target_definition_hash` and is copied, never rewritten
- `propose`/`accept` require YAML == mirror on all mirrored fields
- Accept requires candidate hash == current YAML hash; rejected is terminal
- `edgar registry validate|sync`, `edgar metrics list|show`, `edgar mappings list|show|propose|accept|reject|export`
- Live affected facts via `contains()`; no durable `source_fact_ids`

## Phase 2B invariants (source cutover)

Phase 2B is complete. Continue to maintain:

- PostgreSQL live surface is `source.*` only (Alembic `0001_source_v2`)
- Live path: immutable FilingBundle → `filings catalog|extract` → native
  `ReportExtraction` → `source.*`
- No Phase-1 projection/attempt tables, dual-writes, or projection CLI commands
- Phase-1 DBs must be recreated (no in-place upgrade from deleted 0001–0004)

Do not add without an explicit frozen Phase 2D+ plan:

- `semantic.*` / `metric_observation` or canonical fact acceptance
- automated mapping candidates or precedence among current rules
- LLM auto-approval of mappings
- SQLMesh or observation-selection policy

---

## Active foundations scope

Implement and maintain:

- SEC discovery for `10-K`, `10-K/A`, `10-Q`, `10-Q/A`
- immutable raw filing retrieval and manifests
- filesystem FilingBundle publish/load + offline replay
- `source.*` catalog and extraction (XBRL + documents)
- XBRL concepts, labels, references, relationships, contexts, units, facts
- document blocks and regulatory sections
- local PostgreSQL (`source` and `registry` schemas)
- deterministic offline fixtures
- CLI workflows (`filings`, `documents sections`, `metrics`, `registry`, `mappings`)
- optional local-LLM development experiments

Do not add without explicit scope change:

- derived financial metrics / observations
- security-master or market data
- research dataset generation
- embeddings or vector databases
- web applications
- distributed queues
- cloud infrastructure
- production LLM dependencies
- additional filing forms

---

## Non-negotiable invariants

### Source artifacts

- Raw SEC artifacts are immutable.
- Never overwrite verified bytes with different bytes.
- Every artifact has a SHA-256 hash.
- Write atomically using a temporary file and rename.
- Store paths relative to the configured data root.
- Parsing must work with network disabled.
- Frozen fixtures change only through the explicit refresh workflow.

### Identifiers

- CIKs are zero-padded ten-digit strings.
- Accession numbers use canonical dashed form.
- Dashless accessions are derived only for archive paths.
- Tickers are never issuer primary keys.
- Do not manufacture missing identifiers.

### Time

Persist timezone-aware UTC timestamps and distinguish:

- filing date
- SEC acceptance timestamp
- report-period end
- retrieval time
- extraction timestamps on `source.xbrl_report` / related rows
- later `known_at` and `superseded_at` semantics

Never substitute one timestamp for another. Extraction timestamps are metadata
only—never interpretation identity.

### Numeric facts

- Never use binary floating point for filed financial values.
- Use Python `Decimal` and PostgreSQL `NUMERIC`.
- Preserve raw and normalized values.
- Preserve scale, sign, decimals, precision, unit, context, and dimensions.
- Preserve nil facts.
- Do not drop extension concepts.
- Do not aggregate dimensional facts without an explicit policy.

### XBRL semantics

- Concept names and labels do not prove economic equivalence.
- Preserve all available labels, references, statement roles, and relationship networks.
- Preserve issuer extension relationships exactly as filed.
- Do not collapse broader, narrower, component, proxy, non-GAAP, or segment measures into one metric.
- Do not infer canonical financial metrics during foundation phases.
- Do not remove apparently duplicate facts without preserving source occurrences or a documented equivalence relationship.
- XBRL engine-specific objects must not escape the adapter boundary.
- Production modules must not import from `scripts/spikes/`. Slice-0 serialization versions, promotion ceremony, occurrence/semantic hash frameworks, and evidence formats are historical verification mechanisms rather than production compatibility contracts. Reuse of an underlying idea requires an independent production abstraction.

### Parsed text

- Preserve document order and source locators.
- Do not rewrite substantive filing text.
- Whitespace normalization is deterministic and tested.
- Missing sections become quality issues, not inferred content.
- Table-of-contents headings require explicit disambiguation.
- Tables remain linked to their source locations.

### Versioning and provenance

Every extracted output must be traceable through the persisted model to:

- filing/accession (`source.filing`)
- FilingBundle (filesystem)
- `source.xbrl_report` and/or `source.document` as applicable
- source bundle artifact / URI binding and locator where applicable
- parser / Arelle version recorded on extraction rows

Shared `source.concept` identity is global; report-scoped declarations provide
filing-local provenance.

Operational acquisition is separate from extraction replace cycles. There is no
projection-attempt owning identity in V2.

A parser behavior change that alters persisted output requires a version change.

### Idempotency

- Reruns do not duplicate canonical rows.
- Enforce natural uniqueness in the database.
- Use transactional repository methods and conflict handling.
- Failed operations are not marked successful.
- Raw artifacts are not deleted when derived parser outputs are replaced.

---

## Architecture boundaries

```text
CLI / orchestration
        ↓
application services
        ↓
domain models and protocols
        ↓
adapters: SEC HTTP, filesystem, PostgreSQL, Arelle, optional LLM
```

Rules:

- Domain modules do not import CLI code.
- Parsing code does not access the network.
- SEC HTTP code does not write directly to database tables.
- Filesystem writes go through the storage abstraction.
- SQLAlchemy models are not the universal domain API.
- Arelle objects stay inside the XBRL adapter.
- Canonical ingestion/parsing modules do not import LLM implementations.
- Production modules under `src/` must not import from `scripts/spikes/`.
- Notebooks are exploratory only; reusable logic belongs in `src/`.

---

## Local development commands

Use repository commands when available:

```bash
make bootstrap
make db-up
make migrate
make lint
make typecheck
make test
make check
make phase1-acceptance
```

Possible direct equivalents:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
uv run alembic upgrade head
```

Run targeted checks first, then the appropriate broader check.

Never claim a command passed unless it was executed.

---

## Python standards

- modern typed Python
- annotations on public and non-trivial functions
- small pure normalization/parsing functions
- dataclasses or Pydantic models at boundaries
- `pathlib.Path`
- explicit timezone-aware datetimes
- `Decimal` for financial numerics
- enums/literals for stable vocabularies
- no mutable defaults
- no hidden import-time work
- narrow exception handling
- no unexplained type suppressions
- no new dependency without justification
- I/O at the edges
- deterministic parsing logic where possible

`pyproject.toml` is authoritative for tooling configuration.

---

## Database and migration rules

- All schema changes use Alembic.
- Do not edit an already applied migration; create a new migration.
- Review generated migrations.
- Name constraints and indexes.
- Use natural uniqueness constraints for idempotency.
- Use foreign keys unless explicitly documented otherwise.
- Use one transaction per logical filing operation.
- Avoid destructive cascades from issuer or filing tables.
- Preserve raw artifacts independently of parser outputs.
- Parser reruns are version-aware.
- Add integration tests for schema changes.
- Include downgrade logic unless intentionally irreversible.
- Never reset non-test data without explicit authorization.

---

## SEC access rules

All requests go through the shared SEC client, which provides:

- identifying user agent
- conservative request rate
- bounded concurrency
- timeouts
- retries with backoff and jitter
- caching
- deterministic URL construction
- observable failures

Rules:

- default below the SEC maximum
- no live SEC calls in unit/default integration tests
- live tests are opt-in and marked
- no scattered `httpx` calls
- use documented APIs/archive endpoints
- no LLM or browser agent as downloader
- download only bounded command scope

---

## Parser rules

### HTML and sections

- Parse the DOM; regex is not the primary HTML parser.
- Regex may normalize heading/item patterns.
- Preserve reading order and source XPath.
- Treat headings, paragraphs, lists, tables, and footnotes distinctly.
- Any boundary-changing heuristic needs fixture coverage.
- Use form-specific section vocabularies.
- Generate candidates, score them, and enforce sequence constraints.
- Persist confidence and method.
- Never fabricate section content.
- No LLM in canonical Phase 1 section extraction.

### XBRL

- Use the XBRL adapter.
- Preserve concepts, labels, references, role types, relationships, contexts, units, dimensions, and facts.
- Preserve source taxonomy and linkbase artifacts.
- Handle instant/duration contexts explicitly.
- Store dimensions as structured data.
- Preserve calculation weights and presentation order.
- Preserve definition-network attributes such as `usable`, `closed`, and target roles.
- Do not infer canonical metric identity from QName or label similarity.
- Do not create canonical financial metrics in Phase 1.

---

## Metric semantics rules for later phases

Phase 2C records mapping decisions; it does **not** implement observation
selection. Later phases may add:

- additional relationship types beyond `exact|narrower|broader|related`
- scope beyond global/issuer
- separate direct, derived, and proxy observations
- dataset exposure of mapping uncertainty

No LLM may auto-approve an ambiguous mapping. Do not implement `semantic.*` or
`metric_observation` until a frozen Phase 2D+ plan exists.

---

## Testing rules

A behavior change requires a test unless documentation-only.

### Unit tests

No network or database by default. Cover:

- identifiers
- SEC URL construction
- manifests and hashes
- rate limiting with fake time
- HTML normalization
- section candidates and sequence
- taxonomy resources
- relationship normalization
- exact decimal parsing
- stable hashes

### Integration tests

Use PostgreSQL and frozen artifacts. Cover:

- migrations
- repositories
- rollback
- offline replay
- idempotency
- text persistence
- taxonomy-resource persistence
- network reconstruction
- context/unit/fact persistence
- provenance queries

### Fixtures and golden files

- prefer small targeted fixtures
- use full bundles only for end-to-end tests
- every artifact is manifest-listed and hashed
- golden updates are explicit and reviewed
- never refresh expected outputs merely to make tests green
- explain intentional count/output changes

### Network tests

- mark `network`
- disable by default
- respect SEC limits
- never use for deterministic acceptance

---

## Local LLM policy

Local LLMs are development assistants and experimental analyzers, not sources of truth.

Permitted:

- code generation with review/tests
- code explanation
- test-case proposals
- diff review
- candidate parser heuristics
- structured diagnostic experiments
- taxonomy-evidence summaries
- candidate metric suggestions in later experimental workflows
- documentation drafting

Not permitted:

- altering source artifacts
- inventing filing text or facts
- auto-approving ambiguous metric mappings
- equating non-GAAP and GAAP measures by semantic similarity
- changing golden files without review
- uncontrolled SEC downloads
- becoming required for tests or ingestion
- claiming commands were run when they were not

Any code-mediated LLM call must use:

- explicit purpose
- versioned prompt
- schema validation
- model identity
- input hash
- recorded parameters and failures
- storage separate from canonical decisions

The system must start, test, ingest, and parse with `LLM_ENABLED=false`.

---

## Security and repository hygiene

- never commit `.env`, credentials, personal contact details, dumps, or model secrets
- do not commit uncontrolled filing corpora
- validate paths and prevent traversal
- treat filings as untrusted input
- do not execute scripts or active content
- disable XML external entities
- use bounded response and parsing limits
- keep PostgreSQL local by default
- do not run destructive commands without explicit need
- preserve unrelated user changes

---

## Documentation rules

Update documentation when changing:

- CLI behavior
- environment variables
- schema
- parser outputs
- fixture process
- semantic invariants
- phase boundary
- acceptance criteria

Use ADRs for consequential decisions.

Clearly distinguish implemented, planned, and experimental behavior.

---

## Definition of done for a change

A change is complete when:

- requested behavior is implemented
- relevant tests exist and pass
- relevant lint/type checks pass
- migrations are included and reviewed when required
- idempotency and provenance are preserved
- semantic distinctions are not lost
- phase scope is respected
- documentation is updated
- final diff has no unrelated edits
- executed commands are reported accurately
- limitations are explicit

Parser/XBRL changes additionally require:

- offline fixture coverage
- review of changed counts and relationships
- explanation of golden changes
- no loss of source traceability

---

## Completion report format

```text
Summary
- What changed and why

Validation
- Exact commands run
- Pass/fail result

Data or schema impact
- Migration, fixture, parser-version, relationship, or manifest implications

Limitations
- Anything not tested or intentionally deferred
```
