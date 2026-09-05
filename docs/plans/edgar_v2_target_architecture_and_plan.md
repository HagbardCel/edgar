# EDGAR v2 — Target Architecture and Phased Implementation Plan

## 1. Mission

> Build a lean local EDGAR data platform that captures XBRL filing information comprehensively, preserves source semantics, conservatively maps source concepts to a governed canonical financial vocabulary, and produces traceable analysis-ready financial observations.

The priority order is:

1. **Correctness**
2. **Complete source capture**
3. **Traceability**
4. **Useful normalization**
5. **Speed to a usable financial dataset**
6. Broader normalization coverage
7. Scale and automation

The system must prefer:

> **unmapped but correct**

over:

> **normalized but potentially wrong**

---

## 2. Architectural target

```text
                               SEC EDGAR
                                   │
                       acquisition / discovery
                                   │
                                   ▼
                     ┌────────────────────────┐
                     │      RAW FILES         │
                     │                        │
                     │ original filing files  │
                     │ hashes + manifest      │
                     └───────────┬────────────┘
                                 │
                     Arelle + document parser
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────┐
│ SOURCE                                                     │
│ faithful representation of what the filer reported        │
│                                                            │
│ issuer / filing / document                                 │
│ XBRL concepts + declarations + labels                     │
│ contexts + dimensions                                      │
│ units                                                       │
│ every XBRL fact occurrence                                │
│ presentation / calculation / definition relationships     │
│ document blocks / filing sections                          │
└──────────────────────────┬─────────────────────────────────┘
                           │
                           │
            ┌──────────────▼───────────────┐
            │ REGISTRY                     │
            │ durable semantic knowledge   │
            │                              │
            │ canonical metrics            │
            │ mapping assertions           │
            │ mapping rationale/evidence   │
            │ review history               │
            └──────────────┬───────────────┘
                           │
                     SQLMesh models
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│ SEMANTIC                                                   │
│ regenerable                                                │
│                                                            │
│ current accepted mappings                                  │
│ fact → metric mappings                                     │
│ mapping coverage                                           │
│ observation candidates                                     │
│ context qualification                                      │
└──────────────────────────┬─────────────────────────────────┘
                           │
                     SQLMesh models
                           │
                           ▼
┌────────────────────────────────────────────────────────────┐
│ ANALYTICS                                                  │
│ regenerable                                                │
│                                                            │
│ canonical metric observations                              │
│ annual financials                                          │
│ quarterly financials                                       │
│ point-in-time financials                                   │
│ derived metrics / ratios                                   │
└──────────────────────────┬─────────────────────────────────┘
                           │
                Polars / Parquet / DuckDB
                           │
                           ▼
                     research / ML
```

The central separation is:

```text
SOURCE              = what was filed
REGISTRY            = what we believe it means
SEMANTIC            = application of those beliefs
ANALYTICS           = useful economic observations
```

This distinction should become the organizing principle of the entire repository.

---

## 3. Normative requirements

These should live in a new `docs/requirements.md`.

### 3.1 Source completeness

**R1 — Complete fact capture**

Every XBRL item fact exposed by the authoritative XBRL extraction must either:

- be persisted as a source fact, or
- cause an explicit extraction/completeness issue.

It must never disappear silently.

**R2 — Occurrence preservation**

Two identical filed fact occurrences remain two source rows.

```text
source occurrence ≠ economic observation
```

**R3 — Context preservation**

Normalization must never silently remove:

- reporting period;
- dimensions;
- dimensional members;
- unit;
- language;
- nil state;
- precision/decimals;
- other interpretation-relevant fact semantics.

**R4 — Exact concept identity**

Source concepts are identified by expanded QName:

```text
namespace URI + local name
```

Never by prefix or local name alone.

**R5 — Source fidelity**

Original filing documents required to inspect or reproduce source facts remain available locally and are integrity-checked with hashes.

### 3.2 Normalization

**R6 — Normalization is additive**

A mapping never rewrites or deletes a source concept or fact.

```text
source fact
    +
mapping assertion
    =
mapped fact
```

**R7 — Mapping is semantic assertion**

A mapping means:

> We assert that source concept X bears semantic relation Y to canonical concept Z.

It does **not** mean:

> X's name looks similar to Z.

**R8 — Conservative publication**

Candidate, rejected, related, broader, or narrower mappings must never silently become exact canonical observations.

For the initial implementation:

> **Only current, accepted, exact mappings may automatically create mapped canonical facts.**

