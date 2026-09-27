# P1 — Walking skeleton

**Duration:** about two weeks. **Depends on:** accepted P0.1 ADR. P0.2/P0.3
are strongly preferred (extract is otherwise too slow to iterate) but not
required for the first unit tests.

## Goal

A developer can run one command on the local six-filing corpus and get
canonical observations for eight metrics. Those observations match the M0
gold values and the agreed counterexample statuses. Nothing in this phase
replaces PostgreSQL, the ledger, or the worker protocol.

Exit numbers (from [08](../08-migration-plan-assessment.md) and
[A](../A-evidence-and-method.md)):

- **13 / 13** gold value slots agree.
- Parent net income for eBay FY2023 **is published** (FASB definition of
  `NetIncomeLoss`).
- Walmart cash **is published** as `9867000000` (consistent duplicates;
  keep the more precise fact).
- The other counterexamples produce the statuses in the gold file below.

## Preconditions

- ADR 0014 (or equivalent) is accepted.
- Six corpus filings are extracted into local PostgreSQL (`source.*`).
  Accessions are in `fixtures/corpus.toml`.
- You have read [05](../05-mapping-strategy.md) §§1, 5, 6 and
  [04](../04-target-architecture.md) “Knowledge files” and “Interfaces”.

## Out of scope

- DuckDB, Parquet as the *store*, taxonomy packages, deleting the ledger (P3).
- Issuer extension auto-accept, review queue, LLMs (P4).
- `first-reported` / `latest-as-of` / 10-Q policies (P5).
- The other 31 metrics, bank-revenue contracts, segments (P6).
- New Alembic tables for observations. P1 observations are query output +
  files.
- Knowledge clocks, publication notices, review-profile machinery.

## Architecture of this phase (only)

```text
registry/metrics.yml     ─┐
registry/rules/*.yml      ├─ load in process (Git)
registry/gold/*.yml      ─┘
        │
        ▼
  edgar build            reads source.* (existing PostgreSQL)
        │
        ├─ metalinks.parse(bundle)     # definitions + statement roles
        ├─ resolve(facts, rules)       # supports
        ├─ select(supports, contexts)  # observations
        └─ validate(observations)      # findings
        │
        ▼
  var/builds/<id>/{observations.csv, observations.json, manifest.json, findings.json}
```

New code lives under `src/edgar/financials/` (name is fine; do not create
`semantic.*` tables). Keep it import-free of `scripts/` and of Arelle.

Suggested modules (do not add more without need):

| Module | Responsibility |
|---|---|
| `financials/rules.py` | Load and validate `registry/rules/*.yml` |
| `financials/metalinks.py` | Parse `MetaLinks.json` / `FilingSummary.xml` from a bundle |
| `financials/period.py` | Required-context + fiscal focus from `source.*` |
| `financials/decimals.py` | XBRL duplicate-fact consistency |
| `financials/resolve.py` | Fact → `(metric, relation, rule_id)` |
| `financials/select.py` | Slot → observation |
| `financials/validate.py` | Identities + gold comparison |
| `financials/build.py` | Orchestrate one build; write files |
| `financials/cli.py` | Wired from `src/edgar/cli.py` as `edgar build` |

## Work items

### P1.1 — Tighten the eight contracts in Git

**Why.** The live registry has 39 `metric-v1` keys. The benchmark invented two
keys that do not exist: `cash_excluding_restricted_cash`,
`cash_purchases_of_ppe`. Do not fork a `metric-v2` hash scheme. Edit YAML.

**Read first:** `registry/metrics.yml`, `src/edgar/registry/models.py`,
`src/edgar/registry/hashing.py`, `src/edgar/registry/loader.py`.

**Do this:**

1. **Keep** these existing keys as the P1 set: `revenue`, `total_assets`,
   `operating_cash_flow`, `operating_income`, `research_and_development`,
   `net_income_attributable_to_parent`.
2. **Add** `cash_excluding_restricted_cash` (instant, monetary). Definition:
   cash and cash equivalents **excluding** restricted cash. Do not reuse
   `cash_and_cash_equivalents` — that key allows restricted cash when the
   issuer buries it in the same line.
3. **Add** `cash_purchases_of_ppe` (duration, monetary). Definition: cash paid
   to acquire PP&E only. Do not reuse `capital_expenditure` — that key is
   broader (“similar long-lived productive assets”).
4. Leave the other 31 keys untouched.

After the edit:

```bash
uv run edgar registry validate
```

Record the new `definition_hash` for each of the eight keys
(`edgar metrics show <key>`). You will paste those hashes into the rules in
P1.2.

