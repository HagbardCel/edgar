# EDGAR Scraper — Comprehensive Project Roadmap

**End goal:** A point-in-time, semi-structured company-filings database that combines immutable source documents, regulatory text, raw and normalized financial observations, market data, and reproducible research datasets.

---

## 1. Target capabilities

The completed system should support four classes of work:

### A. Filing research

- retrieve any covered filing and its exhibits
- navigate canonical regulatory sections
- compare sections across periods
- search and retrieve filing passages with provenance
- inspect XBRL statement trees and facts

### B. Financial analytics

- query as-reported and restated observations
- use precise, versioned canonical metric definitions
- preserve industry- and issuer-specific distinctions
- derive quarterly, trailing, and ratio metrics reproducibly
- audit every normalized observation back to the filed fact

### C. Market research

- align filings to tradable securities point in time
- calculate event and forward returns
- construct leakage-resistant features
- analyze cross-sectional and longitudinal relationships
- publish versioned analytical datasets

### D. Text and LLM applications

- section and paragraph retrieval
- filing-to-filing change detection
- risk, guidance, liquidity, and accounting-policy extraction
- source-grounded summarization
- structured LLM outputs with citations to filing blocks
- semantic search and hybrid text/metric analysis

---

## 2. End-state architecture

```text
SEC EDGAR and approved external data sources
                    |
                    v
        Immutable acquisition layer
        raw filings / exhibits / manifests
                    |
                    v
        Canonical parsed evidence layer
 documents / blocks / sections / XBRL taxonomy / raw facts
                    |
                    v
        Semantic normalization layer
 metric ontology / mappings / reviews / derived observations
                    |
                    v
        Point-in-time entity and market layer
 issuers / securities / identifiers / prices / corporate actions
                    |
                    v
        Research and application layer
 Parquet datasets / DuckDB / statistics / search / embeddings / APIs
```

### Systems of record

- **Filesystem/object storage:** immutable source artifacts and large derived artifacts
- **PostgreSQL:** metadata, provenance, normalized entities, mappings, reviews, text structure, and operational state
- **Parquet:** research panels and large analytical extracts
- **DuckDB:** local analytical querying
- **Search/vector index:** added only when concrete retrieval workloads justify it

---

## 3. Cross-cutting principles

1. Immutable source evidence
2. Versioned interpretations
3. Point-in-time correctness
4. Explicit semantic uncertainty
5. Offline reproducibility
6. Idempotent ingestion
7. Human-reviewable mappings
8. LLMs outside the source-of-truth path
9. Dataset releases pinned to code and policy versions
10. Precision before coverage

---

# Phase 0 — Product and research specification

## Objective

Define the questions the system must answer before optimizing ingestion breadth.

## Deliverables

- prioritized research use cases
- initial universe definition
- filing-form scope
- target historical depth
- initial metric families
- target event-return horizons
- data-source constraints
- storage and compute budget
- quality thresholds
- architecture decision records

## Key decisions

- US domestic issuers first
- common-stock universe definition
- treatment of financial companies
- as-reported versus latest-restated use cases
- daily versus intraday market alignment
- analyst-consensus inclusion or exclusion

## Exit gate

A written research specification defines the first empirical study and the minimum data needed to execute it.

---

# Phase 1 — Immutable filing and semantic XBRL foundation

## Objective

Build the offline-replayable evidence substrate.

## Scope

- `10-K`, `10-K/A`, `10-Q`, `10-Q/A`
- SEC discovery and retrieval
- manifests and artifact hashes
- filing documents
- semantic text blocks
- regulatory sections
- concepts, labels, references
- role and arcrole definitions
- presentation, calculation, and definition networks
- contexts, units, dimensions, and facts
- provenance and quality issues
- deterministic fixtures

## Internal gates

```text
Slice 0: acquisition/replay spike
  -> Phase 1A: Acquisition Foundation
       -> Phase 1B: XBRL Evidence
       -> Phase 1C: Document Structure
            -> Phase 1D: Acceptance & Hardening
```

Phase 1B and Phase 1C may proceed in parallel only after Phase 1A produces a valid immutable filing bundle. Durable retrieval is the input dependency for both parser tracks.

Parser outputs are versioned, regenerable materializations of immutable filing bundles. Curated review and mapping decisions are separate, non-regenerable source data that must be transactionally stored, exported and backed up.

Amendment filings use a directed `amends` relationship (see ADR 0005); they do not supersede the original filing as a whole.

## Exit gate

A fact can be traced from database row through statement network and inline location to an immutable source artifact. Phase 2 can perform mappings without reparsing filings.

---