Conditional mappings are deferred until we have real cases requiring them.

### 3.3 Mapping auditability

**R9 — Every mapping is explainable**

Every accepted mapping must contain:

- source concept;
- canonical target;
- semantic relation;
- scope;
- method;
- rationale;
- structured evidence;
- author/origin;
- decision history.

**R10 — Every affected fact is identifiable**

For every mapping assertion, it must be possible to enumerate **all source fact occurrences to which it currently applies**.

**R11 — Every normalized observation is traceable**

```text
canonical observation
      ↓
source fact
      ↓
mapping assertion
      ↓
mapping evidence/rationale
      ↓
filing
      ↓
source document
```

must be queryable.

### 3.4 Human and AI review

**R12 — Machine-readable and human-readable**

The mapping ledger must have deterministic exports suitable for:

- humans;
- coding agents;
- LLM review;
- automated tests.

At minimum:

```text
JSON/JSONL
Markdown
```

YAML can additionally be supported.

**R13 — AI is advisory initially**

AI may:

- generate candidates;
- assemble evidence;
- detect inconsistencies;
- propose rationale;
- prioritize review.

AI-generated similarity or reasoning alone must not automatically establish an accepted mapping.

A deterministic vetted rule may automatically establish accepted mappings where we explicitly choose to permit it.

### 3.5 Derived data

**R14 — Derived data is disposable**

Everything under `semantic` and `analytics` must be reconstructable from:

```text
source + registry + transformation code
```

No application-specific materialization identity, projection attempt hierarchy, or custom derived-state version framework.

**R15 — Durable decisions are not disposable**

Mapping decisions and other curated semantic knowledge are durable source data.

### 3.6 Deployment

**R16 — Laptop first**

The complete initial system must work with:

```text
Python
PostgreSQL
local filesystem
Docker
```

No external scheduler, object store, warehouse, message broker, or cloud service.

**R17 — Libraries before frameworks-of-our-own**

If a mature third-party library satisfactorily solves a generic infrastructure problem, prefer it over custom project infrastructure.

---

## 4. Physical ownership model

| Layer | Storage | Owner | Regenerable? |
|---|---|---|---:|
| Raw filing files | filesystem | ingestion | No |
| Source semantic tables | PostgreSQL | Python + Alembic | Yes, from raw |
| Mapping registry | PostgreSQL | registry application + Alembic | **No** |
| Canonical metric definitions | source-controlled declarative files | Pydantic | No |
| Semantic models | PostgreSQL | SQLMesh | **Yes** |
| Analytical models | PostgreSQL | SQLMesh | **Yes** |
| Research snapshots | Parquet | export | Yes |
| Research queries | DuckDB/Polars | research code | Yes |

This ownership rule prevents multiple frameworks from fighting over the same tables.

---

## 5. Technology stack

### Core

Retain:

```text
Python + uv
PostgreSQL
SQLAlchemy
Alembic
Pydantic
Typer
pytest
Ruff
Pyright
```

### Arelle remains the XBRL semantic authority

Arelle should remain authoritative for XBRL semantics. Do **not** reimplement XBRL processing.

### Strongly evaluate EdgarTools for acquisition

Phase 2A should contain a short replacement spike:

```text
Can EdgarTools replace:
    SEC discovery
    accession retrieval
    attachment enumeration
    download/storage plumbing
    possibly some document parsing
?
```

If yes:

> **delete our implementation and use EdgarTools.**

Do not automatically use its normalized financials as the semantic truth. Treat them as a benchmark/candidate source unless validated against the source-semantic requirements.

---

## 6. SQLMesh should own the transformation DAG

SQLMesh should own regenerable transformations:

```text
mapped facts
→ observation candidates
→ observations
→ financial marts
```

This replaces custom machinery for:

```text
projection fingerprints
projection reuse
materialization comparison
dependency invalidation
derived-state rebuild system
```

### Ownership boundary

**Alembic owns durable state**

```text
issuer
filing
xbrl_fact
xbrl_context
canonical_metric
mapping_assertion
mapping_review
```

**SQLMesh owns regenerable state**

```text
current_mapping
fact_mapping
observation_candidate
metric_observation
annual_financials
quarterly_financials
```

---

## 7. Target source data model

Exact physical columns can evolve. The **grains** should be frozen.

### `source.issuer`

**Grain:** one SEC registrant.

```text
cik
```

Ticker is metadata, not identity.

### `source.filing`

**Grain:** one SEC accession.

