# 03 — Functionality and code-size inventory

LOC is used here as a diagnostic of where effort and maintenance cost sit, not as a quality metric.

## Counting method

- **Scope:** Git-tracked `*.py` files (`git ls-files '*.py'`). This includes `src/`, `migrations/`,
  `scripts/` and `tests/` (with `tests/helpers/`). No generated or vendored code is tracked: `.venv`
  is untracked, and `uv.lock`, YAML, SQL and Markdown are excluded.
- **Physical** lines are all lines. **Code** lines exclude blank lines and `#` comment lines;
  docstrings are counted as code.
- **Assignment** is by path pattern, one capability per file. The script is in
  [A](A-evidence-and-method.md#loc-inventory-script). Files that serve two capabilities are assigned
  to their dominant one, so boundaries are approximate to about ±10%.
- **Nature** of the code:
  - **Essential** code encodes SEC, XBRL or financial domain knowledge that any design needs.
  - **Infrastructure** is generic plumbing that any design needs in some form.
  - **Supporting** code exists because of a specific design choice: verification layers, codecs,
    governance, acceptance harnesses.

## Inventory by capability

| # | Capability | Main modules | Prod phys / code | Test phys / code | Nature | Overlaps |
|---|---|---|---:|---:|---|---|
| A | SEC access and acquisition | `sec/client`, `sec/accession`, `sec/submissions`, `sec/ssrf`, `ingestion/acquisition`, `ingestion/report_input` | 1,976 / 1,769 | 1,385 / 1,172 | Infrastructure with essential SEC rules | report-input selection re-validated in F |
| B | DTS closure capture and offline replay | `xbrl/closure`, `xbrl/arelle_env`, `xbrl/network_guard`, `domain/uri`, `xbrl/uri` | 1,182 / 1,005 | 1,059 / 941 | Supporting (replaceable by taxonomy packages) | offline guarantee also enforced in D (worker guard) and C (hashes) |
| C | Immutable storage and bundle model | `storage/objects`, `storage/bundles`, `domain/bundle`, `domain/report_key`, `domain/identifiers` | 1,403 / 1,169 | 485 / 405 | Infrastructure (essential) | four snapshot identities threaded through D, F, G |
| D | XBRL extraction (Arelle adapter) | `xbrl/extract`, `xbrl/worker`, `xbrl/locators`, `xbrl/config`, `xbrl/resolved_text` | 3,629 / 3,160 | 1,930 / 1,690 | Essential | invariant checks also in E, F, G |
| E | Extraction records and wire codecs | `xbrl/records`, `xbrl/source_records`, `xbrl/_source_build`, `xbrl/source_wire` | 3,064 / 2,651 | 556 / 500 | Supporting (accidental duplication) | two record families for one object; row building repeated in G |
| F | Verification, receipts and orchestration | `xbrl/upstream_inventory`, `xbrl/extraction_receipt`, `xbrl/integrity`, `xbrl/semantic`, `xbrl/source_extract`, `ingestion/source_extract`, `provenance` | 2,247 / 1,973 | 2,574 / 2,282 | Supporting | re-checks D; overlaps K |
| G | Source persistence (PostgreSQL + migrations) | `db/source`, `db/source_schema`, `ingestion/catalog`, `migrations/0001–0005` | 3,623 / 3,349 | 3,944 / 3,529 | Infrastructure | integrity `CHECK`s duplicate F; row dicts duplicate E |
| H | Document structure and sections | `parsing/sections`, `parsing/html`, `parsing/records`, `xbrl/source_documents` | 2,397 / 2,053 | 1,338 / 1,155 | Essential | — |
| I | Metric registry and mapping ledger | `registry/service`, `registry/mapping`, `registry/loader`, `registry/views`, `db/registry*`, `migrations/0002` (under G) | 2,091 / 1,793 | 2,390 / 2,061 | ~25% essential (contracts, relations, hashes); rest supporting (mirror, ledger) | contracts duplicated in YAML + DB mirror; history duplicated with Git |
| J | M0 benchmark validation | `tests/helpers/financial_cases`, `test_financial_benchmark_*` | 0 | 2,327 / 2,051 | Supporting (validates YAML structure, not values) | review-profile semantics restated in docs |
| K | Corpus acceptance | `corpus_acceptance`, `scripts/phase1_corpus_acceptance` | 1,555 / 1,408 | 669 / 588 | Supporting | overlaps F and the integration tests |
| L | CLI and settings | `cli`, `config` | 604 / 537 | 0 | Infrastructure | — |
| | **Total** | | **23,771 / 20,867** | **18,657 / 16,374** | | |

## Shares by nature

| Nature | Production lines | Share | Test lines (approx.) |
|---|---:|---:|---:|
| Essential domain logic (D, H, essential part of I) | ~6.5k | ~27% | ~3.6k |
| Infrastructure (A, C, G, L) | ~7.6k | ~32% | ~5.8k |
| Supporting mechanisms (B, E, F, K, most of I) | ~9.6k | ~41% | ~9.2k, including all of J |

The ratio matters more than any single number. **About 2.6 lines of supporting or infrastructure
code exist for every line that encodes domain knowledge.** Supporting mechanisms also carry about
half of all test lines.

## Largest concentrations

The ten largest production files hold 10,492 lines (44% of production).

| File | Lines | Comment |
|---|---:|---|
| `xbrl/extract.py` | 2,004 | Core fidelity logic; keep, split by concern |
| `xbrl/records.py` | 1,310 | Record family 1 plus dead codecs; collapse |
| `parsing/sections.py` | 1,288 | Core text logic; keep |
| `db/source.py` | 1,220 | PostgreSQL persistence; replace with the columnar writer |
| `corpus_acceptance.py` | 819 | Acceptance harness; fold into validation |
| `db/source_schema.py` | 817 | 17-table schema; fewer, wider tables |
| `migrations/0001_source_v2.py` | 792 | Schema for regenerable data |
| `xbrl/worker.py` | 769 | Arelle worker; keep, write columnar output directly |
| `registry/service.py` | 751 | Ledger and mirror workflow; replace with Git rules |
| `xbrl/source_wire.py` | 722 | Wire codec; delete once there is one schema |

By capability, the largest concentrations are persistence (G, 7.6k production and test lines),
verification and orchestration (F, 4.8k) and the registry (I, 4.5k). All three sit mainly in the
supporting and infrastructure categories.

## Non-code assets

- **Documentation:** ~55k words. That is 31.6k in `docs/architecture/`, 6.4k in ADRs, 13.7k in
  other `docs/` files and 3.6k in root Markdown files (`AGENTS.md` alone is 573 lines, `README.md`,
  changelog).
- **Fixtures:** 13 tracked files. `fixtures/analysis/financial-benchmark.yml` has 2,924 lines,
  9.4k words and 22 cases.
- **Registry:** `registry/metrics.yml` has 718 lines and 39 metrics; `registry/review-profile.yml`
  has 76 lines. The historical `semantic-registry/` archive is 4 files and 1,110 lines, and nothing
  in production uses it.

## Replacement potential (used by 04 and 08)

| Capability | Recommended treatment | Production Δ (est.) | Test Δ (est.) |
|---|---|---:|---:|
| A | Keep; remove dead aliases | −0.1k | — |
| B | Pinned taxonomy packages after a parity test; keep extension capture | −0.8 to −1.0k | −0.8k |
| C | Keep; one snapshot identity | −0.2 to −0.4k | −0.1k |
| D | Keep; fix locators; locate filer declarations only | −0.2 to −0.5k | adapt |
| E | One record schema; the worker writes columnar files | −2.0 to −2.4k | −0.4k |
| F | One dataset manifest + one integrity check | −1.4 to −1.8k | −1.8k |
| G | Embedded columnar store (DuckDB/Parquet) instead of PostgreSQL | −2.5 to −3.0k (new +0.5–0.8k) | −2.0k (port the rest) |
| H | Keep | — | — |
| I | Git-authored contracts and rules; delete mirror and ledger | −1.4 to −1.6k (new +0.3–0.5k) | −1.8k |
| J | Replace with a gold-value test against pipeline output | — | −2.1k (new +0.2k) |
| K | Fold into the validation harness | −1.0 to −1.3k | −0.5k |
| New | Resolve/select, validators and oracles, taxonomy dataset and MetaLinks parsing, review queue and export | +2.5 to +4.0k (includes the "new" items above) | +2 to +3k |

Net effect:

- Production code goes from 23.8k to roughly **14–19k lines, midpoint ~16k**, including the new
  capabilities.
- Tests go from 18.7k to roughly **10–12k lines**.
- Governance prose goes from ~55k to about **10–15k words**, assuming the architecture package is
  archived.

The new capabilities are the ones the current plan defers to M2–M4:

- mapping application;
- observation selection;
- validation against independent references;
- publishing.

These are estimates from the per-file inventory, not commitments. The largest uncertainty is G,
which depends on the storage decision in 04 and 08.