# Phase 2 — Metric ontology and mapping engine

## Objective

Convert selected raw facts into precise, auditable canonical observations while preserving fundamental differences.

## Workstreams

### 2.1 Metric ontology

Define initial metric families and measurement contracts:

- revenue
- gross profit
- operating income
- pretax income
- net income
- EPS
- cash flow
- capex
- cash
- debt
- equity
- shares
- stock-based compensation
- R&D
- SG&A
- dividends
- repurchases

Separate industry-specific definitions where necessary.

### 2.2 Mapping rule engine

Implement:

- mapping scopes
- relationship types
- hard compatibility checks
- evidence scoring
- precedence rules
- validity intervals
- negative mappings
- direct and derived observation distinction

### 2.3 Review tooling

Initially use CLI or generated HTML reports rather than a full web application.

A review packet includes:

- concept labels/references
- statement role
- presentation/calculation neighborhood
- context and dimensions
- issuer history
- candidate metric
- proposed relationship type
- rationale and warnings

### 2.4 Longitudinal validation

Detect:

- taxonomy concept transitions
- comparative-period overlap
- issuer-extension continuity
- unexpected discontinuities
- accounting-policy changes
- restatements

### 2.5 Quality tiers

Produce strict, standardized, and proxy observations.

## Initial implementation strategy

Start with a narrow, heterogeneous issuer sample. Target precision rather than coverage. Expand metric by metric, not issuer by issuer.

## Exit gate

For the pilot universe:

- high precision on core metric mappings
- every observation has definition and policy versions
- ambiguous extensions are reviewed or excluded
- mapping sensitivity can be measured
- no raw fact is overwritten or discarded

---

# Phase 3 — Period normalization, restatements, and derived metrics

## Objective

Create analytically usable time series with explicit economic periods and knowledge timestamps.

## Workstreams

### 3.1 Period classification

Classify:

- instant
- quarter-only
- year-to-date
- annual
- trailing
- 52/53-week periods
- comparative prior periods

### 3.2 Quarter derivation

Where permitted:

```text
Q2 = H1 YTD - Q1
Q3 = 9M YTD - H1
Q4 = FY - 9M YTD
```

Store formulas and input observation IDs.

### 3.3 Restatement model

Preserve:

- originally reported value
- later comparative value
- amendment-derived correction
- latest-known value
- `known_at`
- `superseded_at`
- restatement relationship

### 3.4 Derived metrics

Initial formulas:

- growth
- margins
- margin changes
- free cash flow
- net debt
- leverage
- accruals
- cash conversion
- dilution
- capex intensity
- R&D intensity
- trailing-twelve-month metrics

### 3.5 Validation

- accounting identities
- continuity checks
- period coverage
- derivation reconciliation
- unit and currency consistency

## Exit gate

The system can answer both:

- “What was originally known after this filing?”
- “What is the latest restated value for that economic period?”

Every derived value is reproducible from versioned inputs.

---

# Phase 4 — Historical ingestion and coverage expansion

## Objective

Scale the reliable parser and mapping substrate across a research-relevant universe.

## Workstreams

### 4.1 Universe and backfill

- point-in-time issuer universe
- bounded historical windows
- delisted-company inclusion
- prioritized filing acquisition
- resumable backfills

### 4.2 Operational scaling

Add only as required:

- worker pool
- durable job table
- retry queues
- checkpointing
- storage monitoring
- parser-version reprocessing
- partitioned batch operations

A local laptop can begin with process-based workers and PostgreSQL job state. Distributed infrastructure is deferred until measurements show a need.

### 4.3 Quality sampling

- stratified manual review
- issuer/industry/error sampling
- parser drift reports
- mapping coverage and precision reports
- taxonomy-era comparisons

### 4.4 Additional forms

Add selectively:

- `8-K` items relevant to earnings and material events
- `20-F` and IFRS taxonomy support
- proxy statements
- earnings exhibits

Each form requires a separate schema/section vocabulary and acceptance corpus.

## Exit gate

The target universe and period have known, quantified coverage. Failure modes are observable rather than silently omitted.

---

# Phase 5 — Security master and point-in-time market data

## Objective

Connect registrants and filings to tradable securities without ticker leakage.

## Workstreams

### 5.1 Security master

Model:

- issuer
- security/share class
- ticker and exchange histories
- CUSIP/ISIN/vendor identifiers
- predecessor/successor relationships
- mergers
- spin-offs
- delistings
- multiple share classes

### 5.2 Market data

Preserve:

- raw unadjusted prices
- volume
- dividends
- splits
- corporate actions
- adjustment factors
- source and source version