```text
accession
issuer
form
filing_date
accepted_at
report_period_end
primary_document
```

### `source.document`

**Grain:** one stored filing document/artifact.

```text
filing_id
filename
document_kind
source_url
local_path
sha256
byte_size
is_primary
```

### `source.xbrl_report`

**Grain:** one independently loaded XBRL report within a filing.

Usually one primary report, but avoid assuming:

```text
filing == exactly one physical XBRL document
```

Store only current extraction metadata:

```text
filing_id
extractor_version
arelle_version
status
extracted_at
```

No projection history.

### `source.concept`

**Grain:** one exact expanded QName.

```text
id
namespace_uri
local_name
```

### `source.concept_declaration`

**Grain:** one effective concept declaration in one XBRL report.

```text
report_id
concept_id

data_type
period_type
balance
abstract
nillable
substitution_group
```

This preserves:

```text
QName identity
≠
DTS-specific declaration
```

### `source.concept_label`

**Grain:** one relevant label occurrence/use for one concept in one report.

```text
concept
role
language
text
```

Initially, exact XLink arc/resource provenance is not required.

### `source.context`

**Grain:** one XBRL context in one report.

```text
source_context_id
entity_scheme
entity_identifier

period_kind
instant
start_date
end_date
```

### `source.context_dimension`

**Grain:** one filed dimension occurrence within a context.

```text
context_id
dimension_concept_id
context_element

member_kind
explicit_member_concept_id
typed_member
```

No implicit default dimensions fabricated as filed dimensions.

### `source.unit`

**Grain:** one filed unit declaration.

### `source.unit_measure`

**Grain:** one numerator/denominator unit measure occurrence.

### `source.fact`

**Grain: one filed XBRL fact occurrence.**

At minimum:

```text
id
report_id
concept_id
context_id
unit_id

value_status
raw_lexical_value
resolved_value_kind
resolved_numeric
resolved_text

is_nil
decimals
precision

xml_lang
scale
sign

source_document_id
source_locator
```

There must be **no economic deduplication** here.

### `source.relationship`

**Grain:** one effective semantic relationship occurrence in one XBRL report.

```text
network_type
link_role_uri
arcrole_uri

source_concept_id
target_concept_id

order
weight
preferred_label
target_role
dimensional attributes where relevant
```

This supports:

```text
presentation
calculation
definition
```

without storing a generic XLink database.

### Document content

Retain:

```text
source.document_block
source.filing_section
```

but collapse projection lifecycle complexity.

The parser output is current regenerable interpretation:

```text
document
+ parser_version
→ blocks / sections
```

not:

```text
projection
+ attempt
+ fingerprint
+ verified reuse
+ historical materializations
```

---

## 8. Semantic registry

The semantic registry becomes the most valuable manually curated asset in the project.

### `canonical_metric`

Define canonical metrics declaratively under:

```text
registry/
  metrics.yml
```

validated with Pydantic.

Example:

```yaml
key: revenue
name: Revenue

kind: reported

statement: income_statement
period_type: duration
unit_dimension: monetary

definition: >
  Revenue generated from the entity's ordinary activities
  during the reporting period before operating expenses.

includes:
  - product revenue
  - service revenue

excludes:
  - gross profit
  - billings
  - bookings
  - gross merchandise value
  - other operating income
```

The stable `key` is the semantic identity.

The definition is not decorative documentation. It defines what mappings must be judged against.

---

## 9. Mapping vocabulary

Use a compact mapping vocabulary:

```text
exact
narrower
broader
related
conditional
```

Examples:

```text
acme:TotalNetRevenue
    exact
        → revenue
```

```text
acme:ServiceRevenue
    narrower
        → revenue
```

```text
acme:Billings
    related
        → revenue
```

Only:

```text
accepted + exact
```

participates automatically in the initial normalized fact layer.

---

## 10. The Mapping Decision Ledger

The durable entity should be:

```text
registry.mapping_assertion
```

rather than merely `mapping`.

**Grain: one immutable revision of one semantic mapping assertion.**

Suggested structure:

```text
id
supersedes_id                 nullable

source_concept_id
target_metric_key

relation
scope_kind                    global | issuer
issuer_id                     nullable
valid_from                    nullable
valid_to                      nullable

status
    candidate
    accepted
    rejected

method
    curated
    deterministic_rule
    lexical_candidate
    structural_candidate
    model_candidate
    human_review

rationale                     required for accepted
evidence JSONB                required for accepted

created_at
created_by
```

