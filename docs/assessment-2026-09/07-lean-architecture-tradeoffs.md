# 07 — Trade-offs of a lean architecture

There are two "lean" architectures to weigh:

- **The adopted plan (ADR 0012)** is lean in *breadth*: few metrics, few filings, no SQLMesh, no
  LLM approval. It is heavy in *mechanism*: claims per report, occurrence qualification, knowledge
  clocks, publication notices, hash schemes.
- **This recommendation** is the reverse. It is broader early (market samples, global rules) and
  lean in mechanism (rules in Git, deterministic selection, measured quality).

Both give things up. This document makes the choices explicit.

## 1. The adopted plan: gains and costs

| Gains | Costs |
|---|---|
| Every published value has an individual human attestation | Human effort grows with filings × metrics; market coverage is unreachable |
| Very low false-positive risk on the reviewed set | Coverage is limited to what was reviewed. Resolvable cases stay open (parent NI, consistent duplicates), which lowers coverage without raising accuracy |
| Knowledge-time reproducibility (`semantic_as_of`, `public_as_of`, `acquired_as_of`) | Three clocks, notices and publication status to build and keep consistent before any value exists |
| Strong database-enforced integrity and lifecycle | Migrations for regenerable data; server database for a batch workload; ~4.5k lines of ledger code with no decisions recorded |
| Deliberate phase gates, reducing scope creep | First canonical value at M3. The central assumption, that mapping is hard and must be per-report, is never tested before most infrastructure is built |
| Extensive written rationale | ~55k words to keep true; documented status already lags the code |

In short, the plan buys assurance per decision. It pays with scale, time to value and measurable
quality. Given the mission (market-wide research data), that is the wrong trade.

## 2. What the leaner architecture gains (quantified)

| Measure | Now (built + planned) | Recommended | Change |
|---|---|---|---|
| Custom responsibilities (built) | Standard-taxonomy closure capture; replay verification; second record family; wire codec; upstream re-count; receipts; multi-layer integrity re-checks; migrations for derived data; test database lifecycle; registry mirror + sync; ledger lifecycle; benchmark structure validation; corpus acceptance harness | Taxonomy packages (Arelle); one schema; one integrity check; disposable derived store; Git + CI; gold-value test; validation harness | **13 responsibilities removed or delegated** |
| Planned mechanisms not built | Three knowledge clocks; qualification packets; review-profile capability states; publication status and notices; dual hash schemes; request/selector objects per request | Build manifest; tiers; flags; one contract hash | **~8 planned mechanisms avoided** |
| Representations of one extracted report | 4 (worker dict, `records`, `source_records`, SQL rows) | 1 (Arrow/Parquet schema) | 4 → 1 |
| Places defining metric contracts | 3 (YAML, DB mirror, benchmark fixture) | 1 (YAML) | 3 → 1 |
| Snapshot identities | 4 (`report_key`, opaque bundle id, payload hash, descriptor SHA) | 1 (manifest hash) + report key | 4 → 1–2 |
| Sites enforcing the fact-count invariant | 13 files | 1 commit check + tests | 13 → 2 |
| Mapping history stores | Ledger (designed) + Git | Git | 2 → 1 |
| Deletable production modules | — | ~20: `records` (most), `source_wire`, `_source_build`, `upstream_inventory`, `extraction_receipt`, `closure` (most), `db/source`, `db/source_schema`, `db/registry*`, `registry/service` (most), `corpus_acceptance`, migrations, … | ~9–12k lines |
| New production code | — | Resolve, select, validate, oracles, taxonomy tables, MetaLinks parsing, review queue, export | +2.5–4k lines |
| Human work per new filing | Qualification per report and occurrence | Zero unless an exception is raised | O(filings) → O(exceptions) |
| Time to first canonical value | After M1A + M2 + M3 | P1 (~2 weeks) | Months → weeks |
| Services required | PostgreSQL (Docker) | None | −1 |

Third-party capabilities replace bespoke work:

- Arelle taxonomy packages replace closure capture.
- DuckDB/Parquet replaces the schema, migrations and row persistence.
- Git, pull requests and CI replace the ledger and mirror.
- XBRL duplicate-fact rules replace bespoke accuracy review.
- The EDGAR required context replaces bespoke period-slot identity.
- FASB documentation via `MetaLinks.json` replaces planned taxonomy-evidence acquisition.
- SEC `companyfacts`/FSDS replace attestation as the quality signal.

## 3. What the leaner architecture gives up

Each trade-off is classified:

- **Sensible:** accept without ceremony.
- **Accept explicitly:** record the decision in an ADR, because a reasonable user could want the
  other side.
- **Future risk:** acceptable now, with a named trigger to revisit.