Do **not** run `edgar registry sync` unless you need the mirror for an
existing test. P1 does not use the mirror.

**Tests:** existing registry tests must stay green. Add a unit test that the
two new keys load and hash stably (pin the hashes in the test).

**Validation gate P1.1**

```bash
uv run edgar registry validate
uv run pytest -q tests/unit/registry
rg -n "cash_excluding_restricted_cash|cash_purchases_of_ppe" registry/metrics.yml
```

---

### P1.2 — Global rules file

Create `registry/rules/standard.yml`. One exact rule per P1 metric:

| `id` | `metric` | `concept` (family:local) |
|---|---|---|
| `revenue.us-gaap.RevenueFromContractWithCustomerExcludingAssessedTax` | `revenue` | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` |
| `total_assets.us-gaap.Assets` | `total_assets` | `us-gaap:Assets` |
| `operating_cash_flow.us-gaap.NetCashProvidedByUsedInOperatingActivities` | `operating_cash_flow` | `us-gaap:NetCashProvidedByUsedInOperatingActivities` |
| `operating_income.us-gaap.OperatingIncomeLoss` | `operating_income` | `us-gaap:OperatingIncomeLoss` |
| `research_and_development.us-gaap.ResearchAndDevelopmentExpense` | `research_and_development` | `us-gaap:ResearchAndDevelopmentExpense` |
| `net_income_attributable_to_parent.us-gaap.NetIncomeLoss` | `net_income_attributable_to_parent` | `us-gaap:NetIncomeLoss` |
| `cash_excluding_restricted_cash.us-gaap.CashAndCashEquivalentsAtCarryingValue` | `cash_excluding_restricted_cash` | `us-gaap:CashAndCashEquivalentsAtCarryingValue` |
| `cash_purchases_of_ppe.us-gaap.PaymentsToAcquirePropertyPlantAndEquipment` | `cash_purchases_of_ppe` | `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` |

Also record, as `relation: broader` or `related` (never exact):

| concept | metric | relation |
|---|---|---|
| `us-gaap:Revenues` | `revenue` | `broader` |
| `us-gaap:CashAndCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect` (only if you need it) | — | skip unless a test requires it |
| `us-gaap:RestrictedCashAndCashEquivalentsAtCarryingValue` | `cash_excluding_restricted_cash` | `related` |

Schema (Pydantic), one object per list item:

```text
id: str
metric: str                         # must exist in metrics.yml
concept_family: "us-gaap" | "dei" | "srt" | "issuer"
local_name: str
relation: "exact" | "narrower" | "broader" | "related"
contract_hash: str                  # definition_hash of that metric *now*
basis: str                          # one-line FASB/filer justification
reviewed: {by: str, on: date}
```

Matching a stored fact:

- `us-gaap` + `Assets` matches any `namespace_uri` starting with
  `http://fasb.org/us-gaap/` and `local_name == "Assets"`.
- Do **not** require the year suffix to match.

`contract_hash` must equal `definition_hash(metric)` at load time. If a
contract changes and the rule is not re-affirmed, load fails. That is the
whole versioning story for P1. Do not add `metric-v2`.

Optional `registry/rules/conditions.yml` in P1:

```yaml
- rule: revenue.us-gaap.RevenueFromContractWithCustomerExcludingAssessedTax
  exclude_when:
    sic_division: ["H"]   # finance/insurance; or a hard-coded CIK list for P1
```

For P1 it is enough to hard-code JPM (`0000019617`) as `unsupported` for
`revenue`. A real SIC map waits for P2/P6.

**Tests (no database):**

- Family match: `http://fasb.org/us-gaap/2022` and `.../2024` both hit
  `us-gaap:Assets`.
- Stale `contract_hash` raises.
- Unknown metric key raises.
- Broader rules never have `relation: exact`.

**Validation gate P1.2**

```bash
uv run pytest -q tests/unit/test_financials_rules.py
uv run edgar rules check    # add this command; exit 0
```

---

### P1.3 — Gold file (values + counterexamples)

Create `registry/gold/m0-annual.yml`. Copy **periods and accessions** from
`fixtures/analysis/financial-benchmark.yml`. Do **not** copy review-process
fields (`capability_state`, evidence pins, reviewers, `metric-v2` hashes).

Use live metric keys from P1.1.

**Value slots (status `value`):**