If a decision changes:

```text
assertion A
    ↓ superseded by
assertion B
```

Do not mutate history away.

---

## 11. Mapping evidence

Evidence should be structured wherever possible.

Example:

```json
[
  {
    "kind": "label",
    "value": "Net Sales"
  },
  {
    "kind": "period_type",
    "value": "duration"
  },
  {
    "kind": "presentation_path",
    "statement": "Consolidated Statements of Operations",
    "path": [
      "StatementOfIncomeAbstract",
      "NetSales"
    ]
  },
  {
    "kind": "calculation_structure",
    "children": [
      "ProductRevenue",
      "ServiceRevenue"
    ]
  },
  {
    "kind": "historical_consistency",
    "filings": 5,
    "consistent": true
  }
]
```

Useful evidence kinds include:

```text
taxonomy_identity
label
documentation
data_type
period_type
balance

presentation_path
calculation_relationship
definition_relationship

unit_usage
dimension_usage

historical_consistency
value_reconciliation

human_analysis
model_analysis
```

Free-text rationale remains important, but it supplements structured evidence.

---

## 12. AI records

AI proposals should contain ordinary inspectable metadata:

```text
model
candidate metric
reasoning summary
evidence presented to model
rule/prompt version
```

An AI proposal produces:

```text
status = candidate
```

unless a separate policy explicitly promotes that class of output.

---

## 13. Fact-level mapping ledger

The mapping assertion does **not** contain a huge embedded list of facts.

Instead SQLMesh creates:

```text
semantic.fact_mapping
```

**Grain: one source fact × applicable accepted mapping assertion.**

```text
fact_id
mapping_assertion_id
canonical_metric_key

mapping_relation
mapping_scope

application_status
```

Therefore:

```text
mapping assertion #123
        │
        ├── fact #9182
        ├── fact #9183
        ├── fact #9237
        ├── fact #9348
        └── ...
```

can always be queried.

When a new filing arrives, the assertion remains unchanged and the new source facts automatically join to it.

This separates:

```text
semantic knowledge
```

from:

```text
application of semantic knowledge
```

---

## 14. Human/AI mapping report

This is a first-class feature.

A command such as:

```bash
edgar mappings show <mapping-id>
```

should produce:

```text
MAPPING
=======

Source concept
--------------
QName:
  {http://apple.com/...}NetSales

Issuer:
  Apple Inc.
  CIK 0000320193

Known labels:
  Net Sales


Target concept
--------------
revenue

Relation:
  exact

Status:
  accepted


Definition
----------
Revenue generated from ...


Rationale
---------
The concept represents Apple's consolidated top-line revenue.


Evidence
--------
Period type:
  duration

Presentation:
  Consolidated Statements of Operations
    Net Sales

Calculation:
  Products
  Services
      → Net Sales


Affected facts
--------------
43 occurrences

Accession            Period        Dimensions     Value
...                  FY2025        consolidated   ...
...                  FY2025        Products       ...
...                  FY2025        Services       ...


History
-------
candidate ...
accepted ...
```

And:

```bash
edgar mappings show <id> --format json
```

must expose the same semantics programmatically.

Additional commands:

```bash
edgar mappings list
edgar mappings candidates
edgar mappings accept
edgar mappings reject
edgar mappings export
edgar mappings coverage
```

The JSON structure should be Pydantic-defined so its JSON Schema can be supplied directly to AI agents.

---

## 15. Mapping is not observation selection

Consider:

```text
concept = Revenue
```

and facts:

```text
Revenue | FY2025 | consolidated
Revenue | FY2025 | Europe
Revenue | FY2025 | Americas
Revenue | Q4     | consolidated
```

All four can validly map to:

```text
canonical_metric = revenue
```

But only some are appropriate for a particular analytical dataset.

Therefore:

```text
concept mapping
      ↓
fact mapping
      ↓
observation candidate
      ↓
observation selection
```

must be separate stages.

---

## 16. Observation candidate layer

SQLMesh model:

```text
semantic.observation_candidate
```

**Grain:** one mapped fact being considered for one canonical observation role.

It should expose explicit features/reasons such as:

```text
metric_key

period classification
dimension classification
unit compatibility
filing-period match

selection_status
selection_reasons
```

Never make selection logic invisible inside a Python function.

---

## 17. Canonical observation

SQLMesh produces:

```text
analytics.metric_observation
```

Grain:

> one selected reported economic observation for an issuer, canonical metric, reporting period, and canonical analytical scope.

Retain:

```text
issuer
metric_key

period_start
period_end
instant

value
unit

source_fact_id
mapping_assertion_id
source_filing_id

knowledge_at = SEC accepted_at
```

---

## 18. Point-in-time semantics

Suppose:

```text
2024 filing:
2024 revenue = 100
```

and the 2025 filing later restates:

```text
2024 revenue = 94
```

For today's financial statement:

```text
94
```

may be preferred.

For a historical return study at the end of 2024:

```text
94
```

would introduce look-ahead information.

Therefore every observation should retain:

```text
source_filing
accepted_at / knowledge_at
```

and eventually support:

```text
latest financials
```

versus:

```text
financials as known at date T
```

---

## 19. Testing architecture

### Python unit tests

Use pytest for:

- extraction;
- Pydantic registry validation;
- mapping command behavior;
- Arelle adapter behavior.

### Hypothesis

Use Hypothesis for invariants such as:

```text
candidate mapping never publishes

narrower mapping never acts as exact

normalization preserves source fact identity

dimensions never disappear

input ordering does not change observation selection

duplicates survive

invalid unit combinations never publish
```

### Testcontainers

Replace custom destructive-database safety infrastructure with disposable PostgreSQL integration databases.

Eventually delete:

```text
EDGAR_TEST_DATABASE_URL
edgar_test naming requirement
destructive test safety barrier
CI-managed shared test database
```

### SQLMesh tests

Use model-level tests for transformations.

Example:

```text
given:
  source facts
  accepted mapping

expect:
  exact mapped_fact output
```

### SQLMesh audits

Use audits for real-data properties such as:

```text
no candidate mappings in fact_mapping

no unknown metric keys

no duplicate canonical observations

every canonical observation has source fact

every source fact still exists

accepted exact mappings have rationale/evidence
```

---

## 20. Mapping quality metrics

Every build should expose at least:

```text
SOURCE
------
Arelle fact count
persisted fact count
extraction completeness issues


NORMALIZATION
-------------
eligible facts
exact mapped facts
candidate-mapped facts
unmapped facts

mapping coverage %


OBSERVATIONS
------------
unambiguous observations
ambiguous observations
missing canonical metrics


QUALITY
-------
blocking audit failures
accounting reconciliation warnings
```

Do **not** optimize blindly for percentage mapped.

A coverage increase accompanied by weaker semantic certainty is not necessarily an improvement.

---

## 21. Candidate-generation architecture

Once the deterministic layer works:

```text
unmapped source concept
           │
           ▼
    candidate generation
           │
      ┌────┼─────┐
      ▼    ▼     ▼
 lexical graph   AI
      │    │     │
      └────┴─────┘
           │
           ▼
 mapping assertion
 status=candidate
```

### RapidFuzz

Use it to reduce:

```text
50 canonical metrics
```

to:

```text
5 plausible candidates
```

Not to decide truth.

### NetworkX

Use ephemeral graphs built from:

```text
source.relationship
```

to collect:

- statement ancestors;
- calculation children;
- neighboring concepts;
- distance from statement root;
- hierarchy evidence.

No additional graph database.

---

## 22. Research-serving layer

Once canonical observations are trustworthy:

### Polars

Use as the Python-facing analytical dataframe API.

### Pandera

Use for public research contracts:

```text
annual_financials
quarterly_financials
```

### DuckDB

Later:

```text
PostgreSQL
   ↓
Parquet research snapshot
   ↓
DuckDB + Polars
   ↓
prices + fundamentals + returns
```

PostgreSQL remains the system of record.

---

## 23. Future technologies — only behind explicit triggers

### LinkML

Trigger:

```text
hundreds/thousands of metrics
canonical dimensions
members
external ontologies
formal hierarchy
interchange requirements
```

Then evaluate LinkML.

### dlt

Trigger:

```text
prices / macro / estimates / fundamentals from multiple APIs
```

Then evaluate dlt.

### Dagster

Trigger:

```text
regular multi-source update workflows
with meaningful dependencies/retries/monitoring
```

Then evaluate Dagster.

Not before.

---

## 24. Proposed repository structure