| # | Given up | Why it is acceptable | Class | Trigger / mitigation |
|---|---|---|---|---|
| T1 | Queryable history of *unpublished* derived states ("what did the DB contain last Tuesday?") | Derived data is rebuildable. Publications are immutable snapshots with manifests (code, rules and extractor versions). | Sensible | Publish anything used in research |
| T2 | A modelled `semantic_as_of` clock: which mappings were known at time T | Vintage knowledge = check out the rules commit and rebuild. Manifests record the commit. Market `available_at` (SEC acceptance) is still modelled per observation. | Accept explicitly | Revisit if backtests must use *mapping* vintages routinely; add a rules-commit dimension to builds, not a clock |
| T3 | Individual human sign-off on every published value | Precision is measured instead of attested. Tiers let users choose conservative subsets. | Accept explicitly | Publication gate: precision per tier on gold ≥ threshold; no regression in CI |
| T4 | Error isolation: one wrong global rule affects many observations | Fixes are equally global. Identities and the oracle detect systematic errors quickly; per-report review hides them. | Future risk (moderate) | Quality-report diff on every rules PR; tier and industry breakdowns |
| T5 | Database-enforced constraints (FKs, CHECKs) on evidence tables | One code path writes derived tables. Integrity is checked once at commit by SQL anti-joins, and extensively in tests. | Sensible | Keep commit-time integrity SQL mandatory |
| T6 | Concurrent writers, multi-user editing, a server endpoint | Single-user batch workload. Git handles concurrent knowledge edits through PRs. | Future risk | Revisit on a multi-user service or remote consumers; PostgreSQL is still an option for the serving layer |
| T7 | Byte-exact capture of what each standard-taxonomy URL served at filing time | Official packages are the canonical content. Issuer extension files remain captured per filing. A parity test proves equivalence on the spike corpus. | Accept explicitly | Keep fetch-and-pin for non-packaged URLs; fail closed if a release is missing |
| T8 | Independent re-count of facts (upstream inventory) in production runs | Golden counts on fixtures catch extractor regressions. Oracle agreement catches missing facts at scale. | Sensible | Run the fixture corpus in CI on every Arelle upgrade |
| T9 | Formal protocol boundaries between resolve, select and validate | They are pure functions over fixed table schemas. Tests pin behavior. Fewer layers make them easier to change. | Sensible | Refactor if one stage grows beyond ~1k lines |
| T10 | Generic extensibility: pluggable engines, protocol versions, multiple hash schemes | No second engine or protocol is planned. Versions are single strings, bumped on output change. | Sensible | — |
| T11 | Dependence on SEC-generated companions (`MetaLinks`, `FilingSummary`) | They are evidence, not truth, and are cross-checked against filed role definitions and taxonomy packages. | Sensible | Verify availability on older filings in P2 |
| T12 | Dependence on external oracles (`companyfacts`, FSDS) | Validation only. Outputs never depend on them. | Sensible | If an oracle disappears, validation weakens; publication still works |
| T13 | Scope sequencing: annual before quarterly/YTD, consolidated before segments | This follows research value and difficulty. Counterexamples stay as tests so nothing is silently mis-published. | Accept explicitly | Stage 4 when users need quarterly data |
| T14 | Structural-proof auto-acceptance (Tier 3) without per-claim review | Proofs are deterministic, recorded and measured. A policy can be switched off. | Accept explicitly | Tier-3 precision below threshold disables the policy |
| T15 | Keeping ~55k words of rationale in the working tree | Git history keeps it; one current architecture document replaces it. | Sensible | — |

## 4. What must not be traded away

A lean design is only acceptable if these remain intact. None of the recommendations touch them.

- **Immutability** of raw bytes; SHA-256 addressing; offline extraction.
- **Values:** `Decimal`, lexical preservation, decimals, units, nil facts, dimensions, and
  duplicates retained as evidence.
- **Relations:** exact vs broader, narrower and related. Only exact is published under a contract's
  name.
- **Scope:** segment vs consolidated, parent vs total, GAAP vs non-GAAP, quarter vs YTD. Each is a
  contract distinction or a typed non-publication, never an approximation.
- **Traceability:** every value resolves to fact ids, rule ids, filing and acceptance time.
- **LLM role:** LLMs never approve.

## 5. Net judgement

- **Sensible (T1, T5, T8–T12, T15).** These remove machinery whose only job was to protect state
  that is either rebuildable or better held in Git.
- **Accept explicitly (T2, T3, T7, T13, T14).** Together they shift the assurance model from human
  attestation per decision to measured quality per policy. That is the substantive change, and it
  deserves an ADR.
- **Future risk (T4, T6).** These are real but observable. Global-rule blast radius is managed by
  measurement. Multi-user needs have a clear trigger and a known upgrade path.
