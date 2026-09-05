# EDGAR v2.1 — XBRL-Native Target Architecture and Comprehensive Implementation Plan

**Status:** proposed target architecture for Phase 2C+  
**Purpose:** replace the earlier “parallel canonical ontology” direction with an XBRL-native semantic architecture that treats official FASB/SEC taxonomies as the primary accounting-semantic backbone.  
**Scope:** U.S. GAAP SEC filings first. IFRS and other taxonomy families are intentionally deferred but should fit the same architecture later.

---

## 1. Executive decision

The project should not build a second accounting ontology where XBRL and the FASB taxonomies already encode the relevant accounting semantics.

The target principle is:

> **XBRL and official reference taxonomies own accounting semantics. EDGAR Scraper owns source fidelity, cross-taxonomy resolution, analytical intent, and observation selection.**

This changes the semantic flow from:

```text
source concept
    ↓
canonical metric
    ↓
observation
```

to:

```text
source XBRL fact
    ↓
resolved accounting meaning
    ↓
analytics metric binding
    ↓
observation selection
    ↓
canonical analytical observation
```

The crucial distinction is now:

```text
SOURCE                = exactly what the filer reported
REFERENCE             = official accounting/taxonomy semantics
REGISTRY              = curated cross-taxonomy knowledge and analytics policy
SEMANTIC              = application of source + reference + registry knowledge
ANALYTICS             = selected economic observations
```

This is a refinement of the existing v2 architecture, not a restart. The Phase 2B source-layer work remains fundamentally valid and should be preserved unless a concrete implementation detail conflicts with the XBRL-native model below.

---

## 2. Why this architecture

### 2.1 The standard taxonomy is already intended to be reused

SEC guidance explicitly discourages filer-specific concepts when a standard taxonomy concept already represents the disclosure. Filers are expected to reuse the standard concept and change the label when appropriate rather than create a semantic duplicate.

That means the standard taxonomy is not merely a vocabulary shipped alongside filings. It is intended to function as the common accounting-semantic reference system.

### 2.2 QName identity is powerful

An XBRL concept is identified exactly by its expanded QName:

```text
{namespace URI}local-name
```

For example:

```text
{http://fasb.org/us-gaap/2026}Assets
```

The prefix (`us-gaap`) is only document syntax. It is not identity.

QName identity gives us deterministic answers to several important questions:

```text
Is this exactly the same source concept?
Is this a standard taxonomy concept?
Have we already reviewed this exact issuer extension?
Which taxonomy/version did this declaration come from?
```

### 2.3 QName identity is not enough by itself

The same accounting meaning may be represented by:

- different taxonomy releases;
- issuer extension concepts;
- deprecated/replacement concepts;
- a primary concept qualified by dimensions and members;
- multiple standard concepts that legitimately map to one analytical role.

Therefore the architecture must distinguish:

```text
exact source identity
        ≠
concept continuity / lineage
        ≠
accounting-semantic equivalence
        ≠
analytics metric identity
```

### 2.4 FASB already publishes machine-readable semantic relationships

The FASB GAAP Meta Model contains relationships designed to help consumers identify and compare accounting concepts. Current relationships include, among others:

```text
trait-concept
trait-domain
class-subclass
concept-dimensional-equivalent
aggregate-other
instant-accrual
instant-contra
instant-inflow
instant-outflow
concept-numerator
concept-denominator
```

The project should ingest and use these relationships rather than re-create an equivalent semantic graph manually.

### 2.5 Accounting meaning can depend on dimensions

A major implication of `concept-dimensional-equivalent` is that accounting meaning is not always a function of the primary concept QName alone.

Conceptually:

```text
primary concept
+ axis
+ member
=
another accounting concept
```

Therefore the semantic pipeline cannot assume that:

```text
concept mapping
→ fact mapping
→ context qualification
```

is universally sufficient.

Instead:

```text
fact aspects
    ↓
accounting meaning resolution
```

must happen before analytical metric mapping.

---

# 3. Architectural invariants

These should be treated as normative requirements.

## 3.1 Source fidelity

### R1 — Every filed fact occurrence remains independently queryable

No economic deduplication in the source layer.

```text
filed occurrence ≠ economic observation
```

### R2 — Exact QName identity is preserved

Every source concept must retain its exact expanded QName:

```text
namespace URI + local name
```

Never use prefix or local name alone as source identity.

### R3 — Fact aspects are preserved

The system must not silently lose:

- concept;
- entity;
- period;
- unit;
- explicit dimensions;
- typed dimensions;
- language;
- nil state;
- decimals/precision;
- other interpretation-relevant fact metadata.

### R4 — Source XBRL and reference taxonomy data remain distinct

A concept present in a filing DTS and a concept loaded from an official taxonomy may refer to the same QName, but their storage ownership and provenance must remain clear.

## 3.2 Reference semantics

### R5 — Official taxonomy meaning is imported, not rewritten

Where FASB/SEC publishes:

- concept declaration properties;
- standard/documentation labels;
- authoritative references;
- deprecation metadata;
- definition/calculation/presentation relationships;
- Meta Model relationships;

we should consume those semantics rather than duplicate them in project-owned prose or bespoke structures.

### R6 — Taxonomy releases are explicit

Reference concepts must be associated with an explicit taxonomy family and release.

```text
family = us-gaap
release = 2026
QName = {http://fasb.org/us-gaap/2026}Assets
```

### R7 — Concept lineage is derived knowledge, not source identity

A cross-release concept series may group concepts such as:

```text
{.../us-gaap/2025}Assets
{.../us-gaap/2026}Assets
```

but those exact QNames remain distinct records.

## 3.3 Mapping semantics

### R8 — Mapping assertions resolve accounting meaning first

Issuer-specific extensions should primarily map to a reference accounting concept or other explicit accounting-meaning target, not directly to an analytical metric.

Preferred:

```text
acme:NetSales
    exact
      ↓
reference accounting concept
      ↓
analytics metric: revenue
```

rather than:

```text
acme:NetSales
    exact
      ↓
revenue
```

### R9 — Mapping relation remains explicit

Use a compact semantic relation vocabulary:

```text
exact
narrower
broader
related
```

`conditional` may be added only when a concrete use case justifies it.

### R10 — Only safe meaning resolutions publish automatically

Initially, only accounting meanings derived through one of these paths are eligible for deterministic downstream use:

1. direct recognized standard concept;
2. accepted exact mapping assertion;
3. official deterministic equivalence relationship whose interpretation is explicitly supported;
4. explicitly vetted deterministic lineage rule.

Candidates, broader/narrower/related assertions, and unresolved extension concepts must remain visible but must not silently publish as exact meaning.

## 3.4 Analytics semantics

### R11 — Analytics metrics are thin stable roles

`revenue`, `total_assets`, `operating_income`, etc. remain stable analytical API keys.

They should not duplicate the complete accounting definition already present in the reference taxonomy.

### R12 — Metric binding is separate from accounting resolution