### 5.3 Filing-event alignment

Use SEC acceptance timestamps and exchange calendars.

Classify:

- pre-market
- during market
- after market
- non-trading day

For daily data, define an explicit effective-trading-date policy. Intraday studies require intraday timestamps and prices.

### 5.4 Returns

Calculate:

- raw total return
- market-adjusted return
- sector-adjusted return
- factor-model abnormal return
- volatility change
- drawdown
- multiple event and forward windows

## Exit gate

Every filing event maps to the correct historical security under a versioned alignment policy. Return labels are reproducible and point-in-time safe.

---

# Phase 6 — Research dataset and empirical framework

## Objective

Create leakage-resistant, versioned datasets for statistical analysis.

## Workstreams

### 6.1 Dataset registry

Each release pins:

- universe definition
- source snapshot
- parser version
- metric-definition version
- mapping-policy version
- derivation version
- security-master version
- return policy
- code commit
- creation timestamp

### 6.2 Feature construction

Initial feature families:

- reported levels
- growth and acceleration
- margins and margin changes
- cash-flow quality
- accruals
- leverage
- dilution
- capex and R&D intensity
- segment dispersion
- mapping-quality controls
- filing timing controls

### 6.3 Expectation proxies

Raw growth is not an earnings surprise. Develop explicit expectation models:

- seasonal historical baseline
- rolling autoregressive expectation
- peer/industry expectation
- analyst consensus, if later licensed
- management-guidance expectation

### 6.4 Statistical framework

- event studies
- cross-sectional regressions
- panel regressions
- clustered standard errors
- overlapping-return corrections
- multiple-testing controls
- time-based out-of-sample validation
- purging/embargo where needed
- transaction-cost and liquidity filters
- survivorship-bias checks

### 6.5 Research reproducibility

Use Parquet dataset releases and DuckDB queries. Notebooks consume released datasets rather than operational tables directly.

## Exit gate

One end-to-end empirical study can be reproduced from a dataset manifest and code commit, including sensitivity to mapping quality.

---

# Phase 7 — Filing text intelligence

## Objective

Turn the preserved document structure into point-in-time textual features and retrieval.

## Workstreams

### 7.1 Deterministic text analytics

- section length
- readability
- numeric density
- modal/uncertainty language
- dictionary sentiment
- forward-looking statement markers
- boilerplate detection
- novelty against prior filing
- added/removed risk paragraphs

### 7.2 Filing comparisons

Align sections and blocks across periods:

- exact hash matches
- fuzzy paragraph alignment
- additions/deletions/modifications
- cross-reference detection
- regulatory-format changes

### 7.3 Embeddings and retrieval

Add only after deterministic block identities are stable:

- embedding model registry
- block and section embeddings
- hybrid lexical/semantic search
- metadata filters
- citation back to source blocks

### 7.4 Structured LLM extraction

Candidate applications:

- guidance changes
- management explanations for margin changes
- liquidity concerns
- restructuring disclosures
- accounting-policy changes
- risk taxonomy
- segment commentary

Rules:

- schema-constrained outputs
- source block citations
- prompt/model versions
- evaluation corpus
- abstention support
- no replacement of source text
- no unreviewed canonical financial facts

## Exit gate

Text-derived features and extractions are measurable against a reviewed evaluation set and remain traceable to filing blocks.

---

# Phase 8 — Integrated analytical applications

## Objective

Expose the combined metric, text, and market layers for practical analysis.

## Possible applications

- company filing dashboard
- filing change monitor
- fundamental factor research
- event-study explorer
- risk-factor change alerts
- comparable-company metric explorer
- natural-language filing research with citations
- company-specific historical metric and narrative timeline
- dataset export API
- screening based on combined quantitative and textual signals

## Implementation approach

Begin with:

- CLI
- SQL views
- DuckDB/Parquet
- notebooks
- lightweight local API

Build a web UI only after repeated workflows justify it.

## Exit gate

At least two recurring analytical workflows are materially faster and more reliable than direct manual filing review.

---

# Phase 9 — Hardening, operations, and broader deployment

## Objective

Make the system sustainable beyond a single developer and laptop.

## Workstreams

- incremental filing monitoring
- scheduled ingestion
- backup and recovery
- database maintenance
- storage lifecycle
- observability
- data-quality service levels
- parser/mapping release process
- access control
- deployment packaging
- optional cloud object storage and managed PostgreSQL
- reproducible model serving
- cost and performance monitoring

## Exit gate

The system has documented recovery, release, and data-quality procedures and can operate continuously with bounded manual intervention.

---

## 4. Recommended execution sequence