```text
edgar/
├── src/edgar/
│   ├── acquisition/
│   │   └── ...
│   ├── xbrl/
│   │   ├── extract.py
│   │   └── models.py
│   ├── documents/
│   │   └── ...
│   ├── registry/
│   │   ├── models.py
│   │   ├── service.py
│   │   └── export.py
│   ├── db/
│   │   ├── schema.py
│   │   └── ...
│   ├── cli.py
│   └── config.py
│
├── registry/
│   └── metrics.yml
│
├── sqlmesh/
│   ├── config.yaml
│   ├── models/
│   │   ├── semantic/
│   │   │   ├── current_mapping.sql
│   │   │   ├── fact_mapping.sql
│   │   │   ├── mapping_coverage.sql
│   │   │   └── observation_candidate.sql
│   │   └── analytics/
│   │       ├── metric_observation.sql
│   │       ├── annual_financials.sql
│   │       └── quarterly_financials.sql
│   ├── audits/
│   └── tests/
│
├── migrations/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── fixtures/
│
└── docs/
```

Application Python should shrink substantially because generic transformation machinery leaves `src/edgar`.

---

## 25. Documentation architecture

Replace the current Phase-1-centric documentation with:

```text
docs/
├── requirements.md
├── architecture.md
├── data-model.md
├── normalization.md
├── data-quality.md
├── development.md
├── roadmap.md
│
├── adr/
│   ├── 0010-lean-data-platform-reset.md
│   ├── 0011-conservative-semantic-mapping.md
│   └── 0012-sqlmesh-derived-model-ownership.md
│
└── archive/
    └── phase1/
        ...
```

### `requirements.md`

Contains R1–R17 above.

### `architecture.md`

Contains:

- mission;
- source/registry/semantic/analytics architecture;
- ownership table;
- technology boundaries;
- what is durable versus regenerable;
- application/SQLMesh responsibilities;
- raw filesystem model.

### `data-model.md`

For every table/model:

```text
purpose
grain
primary identity
foreign keys
ownership
regenerability
```

The **grain must be mandatory documentation**.

### `normalization.md`

Include:

- canonical metric philosophy;
- source concept vs source fact;
- mapping relation vocabulary;
- mapping status;
- mapping scope;
- evidence taxonomy;
- candidate versus accepted semantics;
- AI policy;
- assertion supersession;
- fact mapping;
- observation selection;
- mapping report format;
- coverage definitions.

### `data-quality.md`

Document:

```text
source completeness tests
Hypothesis invariants
SQLMesh tests
blocking audits
non-blocking accounting checks
mapping quality metrics
benchmark corpus
```

### `development.md`

A new developer should be able to follow:

```text
uv sync
Docker/Postgres start
ingest filing
extract filing
inspect source facts
run SQLMesh plan
run tests
review mapping
query financials
```

No architectural philosophy here—just operations.

### `roadmap.md`

Contains the phases below and nothing historical.

Old Phase-1 plans should become explicitly historical rather than remaining apparently authoritative.

---

# 26. Phased implementation plan

Treat the next work as:

> **Phase 2: Lean data-platform reset**

## Phase 2A — Freeze Phase 1 and validate replacement libraries

### Goal

Lock the useful evidence and decide exactly what existing infrastructure can disappear.

### Work

1. Tag current merged state:

```text
phase1-evidence
```

2. Record baseline:

- representative source fixtures;
- fact counts;
- IXDS case;
- dimensions;
- network relationships;
- document blocks/sections.

3. Spike EdgarTools against current acquisition:

```text
accession lookup
attachment enumeration
download
local storage
primary HTML
complete submission
sections
```

4. Compare its filing acquisition behavior against current representative fixtures.

5. Spike SQLMesh with local Postgres:

```text
external source table
→ simple mapped model
→ audit
→ dev plan
```

6. Spike Testcontainers Postgres.

### Deliverables

- final library choices;
- `requirements.md`;
- new `architecture.md`;
- ADR 0010–0012;
- new roadmap.

### Acceptance

Answer definitively:

```text
What existing code survives?
What is replaced by EdgarTools?
What is replaced by SQLMesh?
What is replaced by Testcontainers?
```

No speculative adapter layers.

---

## Phase 2B — Lean source-layer cutover

### Goal

Produce a simple faithful source database with **all XBRL facts**.

### Implement

New source schema:

```text
issuer
filing
document
xbrl_report

concept
concept_declaration
concept_label

context
context_dimension

unit
unit_measure

fact
relationship

extraction_issue

document_block
filing_section
```

Implement one extraction transaction:

```text
raw filing
→ Arelle
→ source records
→ PostgreSQL
```

Re-extraction semantics:

```text
delete/replace current derived source extraction
inside transaction
```

No historical projections.