The project owns the statement:

```text
reference accounting concept X
    → analytics role revenue
```

This is an analytics policy, not a claim about what the filing concept itself means.

### R13 — Observation selection is independent

A fact can correctly resolve to the accounting meaning `revenue` while still be unsuitable as the annual consolidated revenue observation because it may represent:

- Europe;
- a product segment;
- a quarter;
- a year-to-date period;
- another dimensional slice.

Meaning resolution and observation selection therefore remain separate stages.

---

# 4. Target architecture

```text
                                  SEC EDGAR
                                      │
                             acquisition / raw files
                                      │
                                      ▼
                         ┌─────────────────────────┐
                         │         SOURCE          │
                         │                         │
                         │ filing/report/document  │
                         │ QName / concepts        │
                         │ facts                   │
                         │ contexts / dimensions   │
                         │ units                   │
                         │ filing DTS relations    │
                         └────────────┬────────────┘
                                      │
                                      │
              FASB / SEC              │
          official taxonomies         │
                    │                 │
                    ▼                 │
       ┌─────────────────────────┐     │
       │       REFERENCE         │     │
       │                         │     │
       │ taxonomy releases       │     │
       │ QNames / concepts       │     │
       │ labels                  │     │
       │ authoritative refs      │     │
       │ relationships           │     │
       │ deprecations            │     │
       │ Meta Model              │     │
       └────────────┬────────────┘     │
                    │                  │
                    └──────────┬───────┘
                               ▼
                    ┌─────────────────────┐
                    │      REGISTRY       │
                    │                     │
                    │ concept assertions  │
                    │ review history      │
                    │ analytics metrics   │
                    │ metric bindings     │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │      SEMANTIC       │
                    │                     │
                    │ fact aspects        │
                    │ fact meaning        │
                    │ fact → metric       │
                    │ coverage            │
                    │ obs candidates      │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │      ANALYTICS      │
                    │                     │
                    │ metric observation  │
                    │ annual financials   │
                    │ quarterly financials│
                    │ point-in-time views │
                    └─────────────────────┘
```

## 4.1 Layer ownership

| Layer | Purpose | Owner | Durable? | Regenerable? |
|---|---|---|---:|---:|
| Raw files | Original SEC evidence | acquisition | Yes | No |
| `source.*` | Filing-specific XBRL/document evidence | Python + Alembic | No | Yes, from raw |
| `reference.*` | Official taxonomy semantics | taxonomy loader + Alembic | No | Yes, from official packages |
| `registry.*` | Curated semantic decisions + analytics policy | registry service + Alembic | **Yes** | No |
| `semantic.*` | Applied meaning/mapping state | SQLMesh | No | **Yes** |
| `analytics.*` | Selected analytical observations | SQLMesh | No | **Yes** |

The crucial ownership rule is:

> **Alembic owns durable/base tables; SQLMesh owns derived semantic and analytical models.**

---

# 5. XBRL-native source model

The current Phase 2B model should be retained where possible. The main conceptual change is to make QName/aspect semantics explicit and to avoid project-specific reinterpretation.

## 5.1 `source.issuer`

**Grain:** one SEC registrant.

```text
id
cik
legal_name
```

Ticker is metadata, not identity.

## 5.2 `source.filing`

**Grain:** one SEC accession.

```text
id
issuer_id
accession
form
filing_date
accepted_at
report_period_end
primary_document
```

## 5.3 `source.document`

**Grain:** one locally stored filing artifact.

```text
id
filing_id
filename
document_kind
source_url
local_path
sha256
byte_size
is_primary
```

## 5.4 `source.xbrl_report`

**Grain:** one independently loaded XBRL report/DTS within a filing.

```text
id
filing_id
extractor_version
arelle_version
status
extracted_at
```

No projection history or custom lifecycle framework.

## 5.5 `source.qname`

**Grain:** one exact expanded QName encountered in source extraction.

```text
id
namespace_uri
local_name
```

Unique constraint:

```text
(namespace_uri, local_name)
```

This becomes a reusable primitive for:

- concept names;
- data types;
- substitution groups;
- dimensions;
- members;
- unit measures where appropriate.

Do not store or compare prefixes as identity.

## 5.6 `source.concept_declaration`

**Grain:** one effective concept declaration in one source XBRL report.

```text
id
report_id
qname_id

data_type_qname_id
period_type
balance
abstract
nillable
substitution_group_qname_id
```

This preserves the distinction:

```text
QName identity
    ≠
DTS-specific declaration
```

## 5.7 `source.concept_label`

**Grain:** one label resource/use for one concept in one report.

```text
report_id
concept_qname_id
role_uri
language
text
```

## 5.8 `source.concept_reference`

**New recommended source table.**

**Grain:** one reference resource/use attached to one filing-DTS concept.

Store enough structure to inspect references without constructing a generic XLink database.

```text
report_id
concept_qname_id
reference_role_uri
reference_parts_json
```

For standard concepts the authoritative reference copy should usually come from `reference.*`; this source table captures what is actually present/effective in the filing DTS when needed for fidelity.

## 5.9 `source.context`

**Grain:** one filed XBRL context.

```text
id
report_id
source_context_id
entity_scheme
entity_identifier
period_kind
instant
start_date
end_date
```

## 5.10 `source.context_dimension`

**Grain:** one filed dimensional qualification within one context.

```text
context_id
dimension_qname_id
context_element
member_kind
explicit_member_qname_id
typed_member
```

No fabricated defaults presented as filed dimensions.

## 5.11 `source.unit` and `source.unit_measure`

Preserve filed unit structure.

```text
source.unit
-----------
id
report_id
source_unit_id

source.unit_measure
-------------------
unit_id
position
measure_side       # numerator | denominator
measure_qname_id
```

## 5.12 `source.fact`

**Grain:** one filed XBRL fact occurrence.

