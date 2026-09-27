# 02 — Current-state assessment

## Verdict

The codebase solves the *evidence* problem carefully, and in places over-carefully. It has not yet
started on the *interpretation* problem, which is the project's reason to exist. Effort has
concentrated on provenance, integrity re-verification and review governance. It has not gone into
the part that determines research value: turning filed facts into correct canonical observations at
scale.

The plan's own sequencing reinforces this. The first canonical value is scheduled for M3, after
three more infrastructure phases.

## Strengths worth keeping

| Area | Why it is valuable |
|---|---|
| SEC access | One client with identifying user agent, rate limit, bounded concurrency, retry with jitter, and deterministic URLs. Acquisition is hardened: atomic writes, locks, verification of existing bytes. |
| Immutable object store | SHA-256 content addressing, write-once, atomic rename, relative paths. This is the right durable foundation. |
| Offline Arelle isolation | Subprocess worker with a network guard, and engine objects kept inside the adapter. Replay of a captured filing loads in 0.8 s with the network disabled. |
| Fact fidelity | `Decimal` values, lexical form, decimals/precision, nil, and duplicates retained. Explicit and typed dimensions, no invented dimension defaults, correct `INF` handling. Invalid iXBRL transforms, tuples, fractions and non-dimensional segment content fail closed. |
| Relationship fidelity | Calculation weights, presentation order, definition-arc attributes, link and arc QNames. |
| Document sections | DOM-based parsing, candidate scoring, sequence constraints, table-of-contents disambiguation, and 30 edge-case tests. |
| Persistence semantics | One transaction per report, atomic replace, rollback and concurrency tests, global concept identity with filing-local declarations. |
| Registry ideas | Explicit relation vocabulary (`exact`/`narrower`/`broader`/`related`) and a contract hash that invalidates mappings when a contract changes. Both belong in any design. |
| M0 benchmark *content* | 22 cases, including well-chosen counterexamples: broader revenue, bank revenue, segment and year-to-date, amendment, related restricted cash, narrower extension. This is the seed of a gold set. |
| Hygiene | 506 tests pass (398 offline in 15 s, 108 PostgreSQL in 24 s). Ruff, format and pyright are clean. Typed Python throughout. |

## What the system actually does today (measured)

The local working database holds six filings: eBay 10-K 2022, eBay 10-K 2023, eBay 10-K/A,
Walmart 10-K FY2024, JPMorgan 10-Q, and Coca-Cola 10-Q. The table below covers all of them.

| Measure | Value |
|---|---|
| Facts / concepts / relationships / labels / document blocks | 15,019 / 56,217 / 18,308 / 11,664 / 11,091 |
| Concept declarations | 93,690 (≈18.5k per full report; 264 for the 10-K/A) |
| Distinct concepts actually used by facts, per report | 376–871 (37 for the 10-K/A) |
| Undimensioned facts | 4,946 (33%) |
| Facts on standard concepts (US-GAAP / DEI / SRT) | 12,858 (85.6%) |
| Extension share of non-abstract line items on SEC-classified primary statements | JPM 14%, KO 5%, WMT 2%, eBay 11% (both years) |
| Database size | 125 MiB, of which `concept_declaration` 41 MiB and `concept` 18 MiB |
| Raw object store | 251 MiB |
| Offline extraction, 10-K (no DB write) | 92.9 s and 93.9 s (WMT, two runs), 105.0 s (eBay) |
| Mapping decisions recorded | 0; the `edgar` DB is at `0001_source_v2`, with no `registry` schema |
| Canonical observations | none (not implemented) |

The two most striking numbers are extraction time and declaration volume. Both come from the same
root cause: the extractor treats the whole US-GAAP taxonomy, roughly 17k concepts, as report
content.

## Accidental complexity

### 1. Four representations of one extracted report

The worker produces a dict. `records.py` (1,310 lines) defines one family of records, and
`source_records.py` (502) defines another. `_source_build.py` (530) converts between them, and
`source_wire.py` (722) encodes and decodes the worker protocol. On top of that, the persistence
layer builds SQL row dicts.

That is 3,064 lines to move one conceptual object across one process boundary. The August review
flagged the dead half of `records.py`; it is still present.

### 2. Integrity re-verification at every layer

The fact-count invariant (`arelle_item_fact_count == upstream count == persisted count`) is
referenced in 13 files:

- the extractor;
- the XBRL source-extract step;
- the orchestration service;
- the builder;
- the source record family;
- the wire codec;
- the upstream inventory;
- persistence;
- the schema definition (a database `CHECK`);
- two migrations;
- the corpus-acceptance module and its script.