The strict dependency order is:

```text
Phase 0 research specification
  -> Phase 1 evidence substrate
  -> Phase 2 semantic mappings
  -> Phase 3 period/restatement normalization
  -> Phase 5 security and market alignment
  -> Phase 6 research datasets
```

Phase 4 historical scaling should begin only after the relevant Phase 1–3 logic is validated on a heterogeneous sample.

Phase 7 text work can begin after stable blocks and sections exist, but large-scale embeddings should wait until block identity and parser versioning are settled.

---

## 5. Proposed first research release

A good first end-to-end target is:

### Universe

- US domestic non-financial common-stock issuers
- a deliberately selected pilot of 100–300 issuers
- several industries
- include failed/delisted names where data permits
- approximately ten years, expanded only after pilot validation

### Filings

- `10-K`
- `10-Q`
- amendments
- selected earnings-related `8-K` exhibits later

### Strict metrics

- revenue
- gross profit
- operating income
- net income
- diluted EPS
- operating cash flow
- cash capex
- cash
- debt components
- equity
- diluted shares
- stock-based compensation
- R&D

### Features

- year-over-year growth
- growth acceleration
- gross/operating margin changes
- operating cash-flow conversion
- accruals
- dilution
- capex and R&D intensity
- filing-text novelty
- risk-factor additions

### Outcomes

- `[0,+1]`, `[0,+5]`, `[0,+20]`, and `[0,+63]` abnormal returns
- volatility change
- maximum drawdown

### Research question

Evaluate whether fundamental acceleration, cash-flow quality, dilution, and filing-text novelty contain incremental information for post-filing returns after controlling for size, industry, valuation, prior returns, and mapping quality.

---

## 6. Quality metrics

Track at least:

### Acquisition

- filing discovery completeness
- retrieval success
- artifact hash failures
- missing attachment rate

### Parsing

- primary-document accuracy
- section boundary precision/recall
- block stability
- XBRL role/network completeness
- context/unit/fact parse success

### Mapping

- strict mapping coverage
- reviewed precision
- extension-concept rate
- unresolved candidate rate
- direct versus derived share
- mapping changes by policy version

### Point-in-time data

- event alignment exceptions
- security mapping coverage
- restatement leakage tests
- delisted-universe coverage

### Research

- missingness by industry and time
- feature stability
- outlier rates
- multiple-testing burden
- out-of-sample decay
- sensitivity to mapping tiers

---

## 7. Principal project risks and mitigations

| Risk | Mitigation |
|---|---|
| Semantic false equivalence | Typed mappings, precise definitions, conservative acceptance |
| XBRL extension heterogeneity | Preserve networks and issuer history; review queue |
| Point-in-time leakage | `known_at`, historical identifiers, versioned event alignment |
| Restatement confusion | Separate original, amended, comparative, and latest-known values |
| Parser drift | Frozen fixtures, parser versions, stratified review |
| Ticker/survivorship bias | Security master with validity intervals and delisted names |
| Text boilerplate | Longitudinal novelty and section-aware controls |
| Statistical overfitting | Predefined hypotheses, multiple-testing controls, OOS validation |
| Local resource constraints | Bounded vertical slices, Parquet exports, deferred infrastructure |
| LLM non-determinism | Optional use, schema validation, model/prompt registry, evaluation sets |
| Excessive scope | Explicit phase gates and narrow first research release |

---

## 8. Governance and versioning

Version independently:

- source snapshot
- artifact manifest format
- parser components
- section vocabulary
- taxonomy extraction
- metric definitions
- mapping policy
- derivation formulas
- security master
- market alignment
- return definitions
- text models
- prompts
- research dataset releases

A dataset manifest should make it possible to reproduce every row and explain why it differs from another release.

---

## 9. Immediate next tasks

Post–PR #4 filesystem acquisition:

1. ~~Architecture / conceptual data model (PR #3).~~
2. ~~Filesystem-first durable acquisition + offline Arelle smoke load (PR #4 / Phase 1A).~~
3. ~~Minimal database / catalog foundation for issuer, filing, and FilingBundle metadata (PR #5).~~
4. ~~Thin Arelle semantic projection (PR #6 / Phase 1B).~~
5. ~~Document blocks and regulatory sections (PR #7 / Phase 1C).~~
6. Diverse acceptance corpus; retire Slice-0 executable machinery while retaining frozen evidence + minimal immutability guard (PR #8 / Phase 1D).
7. ~~Metric ontology + curated mapping registry (PR #9 / Phase 2A).~~
8. Deterministic mapping engine (PR #10 / Phase 2B).