| id | accession | metric | expected numeric |
|---|---|---|---|
| `ebay_fy2022_revenue` | `0001065088-23-000006` | `revenue` | `9795000000` |
| `ebay_fy2022_total_assets` | `0001065088-23-000006` | `total_assets` | `20850000000` |
| `ebay_fy2022_operating_cash_flow` | `0001065088-23-000006` | `operating_cash_flow` | `2254000000` |
| `ebay_fy2023_revenue` | `0001065088-24-000036` | `revenue` | `10112000000` |
| `ebay_fy2023_total_assets` | `0001065088-24-000036` | `total_assets` | `21620000000` |
| `ebay_fy2023_operating_cash_flow` | `0001065088-24-000036` | `operating_cash_flow` | `2426000000` |
| `ebay_fy2023_operating_income` | `0001065088-24-000036` | `operating_income` | `1941000000` |
| `ebay_fy2023_rnd` | `0001065088-24-000036` | `research_and_development` | `1544000000` |
| `ebay_fy2023_net_income_parent` | `0001065088-24-000036` | `net_income_attributable_to_parent` | `2767000000` |
| `ebay_fy2023_cash` | `0001065088-24-000036` | `cash_excluding_restricted_cash` | `1985000000` |
| `ebay_fy2023_ppe` | `0001065088-24-000036` | `cash_purchases_of_ppe` | `456000000` |
| `walmart_fy2024_revenue` | `0000104169-24-000056` | `revenue` | `642637000000` |
| `walmart_fy2024_total_assets` | `0000104169-24-000056` | `total_assets` | `252399000000` |
| `walmart_fy2024_operating_cash_flow` | `0000104169-24-000056` | `operating_cash_flow` | `35726000000` |
| `walmart_fy2024_cash` | `0000104169-24-000056` | `cash_excluding_restricted_cash` | `9867000000` |

That is **15** value rows (the original 13 plus parent NI plus resolved
Walmart cash). The phase goal “13/13” is the original hand-verified set;
publishing the two resolved cases is an additional requirement.

**Counterexample slots (non-value):**

| id | accession | metric (or concept under test) | expected status |
|---|---|---|---|
| `walmart_fy2024_rnd` | `0000104169-24-000056` | `research_and_development` | `missing` |
| `ebay_10ka_revenue` | `0001065088-24-000094` | `revenue` | `missing` |
| `jpm_2024q2_revenue` | `0000019617-24-000453` | `revenue` | `unsupported` or `missing` (see below) |
| `ko_2024q2_revenue` | `0000021344-24-000044` | `revenue` | `missing` |

Selector unit tests (not gold rows) must also cover:

- `us-gaap:Revenues` is **broader**, never selected as `revenue`.
- eBay extension
  `DisposalGroupIncludingDiscontinuedOperationProductDevelopment` is **not**
  an exact rule for `research_and_development` (the FY2023 R&D slot still
  comes from the standard concept).
- Restricted cash is **related**, not exact.

JPM: if you shipped the P1.2 industry exclude, gold status is `unsupported`.
If not, the selector will return `missing` (no `RFCWCEAT` fact). Pick one,
write it in the gold file, and test that.

**Validation gate P1.3**

```bash
uv run pytest -q tests/unit/test_gold_schema.py
# file parses; 15 value rows; required counterexample rows present
# no capability_state / evidence_pins / metric-v2 fields
```

---

### P1.4 — Required context and decimal consistency (pure functions)

**Required context** (`financials/period.py`).

From `source.*` for one accession:

1. Find the undimensioned fact whose concept is `dei:DocumentPeriodEndDate`
   (`namespace_uri` like `http://xbrl.sec.gov/dei/%`).
2. That fact's context is the required context. Read
   `entity_identifier`, `start_lexical`, `end_lexical` / `instant_lexical`.
3. From the same context (or any undimensioned DEI cover fact in that
   context) read `DocumentFiscalYearFocus` and `DocumentFiscalPeriodFocus`
   when present.

A gold slot may name an explicit comparative period. Selection uses the slot
period when provided, else the required-context period.

Duration metrics match `period_kind='duration'` and start/end.
Instant metrics match `period_kind='instant'` and `instant_lexical == end`.

Entity match: strip leading zeros on both sides before comparing.

**Duplicate consistency** (`financials/decimals.py`).

XBRL `decimals` is a text field (`"-6"`, `"-8"`, `"INF"`).

- `INF` is exact. Two `INF` values agree only if the `Decimal`s are equal.
- Otherwise the **coarser** accuracy is `min(int(dec_a), int(dec_b))`
  (because `-8 < -6`). Round both values to that quantum
  `10 ** (-decimals)` using `decimal.ROUND_HALF_EVEN`. They are consistent
  if the rounded values are equal.
- The **survivor** of a consistent pair is the more precise fact (larger
  `decimals` integer; `INF` wins). Keep its `resolved_numeric` and its fact
  id. Record the other fact ids as co-supports.

Unit test that must exist:

```text
9867000000 decimals=-6  vs  9900000000 decimals=-8  → consistent
survivor = 9867000000
```

Inconsistent pair → selector status `conflict`.

**Validation gate P1.4**

```bash
uv run pytest -q tests/unit/test_financials_decimals.py tests/unit/test_financials_period.py
```

No database in these tests. Fabricate tiny context/fact rows as dicts.

---

### P1.5 — Resolve and select

**Resolve.** For each fact in a report, emit zero or more supports:

```text
Support:
  fact_id, accession, concept_namespace, concept_local_name
  metric, relation, rule_id
```

A support exists when the fact's concept matches a rule and the rule's
`exclude_when` (if any) does not fire. Resolve does **not** look at period,
unit, or dimensions. That is selection.

**Select (`as-filed`, annual-v1).** For each (accession, metric) in the build
request (P1: the eight metrics × the six accessions, plus gold comparative
slots):

Candidates are facts that have an **exact** support and all of:

- `value_status = 'valid'` and not nil and `resolved_numeric` present;
- no `context_dimension` rows;
- entity = required-context entity;
- USD unit (`unit_measure.measure_local_name = 'USD'`);
- period matches the slot / required context as in P1.4.

Then:

1. Collapse identical `Decimal` values to one observation, many supports.
2. Collapse consistent-but-unequal values (P1.4) to the survivor.
3. Else `conflict`.
4. No candidate → `missing`, unless the rule is excluded → `unsupported`.
5. Never pick a `broader` / `related` / `narrower` support as the published
   value.

Observation fields (P1 minimum):

```text
cik, accession, metric, fy, fp, period_start, period_end, period_type
status, numeric, decimals, unit
rule_ids, fact_ids, relation
available_at          # source.filing.accepted_at (may be null; do not substitute)
view                  # "as-filed"
```

**SQL.** Keep it in one place (`select.py` or a `.sql` file). The experiment
in [A](../A-evidence-and-method.md) is the starting query. Add the dimensions
anti-join, USD check, and `value_status` filter as shown there.

**Tests (unit, fake rows):**

- Happy path: one undimensioned USD fact → `value`.
- Extra dimension → not a candidate.
- Two inconsistent values → `conflict`.
- Walmart pair → `value` `9867000000`.
- Broader-only → not `value` (and not silently used).
- Amendment with no statement facts → `missing`.

**Validation gate P1.5**

```bash
uv run pytest -q tests/unit/test_financials_resolve.py tests/unit/test_financials_select.py
```

---

### P1.6 — MetaLinks parser

**Read first:** any local `MetaLinks.json` (logical path
`accession/MetaLinks.json` in a bundle). Example definitions are quoted in
[A](../A-evidence-and-method.md).

Pure function:

```text
parse_metalinks(bytes) -> MetaLinksView
  tags: { "us-gaap_NetIncomeLoss": {documentation, auth_ref, crdr, xbrltype, ...} }
  statements: [{role, longName, groupType, shortName}]
```

Only `groupType == "statement"` is a primary statement. If `MetaLinks.json`
is absent, return an empty view (do not fail the build). `FilingSummary.xml`
is a fallback for statement titles only; skip it in P1 if MetaLinks exists
on all six filings (it does).

Use the documentation text when writing `basis` on rules (manual). Use
statement roles in a unit test that eBay FY2023 has a consolidated income
statement entry. Selection in P1 does **not** require statement membership
(the required-context undimensioned fact is enough). P4 will use this for
`unmapped_candidate`.

**Do not** persist MetaLinks into PostgreSQL in P1.

**Validation gate P1.6**

```bash
uv run pytest -q tests/unit/test_metalinks.py
# NetIncomeLoss documentation contains "attributable to the parent"
# ≥ 1 statement role on the eBay FY2023 fixture bytes (committed testdata
#    excerpt, not the whole file if you can avoid it)
```

Commit a **small excerpt** of MetaLinks (the `NetIncomeLoss` tag + one
statement) under `tests/fixtures/`, not a 5 MB copy.

---

### P1.7 — Identity validators

`financials/validate.py`. P1 ships two identities, both computed from
`source.*` facts in the **same undimensioned required-context period**, not
from published observations only.

1. **NCI split** (when all three exist):
   `ProfitLoss = NetIncomeLoss + NetIncomeLossAttributableToNoncontrollingInterest`
   within the coarser decimals of the three.
2. **Balance sheet** (when all three exist):
   `Assets = Liabilities + StockholdersEquity`
   (local names `Assets`, `Liabilities`, `StockholdersEquity`). If the
   equity concept is missing, finding is `not_applicable`.

