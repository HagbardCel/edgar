# 06 — Gaps and improvement opportunities

"Important" means the issue affects correctness, the ability to reach the mission, scale, or the
amount of human work. "Optional" items are worthwhile refinements that can wait or be decided by
measurement.

Effort is a rough estimate for one experienced developer. LOC deltas refer to production code
(03).

## Overview

| # | Issue | Class | Effort | Effect |
|---|---|---|---|---|
| G1 | No interpretation layer (resolve → select → validate) | Important | 1–2 weeks | First canonical values |
| G2 | Mapping effort scales with filings × metrics | Important | Policy + 3–5 days of rules | Human work drops from O(filings) to O(semantics) |
| G3 | Quadratic locator scans (~80–90 of ~94 s per 10-K) | Important | Hours | ~4–10× faster extraction |
| G4 | Whole standard taxonomy stored per report | Important | 2–4 days | −95% declaration rows; −47% DB bytes today |
| G5 | Benchmark never executed; contracts forked | Important | 1–2 days | Real acceptance test |
| G6 | SEC-generated semantics in bundles unused | Important | 1–2 days | Definitions and statement classification for free |
| G7 | No independent measurement of quality | Important | 2–4 days | Quality becomes a number |
| G8 | Scale never measured | Important | 1 week | Grounded infrastructure decisions |
| G9 | Knowledge authority split four ways | Important | 2–3 days | One source of truth; −1.5k lines |
| G10 | Two record families + wire codec; verification in 13 files | Important | 1–2 weeks | −3.4 to −4.2k lines; cheaper change |
| G11 | Governance and documentation overhead | Important | 2–3 days | Faster iteration; true docs |
| O1–O12 | Refinements | Optional | — | See below |

## Important

### G1 — No interpretation layer

- **Evidence.** No code turns facts into observations. The plan schedules the first values for M3,
  after M1A, M1B (conditional) and M2.
- **Action.** Build the walking skeleton ([08](08-migration-plan-assessment.md), P1):
  - Git rules for the eight benchmark contracts;
  - the required-context selector with duplicate consistency;
  - identity validators;
  - a Parquet/CSV export with support fact ids.

  Target 800–1,500 lines including tests.
- **Why first.** It is the only way to test the plan's central assumption, the difficulty of
  mapping, against data.

### G2 — Mapping effort scales with filings

- **Evidence.** The target architecture requires the following:
  - claims scoped to issuer + listed reports;
  - affirmative definition evidence per exact claim;
  - human occurrence-level qualification of consolidated scope, basis and sign.

  Yet the global rule experiment reproduces all 13 benchmark values without any of it.
- **Action.** Adopt the tiered strategy in [05](05-mapping-strategy.md): global rules, continuity,
  structural proof, and review of the residual only.

### G3 — Quadratic locator computation

- **Evidence.**
  - `xbrl/locators.py` calls `_attribute_is_unique(root, "//*[@id=$value]", …)` per element.
  - That is a full-document XPath scan each time.
  - 500 locators over `us-gaap-2023.xsd` take 2.4–2.5 s (two runs), extrapolating to ~82–87 s for
    its 17,221 id-bearing elements.
  - A one-pass counter over all ids takes ~4 ms.
- **Action.** Build an id-count index once per document. Additionally, stop locating standard
  declarations no fact uses (see G4). Keep the locator output identical, and prove it with the
  existing locator tests plus a golden diff on the fixture corpus.
- **Payoff.** For Walmart, only ~7–11 s of the ~94 s remain outside the scan, so expect roughly
  10–25 s per 10-K before also dropping unused declarations. This matters more than any architectural choice
  for reaching scale.

### G4 — Standard taxonomy stored per report

- **Evidence.** There are ~18.5k `concept_declaration` rows per report, while 376–871 concepts are
  used. `concept_declaration` and `concept` take 59 of 125 MiB. At full history that projects to
  ~7×10⁹ rows and ~3 TB.
- **Action.**
  - Parse each taxonomy release once into taxonomy tables.
  - Store per report only the filer's declarations and the concepts its facts use.
  - Join standard metadata by `(namespace, local_name)`.

### G5 — The benchmark is paperwork, not a test

- **Evidence.**
  - 2,327 test lines validate the YAML's structure. None compares its values to pipeline output.
  - The fixture defines eight `metric-v2` contracts that fork from the 39 live `metric-v1`
    contracts. Two of the fixture's keys do not exist in `registry/metrics.yml`.
- **Action.**
  - Extract the values and counterexamples into a gold file keyed by live contract ids.
  - Add one test that runs `build` on the fixture corpus and compares against the gold file.
  - Retire the static validators.

### G6 — Semantics already in every bundle are unused

- **Evidence.** `MetaLinks.json` is captured and hashed but never parsed. Per used tag, it carries:
  - the FASB documentation text;
  - authoritative references;
  - balance type and data type;
  - presentation roles.

  Per report, it carries the statement/disclosure classification and titles. `FilingSummary.xml` and
  the R files are also present. This is exactly the "affirmative definition" evidence that ADR 0013
  plans to acquire separately.