### Remove

Once parity tests pass:

```text
semantic_projection
semantic_projection_attempt
document_projection
document_projection_attempt

config fingerprints
round-trip projection equality
verified projection reuse

most bundle/replay machinery
```

Exactly how much acquisition/replay code disappears depends on the EdgarTools spike.

### Testing

- Arelle fact count == persisted fact count.
- occurrence multiplicity preserved.
- contexts/dimensions preserved.
- relationships retained.
- source fact → document locator works.
- PR7 section functionality preserved.

### Definition of done

One accession can be ingested from scratch with:

```text
all XBRL facts queryable
```

and no normalization yet.

---

## Phase 2C — Canonical registry and Mapping Decision Ledger

### Goal

Introduce durable semantic knowledge.

### Implement canonical registry

Start with perhaps **30–50 high-value financial concepts** rather than hundreds.

Examples:

```text
revenue
cost_of_revenue
gross_profit

research_and_development
selling_general_administrative
operating_income

pretax_income
income_tax
net_income

cash
accounts_receivable
inventory
current_assets
total_assets

current_liabilities
debt
total_liabilities
equity

operating_cash_flow
capital_expenditure
investing_cash_flow
financing_cash_flow

basic_eps
diluted_eps
weighted_average_shares
shares_outstanding
```

Do not obsess over the exact list before testing real issuers.

### Implement

```text
registry.mapping_assertion
```

with:

```text
candidate / accepted / rejected
exact / narrower / broader / related
scope
rationale
evidence
history
```

### CLI

```text
mappings list
mappings show
mappings propose
mappings accept
mappings reject
mappings export
```

### Agent contract

Pydantic model + generated JSON Schema.

### Definition of done

A reviewer can inspect one mapping and answer:

1. What source concept is this?
2. What are we mapping it to?
3. Is it exact?
4. Why?
5. What evidence supports that?
6. Who/what proposed it?
7. Who/what accepted it?
8. Which filings use this concept?
9. Which exact source facts does it affect?

---

## Phase 2D — SQLMesh semantic layer

### Goal

Apply mapping knowledge professionally without custom lifecycle code.

### Models

```text
semantic.current_mapping
semantic.fact_mapping
semantic.mapping_coverage
```

### Rules

`fact_mapping` initially requires:

```text
status = accepted
AND relation = exact
AND mapping scope applies
```

### SQLMesh tests/audits

Hard checks:

```text
no candidate mappings
no rejected mappings
all mapping targets exist
all mapped facts exist
no conflicting applicable exact mappings
```

### First useful milestone

At the end of this phase:

> **Every extracted fact is either exactly mapped, candidate-associated, or clearly unmapped, with full lineage.**

---

## Phase 2E — Observation selection and first canonical financials

This should be the first major product milestone.

### Implement

```text
semantic.observation_candidate
analytics.metric_observation
analytics.annual_financials
analytics.quarterly_financials
```

### Context logic

Explicitly classify:

```text
instant
quarter
year-to-date
annual

consolidated
dimensioned
segment
other
```

Selection rules must remain inspectable.

### Ambiguity

If two incompatible facts both survive:

```text
AMBIGUOUS
```

not:

```text
pick whichever happens to sort first
```

### Point-in-time fields

Every observation retains:

```text
source_filing_id
knowledge_at
```

### Initial validation set

Use heterogeneous companies rather than only easy mega-caps.

The goal is to expose normalization failure modes early.

### Definition of done

Something equivalent to:

```python
financials(
    cik="0000320193",
    metrics=[
        "revenue",
        "operating_income",
        "net_income",
        "total_assets",
    ],
)
```

returns useful historical canonical observations with complete source lineage.

**This is where the first usable version is successful.**

---

## Phase 2F — Professional mapping candidate engine

### Goal

Increase coverage without lowering correctness.

### Candidate sources

1. Exact known taxonomy mappings.
2. Historical accepted mappings.
3. Label/name similarity.
4. Presentation structure.
5. Calculation structure.
6. Definition/dimensional context.
7. Historical numerical behavior.
8. AI-assisted analysis.

### Libraries

Add:

```text
RapidFuzz
NetworkX
```

### Candidate evidence packet

For every unresolved concept:

```text
QName
labels
definition/reference if available

period type
data type
balance

presentation paths
calculation neighbors
dimension usage

historical facts

top candidate canonical metrics
```

### AI

Provide exactly that structured packet.

AI returns structured candidate assertion.