```text
id
report_id
concept_qname_id
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

No economic deduplication.

## 5.13 `source.relationship`

**Grain:** one effective relationship occurrence in the filing DTS.

```text
report_id
network_type
link_role_uri
arcrole_uri
source_qname_id
target_qname_id
order
weight
preferred_label
target_role
attributes_json
```

Support at least:

```text
presentation
calculation
definition
```

and preserve unusual arcroles without needing application-specific columns for every XBRL extension.

---

# 6. Fact aspects: semantic view, not another durable source model

The XBRL Open Information Model treats a fact as a value identified by dimensions/aspects such as concept, entity, period, unit, and taxonomy-defined dimensions.

The project should adopt that mental model without replacing source contexts.

A derived semantic representation should expose:

```text
fact_id
concept_qname
entity
period
unit
[dimension QName → member/value]*
```

This may be implemented as SQLMesh views/models rather than another persisted base table.

Suggested model:

```text
semantic.fact_aspect
```

Possible grain:

> one fact × one aspect

```text
fact_id
aspect_kind
aspect_qname_id
member_qname_id
value_text
```

However, do **not** add this physical shape unless it proves useful. A wide fact/context join or JSON aggregation may be simpler for the first implementation.

The architectural requirement is logical, not physical:

> **Meaning resolution must have access to the complete relevant fact aspects.**

---

# 7. Official reference-taxonomy layer

This is the main addition to the previous architecture.

## 7.1 Scope

Initial taxonomy families:

```text
US-GAAP GRT
SRT
FASB GAAP Meta Model
```

Optional later:

```text
DEI
country/currency/exchange taxonomies where semantically useful
IFRS taxonomy
other SEC taxonomies
```

Do not load every possible taxonomy merely because it exists. Add families when required by real filings or semantic resolution.

## 7.2 Acquisition

Prefer official taxonomy packages/entry points and local caching.

Requirements:

```text
immutable downloaded package
source URL
release identity
hash
loaded_at
Arelle version
```

Arelle remains the taxonomy/DTS authority.

Do not implement a second taxonomy parser.

## 7.3 `reference.taxonomy_release`

**Grain:** one official taxonomy family release.

```text
id
family                # us-gaap, srt, ...
release                # 2026
namespace_uri
entry_point_uri
local_package_path
sha256
published_at
loaded_at
arelle_version
```

## 7.4 `reference.qname`

This can either be a separate QName catalog or share a generic database-level QName table.

Preference for conceptual clarity:

```text
reference.qname
```

with the same exact identity rule:

```text
(namespace_uri, local_name)
```

If one global QName table materially simplifies implementation without confusing ownership, that is acceptable. Do not create duplication merely to satisfy layer purity.

## 7.5 `reference.concept`

**Grain:** one concept declaration in one official taxonomy release.

```text
id
taxonomy_release_id
qname_id