- **Action.** Parse `MetaLinks.json` and `FilingSummary.xml` into extraction tables (~150–250
  lines).
  - For pre-Inline filings, verify availability in the scale spike.
  - Fall back to taxonomy packages and EDGAR role-definition conventions where it is missing.

### G7 — Quality is not measured

- **Evidence.** There is no oracle comparison, no identity checks and no gold-value test. The
  plan's quality mechanism is review attestation.
- **Action.** Add three validators in P1–P2:
  - identity checks (balance sheet, cash roll-forward, NCI split, gross profit);
  - an SEC `companyfacts` agreement check;
  - a quality report per metric × tier × industry × year.

### G8 — Scale has never been exercised

- **Evidence.**
  - The system has never run beyond six filings.
  - Extraction takes ~100 s per 10-K.
  - One year of 10-K/10-Q filings (~26k) would be about 30 CPU-days of extraction today.
  - Storage, query and rebuild costs at 10³–10⁵ filings are unknown.
- **Action.** Run the scale spike (08, P2) on 500–1,000 filings across industries and years, after
  G3. Record:
  - throughput;
  - bytes per filing;
  - rebuild time;
  - query latency;
  - coverage and oracle agreement per metric.

### G9 — Knowledge authority is split four ways

- **Evidence.** Contracts and decisions are spread across four places:
  - `registry/metrics.yml`;
  - the `registry.canonical_metric` mirror;
  - the benchmark's own contracts;
  - the (never used) PostgreSQL ledger.

  The archived `semantic-registry/` is still in the tree.
- **Action.** Make Git files the only authority: contracts, rules, conditions, gold values. Delete
  the mirror, ledger and archive; Git history retains the archive. CI then checks:
  - schema;
  - `contract_hash` consistency;
  - rules referencing existing concepts;
  - gold-set regressions.

### G10 — Parallel representations and repeated verification

- **Evidence.**
  - 3,064 lines of records and codecs cover one extracted report.
  - The fact-count invariant is referenced in 13 files, including a DB `CHECK` and two migrations.
  - Implementation identity and lock digests are captured before *and* after extraction.
- **Action.**
  - Define one schema per table.
  - The worker writes Arrow/Parquet.
  - The parent validates schema and referential integrity once, as SQL anti-joins.
  - One count assertion at commit.
  - Golden counts on the fixture corpus in tests.
  - Delete the receipt as a separate artifact; the build and publication manifest carries the same
    identity fields.

### G11 — Governance overhead

- **Evidence.**
  - ~55k words of planning, ADR and review prose.
  - A 573-line `AGENTS.md` whose phase gates forbid the end-to-end work that would test the plan.
  - Documented status already lags the code.
  - 12 commits spent hardening the benchmark fixture's own validators.
- **Action.**
  - Keep a single short `docs/architecture.md` describing what exists.
  - Keep ADRs for decisions.
  - Move the M0–M5 package to `docs/archive/`, or delete it; Git keeps history.
  - Trim `AGENTS.md` to invariants, boundaries and commands (~150 lines).
  - Record decisions from measurements, not from anticipated review outcomes.

## Optional

| # | Opportunity | Why / when |
|---|---|---|
| O1 | Delete the residue flagged in August: `SecClient`, `CatalogConflict`, `SemanticWorkerError`, `LocatorProvenance`, `concept_id_str`, `resolve_document_id`, `AcquisitionObservation`, `WebCacheLike`, always-null `entry_document_id` | Cheap hygiene; do it with G10 |
| O2 | One snapshot identity (content hash of the filing manifest) instead of `report_key` + opaque bundle id + payload hash + descriptor SHA | Less threading; do it with the storage change |
| O3 | Pinned taxonomy packages instead of per-filing closure capture for standard taxonomies | After a parity test on the spike corpus; keep a small fetch-and-pin path for non-packaged URLs |
| O4 | DuckDB/Parquet instead of PostgreSQL for derived evidence | Decide with P2 numbers (04) |
| O5 | Parallel extraction (`--jobs N`, process pool) | Required for scale; trivial once each worker is independent |
| O6 | SEC bulk archives (`submissions.zip`, `companyfacts.zip`) for discovery and oracle data | Replaces thousands of per-CIK calls at scale |
| O7 | Arelle calculation validation results as extraction issues | Cheap extra validator |
| O8 | DQC rules via the Arelle plugin as sanity validators | After Stage 1, if error types warrant |
| O9 | Split `xbrl/extract.py` (2,004 lines) by concern: facts, contexts, networks, declarations | Readability; no behavior change |
| O10 | JSON output on all CLI commands; `edgar sql` shell | Makes the system easy to drive from scripts and coding agents |
| O11 | FSDS-based market census of concept usage per metric | Sizes Stage 2 before extracting at scale |
| O12 | Security master and market data joins | Out of current scope; `available_at` and CIK keys already support it later |