No autonomous acceptance initially.

### Definition of done

The system can prioritize unresolved concepts for review rather than presenting thousands of arbitrary tags.

---

## Phase 2G — Normalization benchmark and quality hardening

### Goal

Measure whether the semantic layer actually works across companies.

Build a benchmark corpus covering:

```text
technology
industrials
consumer
healthcare
financials
utilities
real estate
companies with many custom extensions
```

Measure:

```text
source extraction completeness
core-metric mapping coverage
observation coverage
ambiguity
false mappings
manual-review burden
```

Add accounting diagnostics such as:

```text
assets ≈ liabilities + equity
```

and relevant subtotal relationships as **quality diagnostics**, not universal hard constraints.

This is the point at which to judge whether the ontology or mapping model needs more sophistication.

---

## Phase 2H — Research interface

### Add

```text
Polars
Pandera
Parquet
DuckDB
```

Implement:

```text
financials()
metric_history()
financials_as_of()
mapping_coverage()
```

and exports:

```text
annual_financials.parquet
quarterly_financials.parquet
metric_observations.parquet
```

Pandera validates public dataframe contracts.

DuckDB/Polars become the research interface, while PostgreSQL remains the system of record.

---

## Phase 3+ — Expansion only when justified

### Formal ontology

Trigger:

```text
registry becomes genuinely difficult to manage manually
```

Then evaluate LinkML.

### External datasets

Trigger:

```text
prices / macro / estimates / fundamentals from multiple APIs
```

Then evaluate dlt.

### Scheduling/orchestration

Trigger:

```text
regular multi-source update workflows
with meaningful dependencies/retries/monitoring
```

Then evaluate Dagster.

Not before.

---

## 27. What should happen to the current architecture?

The migration philosophy should be:

> **reuse behavior, not abstractions.**

### Preserve aggressively

- Arelle extraction knowledge;
- hard XBRL fixtures;
- IXDS handling knowledge;
- edge-case tests;
- source fact fidelity behavior;
- context/dimension handling;
- decimal/value fidelity;
- useful document parser behavior;
- SEC edge cases already discovered.

### Re-evaluate

- custom SEC acquisition if EdgarTools covers it;
- custom document parsing if EdgarTools covers enough of it.

### Remove aggressively

- projection materialization history;
- projection attempt hierarchy;
- semantic config fingerprints;
- verified projection equality;
- projection ownership complexity;
- replay architecture that exists only to guarantee hermetic reconstruction;
- bespoke destructive test DB infrastructure;
- duplicate derived lifecycle abstractions.

No compatibility layer.

No old schema migration.

No `v1_repository_adapter`.

No two pipelines on `main`.

---

## 28. The critical architectural distinction

The most important asset will no longer be:

```text
semantic_projection
```

or even:

```text
metric_observation
```

It will be:

```text
canonical metric definitions
+
mapping decision ledger
```

because:

```text
raw files              reproducible
source extraction      reproducible
SQLMesh semantic data  reproducible
analytics marts        reproducible
```

but:

> **the accumulated knowledge about what issuer-specific financial concepts economically mean is curated intellectual capital.**

That is the part of the system that deserves durable history, explicit provenance and careful review.

---

## 29. Definition of the desired end state

The new architecture is successful when all of the following are true:

```text
✓ one command can ingest a filing
✓ all Arelle XBRL fact occurrences are captured
✓ every source fact remains independently queryable
✓ mapping never modifies source facts

✓ canonical metrics have explicit definitions
✓ mappings are semantic assertions, not aliases
✓ accepted mappings require evidence/rationale
✓ mapping history is durable

✓ every mapping can enumerate every affected source fact
✓ every canonical observation links back to fact + mapping
✓ candidate/unmapped facts remain visible

✓ mapping decisions are easy for humans to review
✓ mapping decisions are structured enough for AI agents

✓ SQLMesh owns regenerable semantic/analytics transformations
✓ no bespoke projection lifecycle exists

✓ first canonical annual/quarterly financial datasets work
✓ point-in-time source filing information is retained

✓ PostgreSQL remains the single durable database
✓ project runs on one laptop
✓ no scheduler/cloud/data-platform services are required

✓ source code is materially smaller than the current architecture
✓ adding future ontology/orchestration tooling does not require redesign
```

The key shift is from:

> **reproducible XBRL evidence platform**

to:

> **traceable semantic financial data platform**

The former helped uncover the difficult parts of EDGAR/XBRL. The latter is the intended product.