`SourceExtractService` also captures implementation identity and the lock digest *before and after*
extraction, and re-reads the descriptor hash. Each check is locally reasonable. Together they
multiply the cost of every change to the fact model by the number of layers.

### 3. Provenance receipts for a rebuildable, single-user pipeline

M1A-1 to M1A-3 (PRs #17–#19) added 7,805 lines of code, tests and docs. The additions cover:

- `ExtractionReceipt`, with 11 identity fields;
- an independent lxml "upstream inventory" that re-counts facts;
- link and arc QNames;
- same-report foreign keys.

Only the link/arc QNames close a genuine fidelity gap. The rest defends against silent extraction
or persistence drift: dropped, duplicated or mis-wired rows.

That failure mode is real. A fixture corpus with golden counts, one integrity check at commit, and
oracle agreement at scale cover it at a fraction of the cost.

### 4. The entire standard taxonomy stored per report

Every full report stores about 18.5k `concept_declaration` rows. Almost all of them describe
US-GAAP/SRT/DEI concepts that the filing never uses. They also carry locators computed at great
cost (see Architectural debt).

At 400k filings this is on the order of 7 billion rows. By linear extrapolation from 41 MiB per five
full reports (~8 MiB each), it is roughly 3 TB of redundant data.

Standard taxonomy content belongs in one dataset per taxonomy release. Per-report storage should
hold only the filer's own extension declarations and the concepts its facts use.

### 5. A second store for knowledge that already lives in Git

Metric contracts live in `registry/metrics.yml` and are mirrored into `registry.canonical_metric`.
`propose` and `accept` then require YAML/mirror equality on every mirrored field. Mapping decisions
live in an append-only PostgreSQL ledger with successor-copy semantics and terminal rejection.

That is 2,091 production and 2,390 test lines. It has been used zero times.

Git already provides the same properties:

- append-only history;
- review (pull requests);
- blame;
- diff;
- CI enforcement.

The ledger reproduces them with more code and less visibility.

### 6. Validating the benchmark's paperwork instead of its numbers

`tests/helpers/financial_cases.py` and `test_financial_benchmark_manifest.py` (2,308 lines, plus a
19-line freeze test) validate the benchmark YAML's *structure*: evidence pins, reviewer fields,
capability states, and replacement-slot identity. **No test compares the 13 expected values to
anything the pipeline extracts.** The Git history shows 12 commits over two weeks hardening the
fixture against itself, for example "stop self-authorizing period drift" and "dormant bypasses".

### 7. Planning volume

Planning and governance prose totals ~55k words:

- 31.6k in the architecture package;
- 6.4k in ADRs;
- 13.7k in other `docs/` files;
- 3.6k in `AGENTS.md`, `README.md` and the planning changelog.

The benchmark YAML adds 9.4k words, and `AGENTS.md` (573 lines) is loaded
into every agent session. The architecture package alone (31.6k words) is longer, in words, than
the production codebase is in lines (23.8k).

Much of the prose specifies future mechanisms: knowledge clocks, qualification packets, publication
notices, and hash schemes. Their necessity has not been tested against data.

## Architectural debt

- **Quadratic locator computation** (`xbrl/locators.py`). For each element, uniqueness of its `id` or
  `xml:id` is established by a full-document XPath scan. Over `us-gaap-2023.xsd` (17,221 id-bearing
  elements) this extrapolates to ~82–87 s of the ~94 s Walmart extraction. A one-pass counter index
  takes ~4 ms. It is compounded by computing locators for declarations no fact uses.
- **Regenerable data behind hand-written migrations.** All of `source.*` can be rebuilt from bundles.
  Yet it lives in a server database that needs Alembic migrations, Docker for tests, and in-place
  upgrade discipline.
  - The working database sits at `0001` while `main` is at `0005`. That is evidence of the friction:
    nobody has migrated real data to exercise M1A.
- **Standard semantics are not captured reusably.**
  - ADR 0013 identifies the blocker correctly: FASB documentation labels are not in the filing DTS.
  - It then plans acquisition of official taxonomy evidence.
  - Yet every bundle already contains the SEC-generated `MetaLinks.json`, which is captured and
    hashed but not parsed. It carries, per used tag, the FASB documentation text, authoritative
    references, balance type, data type and statement roles.
  - It also carries report classification: `groupType` statement/disclosure, and `longName` such as
    `0000003 - Statement - CONSOLIDATED BALANCE SHEET` (eBay FY2023).
- **No period model.** Nothing infers fiscal year, fiscal quarter, or the report's own period
  from the EDGAR required context. That is the key selection primitive (see 05).
- **No selection or observation layer.** This is the most important missing domain capability, and
  it is deferred to M3.
- **Multiple identities for one filing snapshot.** Four identifiers name the same snapshot:
  - `report_key`;
  - the bundle opaque id;
  - the payload hash;
  - the descriptor SHA.

  Each needs threading, checking and documenting.
- **Leftover dead code.** The August review's deletions were not applied:
  - aliases: `SecClient`, `CatalogConflict`, `SemanticWorkerError`, `LocatorProvenance`,
    `concept_id_str`, `resolve_document_id`, `AcquisitionObservation` and `WebCacheLike`;
  - `entry_document_id`, which is always null.

## Duplicated responsibilities

| Responsibility | Current owners |
|---|---|
| Fact-count integrity | 13 files, including a DB `CHECK` and two migrations |
| Extracted-report representation | worker dict, `records.py`, `source_records.py`, wire codec, SQL row dicts |
| Metric definitions | `registry/metrics.yml` (39 `metric-v1` contracts), `registry.canonical_metric` mirror, 8 separate `metric-v2` contracts inside the benchmark fixture, historical `semantic-registry/`. Two benchmark keys (`cash_excluding_restricted_cash`, `cash_purchases_of_ppe`) do not exist in the live registry. |
| Mapping history | PostgreSQL ledger (designed), Git (actual history of everything else) |
| Implementation identity | receipt, extraction-row versions, corpus-acceptance checks |
| Offline guarantee | worker network guard, closure capture, replay verification, bundle hashes |
| Benchmark truth | 9.4k-word YAML, 2.3k lines of static validators, the architecture docs describing both |

## Disproportionately expensive abstractions

| Abstraction | Cost | What it buys | Cheaper equivalent |
|---|---|---|---|
| Receipts + upstream inventory + same-report FKs | ~7.8k lines added in M1A | Detects silent extraction drift | Golden counts on a fixture corpus; one count assertion at persist |
| DB mirror + append-only ledger | ~4.5k lines incl. tests; 0 uses | Durable, reviewable mapping history | YAML rules in Git + CI validation (~300–500 lines) |
| Dual record families + wire codec | ~3.1k lines | Typed worker boundary | One schema; the worker writes columnar files validated once |
| Per-report taxonomy declarations + locators | ~47% of DB bytes; ~80 s per 10-K | Locator for every declared concept | Store the standard taxonomy once per release; locate only filer declarations |
| Closure capture + replay verification | ~1.2k lines + 1.1k tests | Offline, pinned taxonomy resolution | Pinned official taxonomy packages via Arelle's package support (issuer extensions remain in the filing) |
| Planned review profiles, qualification packets, knowledge clocks, publication notices | not yet built; roughly 18 work packages | Per-occurrence human assurance | Rules + validators + measured precision (05) |

## Valuable tests, fixtures and domain knowledge

The following should survive any restructuring, adapted rather than rewritten:

- **Extraction behavior tests** (`test_arelle_report_extraction` and fixture helpers):
  - period kinds;
  - duplicates;
  - `INF` decimals;
  - omitted decimals not filled;
  - IXDS multi-document sets;
  - invalid transforms;
  - no invented dimension defaults;
  - fatal tuples, fractions and non-dimensional segment content.
- **Rich, IXDS and invalid-transform fixture builders.** These are small, targeted and fast.
- **Section extraction tests** (30 cases), especially table-of-contents disambiguation, and the
  acquisition hardening tests.
- **Atomic replace, rollback and concurrency tests.** They are worth porting in spirit to any store.
- **Hypothesis properties for identifiers and mapping claims.**
- **The M0 benchmark's values and counterexamples**, for use as gold data. The review-process fields
  wrapped around them are not worth keeping.
- **Domain notes** in `docs/metric-semantics.md`, `docs/normalization.md` and
  `docs/data-quality.md`. They are the most reusable prose in the repository.

## Process observations

- Over two months and 123 commits, code and tests grew by 71,098 lines added and 28,583 deleted.
  Docs grew by 15.4k lines added and 10.2k deleted.
- Remaining M1A–M4 work comes to roughly 18 packages. If they grow at the M1A rate, that implies
  another several tens of thousands of lines before M4. This is an order-of-magnitude warning, not a
  forecast.
- The documented phase (`AGENTS.md`: "Current phase: M0 — complete; next: M1A") lags the repository,
  where M1A-1 to M1A-3 are merged. Governance text is already costly to keep true.
- Two real findings in this assessment went unnoticed through extensive review cycles:
  - the quadratic extraction cost;
  - the benchmark values never being compared with pipeline output.

  Both suggest measurement has been under-weighted relative to specification.
