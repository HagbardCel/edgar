# P6 — Breadth

**Duration:** ongoing. **Depends on:** P4 and P5 exit gates.

## Goal

A published annual (and, where P5 exists, quarterly) dataset covering:

- all **39** contracts in `registry/metrics.yml` that still make sense after
  P1's two added keys (41 total, or 39 if you later merge unused ones);
- industry-specific contracts where a global exact rule is wrong (bank
  revenue is the type case);
- an explicit **segment** policy or an honest `unsupported` for dimensional
  metrics;
- a gold set on the order of **200 issuer-years × 8 core metrics**, plus
  spot labels for the rest;
- extraction of a multi-year 10-K/10-Q history, bounded and retrieved
  through the existing client.

The release artifact is a `edgar publish` snapshot: observations + support
+ findings + manifest. Quality is a table: metric × industry × year × tier.

## Preconditions

- Tiered mapping (P4) and time views (P5) work on the eight core metrics.
- P2-style quality report is a normal `build` output.
- Storage is whatever P3 implemented.

## Out of scope

- Web apps, queues, cloud, security master, market data (unless a later
  product request).
- Maximizing coverage by relaxing exact/undimensioned/USD.
- LLM approval.
- New form types beyond 10-K / 10-Q / amendments.

## Work items

### P6.1 — Remaining income-statement / balance-sheet / cash-flow metrics

For each remaining key in `registry/metrics.yml`, add **one** exact
accepted decision (or an explicit `unsupported` with reason) under
`registry/decisions/<metric>/`.

Suggested first wave (usually one obvious US-GAAP local name):

| Metric key | Typical exact local name (verify in taxonomy + MetaLinks) |
|---|---|
| `cost_of_revenue` | `CostOfRevenue` or `CostOfGoodsAndServicesSold` — **measure both; do not guess** |
| `gross_profit` | `GrossProfit` |
| `operating_expenses` | often **no** single exact tag → `unsupported` or derived |
| `interest_expense` | `InterestExpense` |
| `income_tax_expense` | `IncomeTaxExpenseBenefit` |
| `net_income` | `ProfitLoss` (total, including NCI) — distinct from parent |
| `current_assets` | `AssetsCurrent` |
| `current_liabilities` | `LiabilitiesCurrent` |
| `stockholders_equity` / `shareholders_equity` | `StockholdersEquity` |
| `long_term_debt` | often several tags → inspect before one exact rule |
| `diluted_eps` | `EarningsPerShareDiluted` |
| `weighted_average_shares_diluted` | `WeightedAverageNumberOfDilutedSharesOutstanding` |

If two standard concepts are both plausible and values can differ, do
**not** pick. Either add scope conditions or leave `missing` /
`unmapped_candidate` until a reviewer writes the decision.

Each new decision PR must include: at least one evidence pointer (MetaLinks
or taxonomy artifact), FSDS or spike frequency, and 5 gold slots from
rendered statements.

**Validation gate P6.1** (repeat per wave)

```bash
uv run edgar rules check
uv run edgar build --check-gold
# no drop in core-8 precision
# new metric: n_gold ≥ 5 and precision reported
```

---

### P6.2 — Industry conditions

Replace the P1 JPM hard-code with a real map:

- CIK → SIC from submissions or a committed `registry/industry/sic.yml`
  built from retrieved submissions JSON (hashed in the object store).
- `scope.exclude_sic_divisions: [H]` on product-revenue decisions.
- New contracts if you need them, e.g. `net_interest_income` for banks —
  **new key**, do not overload `revenue`.

**Validation gate P6.2**

```bash
uv run pytest -q tests/unit/test_industry_conditions.py
# JPM revenue = unsupported (product RFCWCEAT)
# eBay / Walmart revenue unchanged
```

---

### P6.3 — Segment policy (explicit or never)

Default remains: **undimensioned only**.

If a named consumer needs a segment series, write a one-page policy:

- which axis (e.g. `StatementBusinessSegmentsAxis`);
- how members are identified (filer extension members — no silent mapping
  across issuers);
- that segment observations are a different metric key or a dimension
  column, never a drop-in for consolidated.

Until that policy exists, dimensional facts stay out of `select`.

**Validation gate P6.3**

```bash
uv run pytest -q tests/unit/test_quarterly_select.py
# KO segment revenue still not published as consolidated revenue
```

---

### P6.4 — Gold set growth and drift sample

Grow `registry/gold/` toward ~200 issuer-years × 8 core metrics,
stratified like P2.2. Double-label ~10%. Each quarter add a fresh
stratified sample (new file, do not silently edit old labels).

Label from SEC-rendered statements (R files in the bundle), not from
`companyfacts` and not from the selector.

**Validation gate P6.4**

```bash
uv run edgar build --check-gold --require-precision-floor
# gold/README.md states n, double-label rate, last sample date
```

---

### P6.5 — History extract and `edgar publish`

Bounded retrieve+extract of 10-K/10-Q history for the gold issuers, then
widening. Use `--jobs` from P2. Respect the SEC client.

`edgar publish <name>` freezes:

```text
publications/<name>/<id>/
  observations.parquet-or-csv
  supports.csv
  findings.json
  manifest.json      # code commit, decisions_commit, extractor, input hashes
```

The directory is write-once. A second publish gets a new id.

**Validation gate P6.5**

```bash
uv run edgar publish core-annual-v1
# manifest verifies; re-running publish does not overwrite
# latest quality report attached
```

---

### P6.6 — Quality report as the release note

Publish metric × industry × year × tier:

- coverage, precision, oracle agreement, identity pass, conflict rate,
  unmapped rate, stability.

This file **is** the release note. Do not claim “complete US-GAAP coverage”.

**Validation gate P6.6**

The published snapshot contains the report. Core-8 non-financial coverage
and precision are quoted with denominators. Bank revenue is not reported
under `revenue`.

## Phase exit gate

There is no single “P6 done”. A wave is done when its gate passes and the
published report is updated. Stop expanding metrics when the next
decision would be a guess.

## Pitfalls

- **One exact tag for `long_term_debt` or `operating_expenses` without
  looking at the statement.** Those are families, not tags.
- **Reusing `revenue` for banks.** New contract.
- **Labeling gold from the selector.** That tests the test.
- **Uncontrolled retrieve.** Always a committed accession list.

## Stop and ask if

- A metric's spike coverage is < 40% after a careful decision — it may be a
  P4 residual, not a missing synonym.
- You are about to add a generic mapping DSL or ontology. That is outside
  this sequence.