Finding statuses: `pass` | `fail` | `not_applicable`. A `fail` does **not**
block export in P1; it is recorded on the observation / in `findings.json`.
A gold-value mismatch **does** fail `edgar build` when `--check-gold` is set
(default on in tests).

**Validation gate P1.7**

```bash
uv run pytest -q tests/unit/test_financials_validate.py
# constructed triples that pass, fail, and omit a term
```

---

### P1.8 — `edgar build` and export

Wire a command:

```text
edgar build --data-root var --check-gold --output-dir var/builds/p1
```

Behavior:

1. Load rules + contracts; fail on hash mismatch.
2. For each cataloged accession (or `--accession` list), run resolve →
   select → validate.
3. Write, atomically (temp dir + rename):
   - `observations.csv` — one row per slot; `Decimal` as string.
   - `observations.json` — same content, numbers as strings.
   - `findings.json`
   - `manifest.json`: git commit, rules file hashes, extractor version,
     accession list, built_at (UTC).

No parquet dependency in P1 (`pyarrow` is not in `pyproject.toml`). CSV +
JSON is enough. Add parquet in P3 if the storage ADR says so.

CLI belongs in `src/edgar/cli.py` as a new typer app `build`, same style as
`filings extract`. JSON-on-`--json` for the summary line.

**Validation gate P1.8**

```bash
uv run edgar build --check-gold --output-dir /tmp/edgar-p1-build
# exit 0
# observations.csv has the 15 value rows with exact Decimals
# jpm revenue is unsupported or missing as pinned
# ebay 10-K/A revenue is missing
# walmart rnd is missing
# manifest.json contains extractor version and a commit hash
```

---

### P1.9 — Pipeline test replacing the static benchmark validators

Add `tests/integration/test_p1_gold_build.py` (marker `database`):

- Assumes the six filings can be extracted into `edgar_test` **or** reads the
  developer's `edgar` database only if you document that as a local-only
  opt-in. Prefer: extract the rich/small fixtures for unit tests, and one
  integration test that runs `build` against whatever source rows the test
  DB has after a targeted persist of the three annual 10-Ks.

Practical path that respects “no live SEC in default tests”:

- If the integration test cannot see the corpus bundles, skip with
  `pytest.skip` unless `EDGAR_DATA_ROOT` points at `var/` **and** the
  accessions are present. Mark that case `corpus` if you add a marker; do
  not mark it `network`.
- Unit tests of select/resolve must carry the 13/13 proof with fabricated
  rows so CI is green without `var/`.

Do **not** delete `tests/helpers/financial_cases.py` in P1 (noise, and
unrelated PRs may still load it). You may stop adding to it. Deletion is P3.

**Validation gate P1.9**

```bash
uv run pytest -q tests/unit/test_financials_select.py tests/unit/test_gold_schema.py
# 13/13 (and the two resolved extras) proven on fake or real rows
```

## Phase exit gate

```bash
make check
uv run edgar rules check
uv run edgar build --check-gold --output-dir /tmp/edgar-p1-build
```

Expected:

| Check | Result |
|---|---|
| 13 original gold values | exact `Decimal` match |
| eBay FY2023 parent NI | `2767000000` |
| Walmart cash | `9867000000`, not `conflict` |
| Walmart R&D | `missing` |
| eBay 10-K/A revenue | `missing` |
| JPM revenue | `unsupported` or `missing` as pinned |
| KO quarterly revenue under annual selector | `missing` |
| Broader `Revenues` | never published as `revenue` |
| `make check` | green |

Paste `edgar build` summary output in the PR.

## Pitfalls

- **Using `cash_and_cash_equivalents` for the gold cash slots.** Wrong
  contract. Use the new key.
- **Treating namespace year as part of the rule.** Then eBay 2022 and 2023
  need two rules. That is the failure mode 08 called out.
- **Selecting dimensional facts.** Segment and LegalEntity breakdowns will
  look like “better” revenue. They are out of scope. Undimensioned only.
- **Picking the rounded Walmart cash (`9.9` billion).** More precise is
  `-6` → `9867000000`.
- **Substituting filing date for `accepted_at`.** If `accepted_at` is null,
  leave `available_at` null.
- **Adding observation tables.** Rebuildable output stays in
  `var/builds/`.
- **Calling Arelle from `financials/`.** Selection reads `source.*` only.

## Stop and ask if

- A gold value does not reproduce after the selector tests pass (the gold
  period may be a comparative; re-read the benchmark slot).
- You think you need a new hash scheme or a ledger row to ship P1.
- JPM unexpectedly returns a revenue value (then the exact concept is
  present and the industry exclude is required, not optional).