data_type_qname_id
period_type
balance
abstract
nillable
substitution_group_qname_id
is_deprecated
deprecated_date
```

## 7.6 `reference.concept_label`

```text
concept_id
role_uri
language
text
```

Persist at minimum:

- standard label;
- documentation label;
- other semantically useful label roles.

## 7.7 `reference.concept_reference`

**Important.**

The reference project should make authoritative accounting references first-class evidence.

```text
concept_id
reference_role_uri
reference_parts_json
```

Do not flatten every possible reference part into dozens of nullable columns initially.

## 7.8 `reference.relationship`

**Grain:** one relationship in one official taxonomy release/network.

```text
taxonomy_release_id
network_type
link_role_uri
arcrole_uri
source_qname_id
target_qname_id
order
weight
preferred_label
target_role
attributes_json
```

This should accommodate:

- presentation;
- calculation;
- definition;
- deprecation relationships;
- Meta Model relationships.

## 7.9 Deprecation metadata

Do not treat “deprecated replacement” as a generic exact synonym.

Preserve:

```text
deprecated concept
relationship type
candidate replacement(s)
deprecation date
reason / deprecated label
```

Different relationship types can imply materially different semantics:

```text
essence-alias
similar replacement
aggregate replacement
replacement by dimensionally qualified concept
no replacement
```

Downstream deterministic handling must be relationship-specific.

---

# 8. Concept identity, continuity, and lineage

This architecture needs three distinct concepts.

## 8.1 Exact QName

Example:

```text
{http://fasb.org/us-gaap/2026}Assets
```

This is exact source/reference identity.

## 8.2 Taxonomy concept series

Example:

```text
us-gaap :: Assets
```

This groups semantically continuous concepts across releases when supported.

For unchanged FASB element names across annual releases, a deterministic lineage rule is reasonable **provided taxonomy-family identity is also stable and no explicit change metadata contradicts continuity**.

Suggested derived key:

```text
family + local_name
```

Do not use this as source identity.

## 8.3 Issuer extension lineage

Potential continuity signal:

```text
issuer
+ local_name
+ successive issuer namespace versions
```

For example:

```text
{http://acme/20251231}CloudRevenue
{http://acme/20261231}CloudRevenue
```

SEC guidance encourages stable local concept names across custom taxonomy versions, so this is a strong candidate-generation signal.

It is **not** sufficient by itself for automatic exact semantic inheritance.

Compatibility checks should include at least:

```text
same issuer
same local_name
compatible data type
same period type
same balance where applicable
compatible substitution group
stable/compatible documentation and labels
no contradictory relationship changes
```

A later policy may allow automatic inheritance when these conditions are satisfied and the rule has been benchmarked.

---

# 9. Accounting meaning model

This is the core semantic change.

## 9.1 Meaning target

A fact should resolve to an accounting meaning that is independent of the project's analytical API.

For the initial U.S.-GAAP implementation, the preferred target is usually:

```text
reference concept / concept series
```

But the model must accommodate meaning represented by an aspect combination.

## 9.2 Meaning resolution paths

A fact may obtain its accounting meaning through:

### Path A — Direct standard concept

```text
source fact concept QName
        =
recognized US-GAAP/SRT reference QName
```

No mapping assertion required.

### Path B — Accepted issuer-extension assertion

```text
issuer extension QName
        │
        │ exact
        ▼
reference accounting concept
```

### Path C — Official dimensional equivalence

```text
primary concept
+ axis
+ member
        │
        │ FASB concept-dimensional-equivalent
        ▼
reference accounting concept
```

### Path D — Explicitly supported deprecation relationship

Only where the specific FASB relationship type justifies the interpretation.

Do not generically map all deprecated concepts to replacement concepts as exact semantic identity.

### Path E — Vetted lineage inheritance

For stable issuer concept versions or reference-taxonomy concept series after an explicit deterministic policy is established and tested.

## 9.3 `semantic.fact_meaning`

**Grain:** one source fact × resolved accounting meaning.

Suggested columns:

```text
fact_id
meaning_kind
reference_concept_id
reference_concept_series_key

resolution_method
resolution_assertion_id
resolution_relationship_id
resolution_confidence

resolution_status
resolution_reasons
```

Possible `resolution_method` values:

```text
direct_reference_qname
accepted_mapping_assertion
concept_dimensional_equivalent
deprecation_relationship
vetted_lineage_rule
```

Possible status values:

```text
resolved_exact
unresolved
ambiguous
candidate_only
```

Initially only `resolved_exact` is eligible for exact downstream metric publication.

---

# 10. Mapping Decision Ledger — revised purpose

The ledger remains one of the project's most important durable assets, but its target changes.

## 10.1 Primary assertion

Preferred assertion:

```text
source / issuer concept
        relation
             ↓
reference accounting concept
```

Example:

```text
{http://acme/2026}NetSales
    exact
      ↓
{http://fasb.org/us-gaap/2026}RevenueFromContractWithCustomerExcludingAssessedTax
```

## 10.2 `registry.mapping_assertion`

**Grain:** one immutable revision of one semantic assertion.

Suggested structure:

```text
id
supersedes_id

source_kind                 # issuer_concept initially
source_qname_id
source_issuer_id             nullable where appropriate

target_kind                 # reference_concept initially
target_reference_concept_id

relation                    # exact | narrower | broader | related
scope_kind                  # global | issuer
issuer_id                   nullable
valid_from                  nullable
valid_to                    nullable

status                      # candidate | accepted | rejected
method
rationale
evidence_json

created_at
created_by
```

No destructive update of semantic history.

```text
assertion A
    ↓ superseded by
assertion B
```

## 10.3 Evidence packet

Accepted assertions should contain structured evidence.

Recommended evidence kinds:

```text
qname_identity
issuer_lineage
standard_label
documentation_label
authoritative_reference
data_type
period_type
balance
substitution_group
presentation_path
calculation_relationship
definition_relationship
meta_model_relationship
unit_usage
dimension_usage
historical_consistency
value_reconciliation
human_analysis
model_analysis
```

Example:

```json
[
  {
    "kind": "documentation_label",
    "source": "Revenue from contracts with customers"
  },
  {
    "kind": "period_type",
    "source": "duration",
    "target": "duration"
  },
  {
    "kind": "presentation_path",
    "statement": "Consolidated Statements of Operations",
    "path": ["Revenue", "Net Sales"]
  },
  {
    "kind": "historical_consistency",
    "filings": 6,
    "consistent": true
  }
]
```

## 10.4 Assertions should not enumerate fact IDs

The ledger stores semantic knowledge.

Derived SQL determines application:

```text
mapping assertion
      │
      ├── fact 1
      ├── fact 2
      ├── fact 3
      └── ...
```

This keeps semantic knowledge stable when new filings arrive.

---

# 11. Thin analytics metric layer

## 11.1 Purpose

The analytics metric vocabulary provides:

- stable user-facing keys;
- a compact analytical API;
- project-owned selection intent;
- mapping from accounting concepts into comparable analytical roles.

It should **not** restate the entire FASB accounting ontology.

## 11.2 `registry.analytics_metric`

Prefer a small source-controlled declarative registry, mirrored to PostgreSQL if operationally useful.

Example:

```yaml
key: revenue
name: Revenue
statement_role: income_statement
purpose: >
  Consolidated top-line revenue used for historical company-level analysis.
```

Avoid copying extensive accounting definitions, references, period type, balance, or hierarchy when those are inherited from the bound reference concepts.

Project-owned restrictions may still be appropriate where they express analytical policy.

## 11.3 `registry.metric_binding`

**Grain:** one governed binding from an accounting meaning to one analytical metric.

```text
id
metric_key
reference_concept_series_key / reference_concept_id
relation
status
rationale
created_at
created_by
```

Initially require:

```text
status = accepted
relation = exact
```

for automatic publication.

A metric may legitimately have multiple accounting anchors.

Example:

```text
reference concept X ─┐
reference concept Y ─┼──► revenue
reference concept Z ─┘
```

This is one reason the stable public metric key should not simply be a US-GAAP QName.

## 11.4 Keep the first metric vocabulary small

Start with roughly 30–50 analytical roles.

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

Do not expand the metric vocabulary faster than the benchmark corpus demonstrates a need.

---

# 12. QName-driven resolution strategy

QName-based resolution should be the first and cheapest stage.

## 12.1 Resolution ladder

```text
1. Exact standard QName?
       ↓ yes
   deterministic reference concept

2. Exact previously reviewed issuer QName?
       ↓ yes
   deterministic accepted assertion

3. Official dimensional-equivalence pattern?
       ↓ yes
   deterministic reference meaning

4. Known reference concept lineage/deprecation rule?
       ↓ supported
   deterministic or explicitly qualified resolution

5. Same issuer + same local name across namespace versions?
       ↓ yes
   high-priority continuity candidate

6. New extension?
       ↓
   semantic candidate generation
```

## 12.2 What local name is allowed to do

Local name is a strong signal for:

```text
cross-release lineage
issuer continuity
lexical candidate generation
```

It is not sufficient for:

```text
exact semantic equivalence
broader/narrower determination
analytics metric selection
```

## 12.3 Standard concepts across releases

For FASB releases, stable element names provide a strong deterministic concept-series signal.

Derived concept series:

```text
family + local_name
```

but retain release-specific declaration metadata because accounting guidance and taxonomy metadata can evolve.

## 12.4 Issuer extensions across releases

Use a compatibility fingerprint for candidate inheritance:

```text
issuer
local_name
data_type
period_type
balance
substitution_group
```

and compare:

```text
documentation labels
standard labels
presentation neighborhood
calculation neighborhood
definition/dimensional usage
```

Do not introduce a hash/version framework for its own sake. These values can be compared directly in SQL/Python.

---

# 13. Candidate generation for unresolved extensions

Only concepts that survive deterministic resolution should enter the expensive semantic-review path.

## 13.1 Candidate packet

For each unresolved extension concept, provide:

```text
Exact QName
issuer
filings in which observed

local name
standard labels
documentation labels
references if present

data type
period type
balance
substitution group

presentation paths
calculation parents/children
definition relationships
axes/members used with the concept
units used

representative facts
historical usage

same-issuer concept lineage candidates
reference-taxonomy lexical candidates
reference-taxonomy structural candidates
```

## 13.2 Candidate mechanisms

Use progressively more expensive methods:

1. exact identity/known rules;
2. issuer lineage;
3. lexical matching;
4. declaration compatibility;
5. label/documentation similarity;
6. authoritative-reference overlap;
7. presentation/calculation structure;
8. dimension usage;
9. value/historical consistency;
10. AI-assisted semantic assessment.

## 13.3 Libraries

Use mature libraries rather than bespoke frameworks:

```text
RapidFuzz   # lexical candidate reduction
NetworkX    # ephemeral taxonomy/relationship graph analysis
```

No graph database is required.

## 13.4 AI policy

AI receives a bounded, structured evidence packet and returns a structured proposal.

Default:

```text
AI output → status=candidate
```

AI-generated prose or similarity alone must not establish an accepted exact assertion.

---

# 14. Metric application

## 14.1 `semantic.fact_metric`

**Grain:** one meaning-resolved fact × applicable accepted analytics metric binding.

```text
fact_id
fact_meaning_id
metric_key
metric_binding_id
application_status
application_reasons
```

Eligibility:

```text
fact_meaning.status = resolved_exact
AND
metric_binding.status = accepted
AND
metric_binding.relation = exact
```

This yields a very clean lineage:

```text
analytics metric observation
        ↓
source fact
        ↓
fact meaning resolution
        ↓
issuer mapping assertion / official taxonomy rule
        ↓
reference accounting concept
        ↓
metric binding
```

---

# 15. Observation selection

Meaning resolution does not choose the analytical observation.

Example:

```text
Revenue | FY2026 | consolidated
Revenue | FY2026 | Europe
Revenue | FY2026 | Americas
Revenue | Q4 2026 | consolidated
```

All may resolve to the same accounting meaning and analytics metric.

The observation layer determines which fact fills which analytical role.

## 15.1 `semantic.observation_candidate`

**Grain:** one mapped fact considered for one analytical observation role.

Expose inspectable features:

```text
fact_id
metric_key
issuer_id

period_class
entity_match
dimension_class
unit_compatibility
filing_period_match

selection_status
selection_reasons
```

Recommended period classes:

```text
instant
quarter
year_to_date
annual
other_duration
```

Recommended dimensional classes:

```text
consolidated
segment
geography
product
other_dimensioned
```

These classifications should be inspectable, not buried in opaque Python ranking code.

## 15.2 Ambiguity policy

If multiple incompatible facts remain equally eligible:

```text
AMBIGUOUS
```

not:

```text
first row after sorting wins
```

## 15.3 Point-in-time semantics

Every selected observation retains:

```text
source_filing_id
knowledge_at = accepted_at
```

This enables both:

```text
latest restated financials
```

and:

```text
financials as known at date T
```

without look-ahead leakage.

---

# 16. SQLMesh model DAG

SQLMesh should continue to own regenerable transformations.

Suggested DAG:

```text
source.* ─────────────┐
                      │
reference.* ───────┐  │
                   │  │
registry.* ────────┼──┘
                   ▼
        semantic.reference_concept_series
                   │
                   ▼
        semantic.current_mapping_assertion
                   │
                   ▼
             semantic.fact_meaning
                   │
                   ▼
              semantic.fact_metric
                   │
                   ├──────────────► semantic.mapping_coverage
                   │
                   ▼
        semantic.observation_candidate
                   │
                   ▼
        analytics.metric_observation
                   │
             ┌─────┴─────┐
             ▼           ▼
analytics.annual   analytics.quarterly
_financials         _financials
```

Potential additional derived models:

```text
semantic.fact_dimension_signature
semantic.issuer_concept_lineage_candidate
semantic.unresolved_concept_queue
semantic.reference_deprecation_resolution
semantic.fact_resolution_evidence
```

Only add them when they make logic or review materially clearer.

---

# 17. Human and AI review workflow

The mapping workflow should answer two different questions explicitly.

## 17.1 Concept review

```text
What accounting concept does this issuer extension represent?
```

### CLI

```bash
edgar concepts show <qname-or-id>
edgar concepts unresolved
edgar concepts candidates <qname-or-id>
```

The review should show:

```text
SOURCE CONCEPT
==============
Issuer
Exact QName
Namespace
Local name
Filings observed

DECLARATION
===========
Data type
Period type
Balance
Substitution group

LABELS / REFERENCES
===================
Standard labels
Documentation labels
Authoritative references

STRUCTURE
=========
Presentation paths
Calculation parents/children
Definition/dimensional relationships

USAGE
=====
Units
Dimensions
Representative facts
Historical continuity

REFERENCE CANDIDATES
====================
1. us-gaap:...
2. us-gaap:...
...

DECISION
========
Relation
Status
Rationale
Evidence
History
```

## 17.2 Mapping ledger commands

```bash
edgar mappings list
edgar mappings show <mapping-id>
edgar mappings propose
edgar mappings accept
edgar mappings reject
edgar mappings supersede
edgar mappings export
edgar mappings coverage
```

JSON output should use Pydantic-defined schemas so coding agents can consume it directly.

## 17.3 Analytics binding review

Separate commands or views should manage:

```text
reference accounting concept → analytics metric
```

For example:

```bash
edgar metrics show revenue
edgar metrics bindings revenue
edgar metrics bind <reference-concept> revenue
```

This prevents accounting-resolution decisions and analytics-policy decisions from being conflated in one ledger entry.

---

# 18. Quality metrics

Measure the pipeline at each semantic stage.

## 18.1 Source

```text
Arelle fact occurrences
persisted fact occurrences
source completeness failures
```

## 18.2 Reference resolution

```text
facts with direct standard QName
facts resolved through accepted extension mapping
facts resolved through official dimensional equivalence
facts resolved through lineage rule
unresolved facts
ambiguous facts
```

## 18.3 Unique concepts

Track separately:

```text
standard concepts
known issuer extension concepts
new issuer extension concepts
issuer-lineage candidates
unresolved extension concepts
```

Do not only report fact-weighted coverage; otherwise a few frequently used concepts can hide poor concept coverage.

## 18.4 Analytics mapping

```text
meaning-resolved facts
facts with accepted metric binding
facts outside target metric vocabulary
exact metric coverage
```

## 18.5 Observation selection

```text
unambiguous observations
ambiguous observations
missing expected metrics
point-in-time conflicts
```

## 18.6 Semantic quality

```text
accepted assertions lacking rationale      = 0
accepted assertions lacking evidence       = 0
conflicting exact assertions               = 0
candidate assertions publishing            = 0
unknown reference concepts publishing      = 0
invalid dimensional equivalence publishing = 0
```

---

# 19. Testing strategy

## 19.1 Unit tests

Use pytest for:

- QName normalization/identity;
- taxonomy-family detection;
- Arelle reference-taxonomy extraction;
- mapping service behavior;
- metric registry validation;
- CLI rendering/export;
- deprecation relationship interpretation.

## 19.2 Property/invariant tests

Use Hypothesis where it adds value.

Important invariants:

```text
prefix changes never change QName identity
local-name equality never by itself proves exact mapping
candidate mappings never publish
broader/narrower mappings never publish as exact
source dimensions never disappear
fact occurrence multiplicity survives
input order does not affect deterministic resolution
ambiguous exact mappings never silently choose one
```

## 19.3 Integration tests

Use disposable PostgreSQL via Testcontainers where practical.

Test:

```text
reference taxonomy load
source filing load
mapping decision
SQLMesh transformation
lineage query
```

## 19.4 Contract tests against Arelle

Representative fixtures should include:

- ordinary US-GAAP concepts;
- issuer extension concepts;
- explicit dimensions;
- typed dimensions if encountered;
- presentation networks;
- calculation networks;
- definition networks;
- inline XBRL document sets;
- duplicate fact occurrences;
- taxonomy imports;
- annual namespace changes.

## 19.5 SQLMesh tests

Example:

```text
given:
    source fact with standard US-GAAP QName
expect:
    fact_meaning = corresponding reference concept
```

```text
given:
    source extension + accepted exact mapping
expect:
    fact_meaning = mapped reference concept
```

```text
given:
    dimensionally qualified fact matching official equivalence
expect:
    fact_meaning = equivalent reference concept
```

```text
given:
    candidate-only assertion
expect:
    no exact fact_meaning publication
```

## 19.6 SQLMesh audits

Hard audits:

```text
no candidate assertion in exact fact_meaning
no rejected assertion in fact_meaning
no conflicting applicable exact mappings
all mapped target concepts exist
all metric bindings reference valid metric keys
all canonical observations trace to source fact
all canonical observations trace to fact meaning
all canonical observations trace to metric binding
```

Diagnostics, not universal hard failures:

```text
assets ≈ liabilities + equity
subtotal/calculation reconciliation
historical discontinuities
unit anomalies
```

---

# 20. Mandatory empirical spike before irreversible redesign

Before broad implementation, measure how much work QName/reference semantics actually eliminate.

This should be a small, time-boxed spike.

## 20.1 Corpus

Select approximately:

```text
20–30 heterogeneous issuers
3–5 years each
```

Include:

```text
technology
industrials
consumer
healthcare
financials
utilities
real estate
issuers with many custom tags
issuers with relatively standard tagging
```

Prefer filings already available in the project's fixture/bundle infrastructure where possible.

## 20.2 Classification

For every relevant unique concept and fact occurrence, classify:

```text
A  exact standard reference QName

B  standard QName already bound
   to target analytics metric

C  exact issuer extension QName
   already reviewed

D  same issuer + same local name
   in another issuer namespace version

E  new issuer extension

F  resolvable through official
   concept-dimensional-equivalent

G  deprecated/reference concept requiring
   explicit relationship interpretation
```

## 20.3 Measure three denominators

Report:

```text
% of unique concepts
% of fact occurrences
% of facts relevant to the initial 30–50 analytics metrics
```

The third metric is especially important. The project does not initially need to normalize every note disclosure equally well.

## 20.4 Questions the spike must answer

1. What percentage of target financial facts use direct standard concepts?
2. How often do issuer extensions repeat unchanged across filings?
3. How often does same-issuer/local-name continuity correctly predict semantic continuity?
4. How many target facts need genuine semantic review?
5. How frequently do FASB Meta Model relationships materially improve resolution?
6. How many analytics metrics need multiple reference concept bindings?
7. Are authoritative references and documentation labels materially useful in disambiguating extensions?
8. Does the proposed reference layer make review simpler enough to justify the extra ingestion tables?

## 20.5 Spike deliverable

Produce a short report with:

```text
coverage table
failure examples
recommended deterministic rules
recommended exclusions
schema changes validated/rejected
```

### Gate

Do **not** implement automated issuer-lineage inheritance until the spike demonstrates a sufficiently low false-positive risk.

---

# 21. Phased implementation plan

The phases below are deliberately ordered so that each stage produces a useful, reviewable capability and avoids speculative infrastructure.

## Phase 2C0 — Architecture validation spike

### Goal

Validate the XBRL-native semantic hypothesis before changing durable registry semantics.

### Work

1. Select benchmark issuers/filings.
2. Inventory exact QNames and namespace families.
3. Measure direct standard-concept coverage.
4. Measure issuer extension reuse across filing versions.
5. Inspect FASB Meta Model usefulness.
6. Inspect deprecation relationships on real examples.
7. Draft initial reference-concept → analytics-metric bindings.
8. Compare review effort against the previous direct `source concept → canonical metric` workflow.

### Deliverables

```text
docs/spikes/xbrl-native-semantic-resolution.md
benchmark output tables
recommended schema delta
initial deterministic-resolution rules
```

### Acceptance

The report must answer:

```text
Does this architecture reduce semantic work materially?
Which resolution paths are deterministic?
Which paths still require review?
What exact reference data must be persisted?
```

### Scope lock

No production auto-mapping rule is introduced in this phase.

---

## Phase 2C1 — Reference taxonomy foundation

### Goal

Make official FASB/SEC taxonomy semantics queryable locally.

### Implement

```text
reference.taxonomy_release
reference.qname / shared QName catalog
reference.concept
reference.concept_label
reference.concept_reference
reference.relationship
```

### Loader

```text
official package / entry point
        ↓
      Arelle
        ↓
reference.*
```

### Initial releases

Load only the releases needed by benchmark/current filings plus the current release. Avoid “all historical taxonomy versions” as an initial requirement.

### Tests

- concept counts are stable for fixed package;
- known concepts can be located by exact QName;
- labels/references are queryable;
- Meta Model relationships are present;
- deprecation metadata is queryable;
- reloading the same release is idempotent.

### Definition of done

A query can answer:

```text
What is this US-GAAP concept?
What does FASB document about it?
What declaration properties does it have?
What official semantic/deprecation relationships does it participate in?
```

---

## Phase 2C2 — XBRL-native registry cutover

### Goal

Change durable semantic knowledge from direct analytics mappings to accounting-meaning assertions.

### Implement

```text
registry.mapping_assertion
registry.analytics_metric
registry.metric_binding
```

### Mapping target

Primary exact assertion:

```text
issuer extension QName → reference accounting concept
```

### Metric policy

```text
reference accounting concept / series → analytics metric
```

### Migration from existing Phase 2C work

If direct source-concept → canonical-metric assertions already exist:

1. preserve historical evidence;
2. identify the intended reference concept where possible;
3. split each decision into:
   - accounting mapping assertion;
   - metric binding;
4. do not silently infer a reference target where the old rationale does not support one;
5. mark unresolved historical mappings for review.

No dual authority after cutover.

### CLI

Implement the minimum review commands:

```text
concepts show
concepts unresolved
mappings show/list/propose/accept/reject
metrics show/bindings
```

### Definition of done

A reviewer can answer separately:

```text
What does this filer concept mean?
Why do we believe that?
Which official accounting concept anchors it?
Which analytical metrics use that accounting concept?
```

---

## Phase 2D — Deterministic fact-meaning resolution

### Goal

Resolve accounting meaning for facts before observation selection.

### Implement SQLMesh models

```text
semantic.reference_concept_series
semantic.current_mapping_assertion
semantic.fact_meaning
semantic.meaning_coverage
```

### Initial resolution methods

1. direct standard QName;
2. accepted exact mapping assertion;
3. explicitly supported official dimensional equivalence;
4. minimal safe reference-concept lineage.

### Explicit exclusions

Do not yet auto-resolve:

```text
same local name only
lexical similarity only
AI candidate only
broader/narrower mapping
ambiguous deprecated replacement
```

### Definition of done

Every relevant fact is classified as:

```text
resolved_exact
candidate_only
ambiguous
unresolved
```

with resolution lineage.

---

## Phase 2E — Thin metric binding and observation selection

### Goal

Produce the first trustworthy canonical financial observations using the revised semantic model.

### Implement

```text
semantic.fact_metric
semantic.observation_candidate
analytics.metric_observation
analytics.annual_financials
analytics.quarterly_financials
```

### Selection rules

Explicitly classify:

```text
period
entity
unit
dimensional scope
filing period match
```

### Ambiguity

Ambiguous surviving facts remain ambiguous.

### Point-in-time

Every selected observation retains:

```text
source_filing_id
knowledge_at
```

### Definition of done

A query such as:

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

returns historical observations with complete lineage through:

```text
observation
→ source fact
→ accounting meaning resolution
→ reference concept
→ mapping assertion if applicable
→ metric binding
→ source filing
```

---

## Phase 2F — Issuer-lineage and candidate engine

### Goal

Reduce manual review of recurring issuer extensions without weakening correctness.

### Implement candidate generators

```text
same issuer + same local name
compatible declaration properties
label/documentation similarity
reference similarity
presentation/calculation structure
dimension usage
historical usage
```

### Add

```text
RapidFuzz
NetworkX
```

### Automation policy

Initially:

```text
lineage detection → candidate
```

Only promote a lineage rule to automatic exact resolution after benchmark evidence demonstrates acceptable safety.

### AI

AI receives the same deterministic evidence packet visible to a human reviewer and returns a structured candidate.

### Definition of done

The review queue is ordered by evidence strength and recurring extensions require substantially less manual work.

---

## Phase 2G — Semantic benchmark and hardening

### Goal

Measure whether the system produces genuinely comparable financial data across heterogeneous issuers.

### Benchmark

Expand the corpus across industries and custom-tag behavior.

Measure:

```text
source completeness
reference-resolution coverage
extension review burden
exact mapping precision
analytics metric coverage
observation ambiguity
historical continuity
```

### Diagnostics

Add:

```text
balance-sheet reconciliation
subtotal relationships
cash-flow relationships
historical discontinuity checks
unit anomalies
```

as quality diagnostics unless a rule is sufficiently universal to become blocking.

### Decision gate

Only at this point evaluate whether the accounting-meaning model requires more formal ontology machinery.

---

## Phase 2H — Research interface

### Goal

Expose trustworthy analytical data without changing the semantic system of record.

### Add

```text
Polars
Pandera
Parquet
DuckDB
```

### Public functions

```text
financials()
metric_history()
financials_as_of()
mapping_coverage()
meaning_coverage()
concept_history()
```

### Exports

```text
annual_financials.parquet
quarterly_financials.parquet
metric_observations.parquet
```

PostgreSQL remains the durable system of record.

---

# 22. Migration from the current v2 plan

## 22.1 Preserve

Preserve aggressively:

```text
raw filing evidence
Arelle extraction knowledge
source fact occurrence preservation
contexts and dimensions
units
relationship extraction
IXDS handling
source document locators
SEC edge-case fixtures
PostgreSQL + Alembic boundary
SQLMesh derived-layer ownership
mapping decision history philosophy
```

## 22.2 Modify

Modify:

```text
source concept representation
    → make QName primitive explicit where useful

concept labels only
    → add concept references

canonical metric as accounting definition
    → thin analytics role

source concept → canonical metric assertion
    → source concept → reference accounting concept

fact mapping
    → fact meaning → fact metric
```

## 22.3 Add

Add:

```text
reference taxonomy layer
reference concept lineage
FASB Meta Model ingestion
explicit deprecation semantics
semantic.fact_meaning
registry.metric_binding
```

## 22.4 Remove / avoid

Do not introduce:

```text
parallel home-grown accounting ontology
own XBRL parser
own generic XLink engine
graph database
custom semantic lifecycle/version framework
automatic local-name equivalence
AI auto-acceptance
huge canonical-metric definition duplication
```

---

# 23. Proposed repository structure

```text
edgar/
├── src/edgar/
│   ├── acquisition/
│   ├── xbrl/
│   │   ├── extract.py
│   │   ├── models.py
│   │   └── qname.py
│   ├── reference/
│   │   ├── load.py
│   │   ├── models.py
│   │   └── service.py
│   ├── registry/
│   │   ├── models.py
│   │   ├── service.py
│   │   ├── review.py
│   │   └── export.py
│   ├── documents/
│   ├── db/
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
│   │   │   ├── reference_concept_series.sql
│   │   │   ├── current_mapping_assertion.sql
│   │   │   ├── fact_meaning.sql
│   │   │   ├── meaning_coverage.sql
│   │   │   ├── fact_metric.sql
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
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── fixtures/
│
└── docs/
    ├── requirements.md
    ├── architecture.md
    ├── xbrl-model.md
    ├── reference-taxonomies.md
    ├── semantic-resolution.md
    ├── normalization.md
    ├── data-quality.md
    ├── development.md
    ├── roadmap.md
    └── spikes/
        └── xbrl-native-semantic-resolution.md
```

Do not create modules until there is real implementation content for them.

---

# 24. Documentation plan

## `docs/architecture.md`

Explain:

- SOURCE / REFERENCE / REGISTRY / SEMANTIC / ANALYTICS;
- durable versus regenerable state;
- ownership boundaries;
- why accounting meaning precedes analytics mapping.

## `docs/xbrl-model.md`

Explain in domain language:

```text
QName
concept declaration
fact
context
aspect
dimension/member
unit
network/relationship
DTS
```

and how each maps into PostgreSQL.

## `docs/reference-taxonomies.md`

Explain:

- loaded taxonomy families/releases;
- official package provenance;
- labels/references;
- deprecations;
- Meta Model relationships;
- concept-series rules.

## `docs/semantic-resolution.md`

Explain:

```text
direct standard resolution
issuer extension assertions
dimensional equivalence
lineage rules
deprecation handling
ambiguity
```

## `docs/normalization.md`

Focus on:

```text
accounting meaning → analytics metric
observation selection
point-in-time semantics
```

Do not duplicate XBRL primer material.

## `docs/data-quality.md`

Document metrics, tests, audits, and benchmark methodology.

---

# 25. Design decisions to freeze now

These are sufficiently well-supported to freeze before implementation.

### D1 — Expanded QName is exact source concept identity

```text
namespace URI + local name
```

### D2 — Prefix is never semantic identity

### D3 — Arelle remains XBRL/DTS authority

### D4 — Official FASB/SEC taxonomy semantics are consumed rather than duplicated

### D5 — Reference taxonomy data is a separate regenerable layer

### D6 — Authoritative concept references are first-class semantic evidence

### D7 — Accounting meaning resolution precedes analytics metric mapping

### D8 — Issuer extensions primarily map to reference accounting concepts

### D9 — Analytics metrics are thin stable roles

### D10 — Context/dimensions remain part of fact semantics and observation selection

### D11 — Official dimensional equivalence may participate in meaning resolution

### D12 — Same local name is a signal, never sufficient proof of semantic identity

### D13 — Candidate/ambiguous mappings never silently publish exact observations

### D14 — SQLMesh owns regenerable semantic/analytics state

### D15 — Mapping decisions remain immutable/reviewable durable knowledge

---

# 26. Decisions explicitly deferred to the empirical spike

Do **not** freeze these yet.

### Q1 — Global QName table vs separate `source.qname` / `reference.qname`

Choose the physically simpler model after implementing both usage paths conceptually.

### Q2 — Exact storage shape of concept references

Start with structured JSON parts unless benchmark queries clearly justify normalized sub-tables.

### Q3 — Physical `semantic.fact_aspect` table/view

The semantic requirement is mandatory; the storage shape is not.

### Q4 — Automatic issuer concept-lineage inheritance

Requires empirical false-positive evidence.

### Q5 — Whether metric bindings target exact release concepts or concept-series IDs

Likely concept series for stable analytics, but verify edge cases around semantic/deprecation changes.

### Q6 — Which deprecation relationship types are safe for deterministic exact resolution

Implement relationship-specific semantics only after examples are reviewed.

### Q7 — How many FASB Meta Model arcroles materially improve the first 30–50 metrics

Do not build generic business logic for every arcrole before seeing real benefit.

---

# 27. Scope boundaries

## In scope for Phase 2C–2E

```text
U.S. GAAP SEC filings
FASB GRT/SRT reference semantics
exact QName identity
reference concepts/labels/references/relationships
Meta Model relationships needed for real cases
mapping decision ledger
thin analytics metrics
fact meaning
observation selection
```

## Out of scope until justified

```text
full IFRS normalization
formal ontology framework
LinkML
RDF/triple store
graph database
LLM autonomous acceptance
all-taxonomy historical warehouse
universal accounting reasoning engine
cross-company segment ontology
automatic derivation of arbitrary ratios
scheduler/orchestrator
cloud data platform
```

---

# 28. Risks and controls

## Risk 1 — Overtrusting local-name continuity

**Failure:** issuer reuses a local name while meaning/declaration changes.

**Control:** exact QName remains identity; continuity requires declaration/semantic compatibility; auto-inheritance stays disabled until benchmarked.

## Risk 2 — Treating deprecation replacement as synonymy

**Failure:** broader/narrower or aggregate replacement becomes incorrect exact mapping.

**Control:** preserve relationship type; relationship-specific interpretation only.

## Risk 3 — Duplicating FASB semantics anyway

**Failure:** `metrics.yml` gradually becomes a second accounting taxonomy.

**Control:** project-owned metric documentation should describe analytics intent only; authoritative accounting semantics remain in `reference.*`.

## Risk 4 — Reference layer becomes an XBRL reimplementation

**Failure:** project models every XLink/resource nuance.

**Control:** persist only semantic structures needed for resolution/review; Arelle remains authoritative.

## Risk 5 — Dimensional meaning is ignored

**Failure:** semantically equivalent dimensional facts remain unmapped or are misclassified.

**Control:** fact-meaning resolution receives complete aspects; support official dimensional equivalence explicitly.

## Risk 6 — Mapping precision is sacrificed for coverage

**Failure:** more mapped facts but lower semantic reliability.

**Control:** unresolved/ambiguous is a valid outcome; coverage and precision/review burden measured separately.

## Risk 7 — Architecture grows before evidence

**Failure:** Meta Model, lineage, graph logic all become generalized frameworks.

**Control:** time-boxed empirical spike; implement only resolution paths demonstrated by target metrics.

---

# 29. Definition of the desired end state

The revised architecture is successful when:

```text
✓ one filing can be ingested from raw SEC files
✓ every Arelle fact occurrence is preserved
✓ every source concept retains exact expanded QName identity
✓ fact contexts/dimensions/units remain queryable

✓ official FASB/SEC taxonomy releases are reproducibly loadable
✓ reference concepts, labels and authoritative references are queryable
✓ relevant FASB Meta Model relationships are queryable
✓ deprecations/replacements retain their specific semantics

✓ direct standard concepts resolve without manual mapping
✓ reviewed issuer extensions resolve to reference accounting concepts
✓ exact issuer QName decisions are automatically reusable
✓ cross-version issuer continuity can be surfaced as candidates
✓ local-name similarity alone never establishes truth

✓ fact meaning is resolved before analytics mapping
✓ dimensional equivalence can participate in meaning resolution
✓ unresolved and ambiguous meanings remain visible

✓ analytics metrics are thin stable API roles
✓ accounting concept → analytics metric bindings are explicit and governed
✓ observation selection remains separate from semantic resolution
✓ dimensioned/segment facts never silently become consolidated observations

✓ every canonical observation traces to:
    source fact
    + accounting meaning resolution
    + reference concept
    + mapping assertion where applicable
    + metric binding
    + source filing

✓ mapping history is durable and reviewable
✓ semantic/analytics tables are regenerable through SQLMesh
✓ no parallel home-grown accounting ontology exists
✓ no custom XBRL parser or graph database is required

✓ a heterogeneous benchmark demonstrates useful coverage
  for the initial 30–50 financial metrics
✓ manual review is concentrated on genuinely novel issuer extensions
✓ source code remains materially leaner than a bespoke semantic platform
```

---

# 30. Recommended immediate next action

The next implementation step should **not** be a large schema rewrite.

It should be:

> **Phase 2C0 — a small empirical XBRL-native semantic-resolution spike using real filings.**

The spike should establish how much of the target financial dataset is solved by:

```text
exact standard QName
+ exact previously known issuer QName
+ stable issuer concept lineage
+ official FASB relationships
```

and quantify the residual semantic-review tail.

If the expected result holds, then Phase 2C1–2E can proceed with a much simpler semantic system:

```text
XBRL source evidence
        +
official accounting semantics
        +
small curated cross-taxonomy ledger
        +
thin analytics policy
```

rather than a second accounting ontology.

---

# 31. Authoritative references used for this architectural revision

The plan above is based on the current project architecture plus the following official material:

1. **SEC — EDGAR XBRL Guide (August 2026)**  
   https://www.sec.gov/files/edgar/filer-information/specifications/xbrl-guide.pdf  
   Relevant points: reuse of standard concepts; custom concept continuity across namespace versions; concept naming/declaration guidance.

2. **FASB — 2026 GAAP Financial Reporting Taxonomy Release Notes**  
   https://xbrl.fasb.org/resources/annualrelease/2026/GAAP_Financial_Reporting_Taxonomy_Release_Notes.pdf  
   Relevant points: stable element names across releases; taxonomy evolution; deprecations; Meta Model expansion.

3. **FASB — GAAP Meta Model Taxonomy: Meta Model Relationships**  
   https://xbrl.fasb.org/resources/metamodelrelationships.pdf  
   Relevant points: `class-subclass`, `trait-*`, `concept-dimensional-equivalent`, aggregate and numerator/denominator semantics.

4. **FASB — 2026 Meta Model package index**  
   https://xbrl.fasb.org/us-gaap/2026/meta/  

5. **SEC — U.S. GAAP XBRL Custom Tags Trend (August 2026)**  
   https://www.sec.gov/data-research/structured-data/us-gaap-xbrl-custom-tags-trend  
   Relevant point: custom tags remain materially present and therefore extension resolution cannot be ignored.

6. **XBRL International — Open Information Model 1.0**  
   https://www.xbrl.org/Specification/oim/REC-2021-10-13/oim-REC-2021-10-13.html  
   Relevant point: facts are identified by core and taxonomy-defined dimensions/aspects.

---

# 32. One-sentence architecture summary

> **Persist XBRL faithfully, load FASB semantics explicitly, resolve each fact to accounting meaning using QName/aspects plus reviewed assertions, bind that meaning to a small analytical vocabulary, and only then select canonical observations.**
