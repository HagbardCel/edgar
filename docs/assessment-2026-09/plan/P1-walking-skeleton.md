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
- Running `annual-v1` on 10-Qs as if they were annual slots (P5).

## Architecture of this phase (only)

```text
registry/metrics.yml          ─┐
registry/decisions/**/*.yml    ├─ load in process (Git)
registry/gold/*.yml           ─┘
        │
        ▼
  expand decisions → exact QNames
        │
  edgar build            reads source.* (existing PostgreSQL)
        │
        ├─ metalinks.parse(bundle)     # definitions + statement roles
        ├─ resolve(facts, decisions)   # supports
        ├─ select(supports, contexts)  # 10-K / 10-K/A only
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
| `financials/decisions.py` | Load `registry/decisions/**/*.yml`; expand via `semantic_family` |
| `financials/metalinks.py` | Parse `MetaLinks.json` / `FilingSummary.xml` from a bundle |
| `financials/period.py` | Required-context + fiscal focus from `source.*` |
| `financials/decimals.py` | XBRL duplicate-fact consistency |
| `financials/resolve.py` | Fact → `(metric, relation, decision_id)` |
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
4. Leave the other **33** original keys untouched. After this edit the
   registry has **41** keys (39 + 2). The P1 selector set is the eight
   named above. `cash_and_cash_equivalents` and `capital_expenditure`
   stay in YAML as **legacy contracts** (different meaning). Do not
   delete or reuse them in P1–P5. P6 either deprecates them explicitly
   or keeps them as distinct published metrics. Diagrams that still say
   “39 metrics” mean the original family; the live count is 41 until a
   deprecation PR.

After the edit:

```bash
uv run edgar registry validate
```

Record the new `definition_hash` for each of the eight keys
(`edgar metrics show <key>`). You will paste those hashes into the
decision records in P1.2.

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

### P1.2 — Decision records and QName expansion

Create one accepted decision file per exact P1 mapping under
`registry/decisions/<metric>/`, plus broader/related files as below.
Do **not** treat the family string as a QName. Source facts keep
`{http://fasb.org/us-gaap/2023}Assets` (or a 2009
`{http://xbrl.us/us-gaap/2009-01-31}Assets`). The decision names the
family and local name; `expand_decision` uses
`semantic_family(namespace)` from P0.3, not a `fasb.org` prefix check.

One exact **accepted** decision per P1 metric:

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

Schema (Pydantic). This is a **Git current-state** record: one file is the
current conclusion. There is **no** `supersedes` field. Git history is the
revision log.

```text
id: str
metric: str                         # must exist in metrics.yml
source:
  family: us-gaap | dei | srt | issuer
  local_name: str
  issuer_cik?: str                  # required when family=issuer
  exclude_qnames?: [str]            # Clark QNames dropped from expansion
relation: "exact" | "narrower" | "broader" | "related"
scope: {exclude_ciks?: [str], exclude_sic_divisions?: [str]}
status: "accepted" | "rejected"
method: "curated" | "reviewed"
rationale: str
evidence: [{kind, source?, artifact_sha256?, concept?, accession?, locator?, quote?}]
reviewed: {by: str, on: date}
reviewed_occurrences?: [{accession, source_qname}]   # issuer decisions; P4
contract_hash: str                  # definition_hash of that metric *now*
```

**Uniqueness.** `edgar rules check` allows **one** current file per

```text
(metric, family, issuer_cik or "", local_name)
```

Scope is an attribute of that file, not part of the key. A second file
for the same key fails the check. There is no scope-overlap algebra.
Bank revenue is `exact` plus `exclude_ciks` / SIC exclusion, not a
second `narrower` file. A positive issuer override is not in this
schema; exclusion is the exception mechanism.

Evidence rules:

- `status: accepted` requires `rationale` **and at least one** evidence
  item with enough to find the source (`kind` plus MetaLinks/taxonomy
  artifact hash, or accession+locator). The quote is optional.
- A **current** `status: rejected` record (it can suppress the queue)
  requires the same minimal evidence pointer. Otherwise “new evidence”
  cannot be detected.
- `rejected` is for a proposed relation with **no** affirmative
  alternative. Do **not** also file `exact`/`rejected` when
  `relation: broader` + `status: accepted` already records the
  conclusion.

**Expansion (P1 algorithm, tested, not identity):**

- `family=us-gaap` + `local_name=Assets` covers any fact whose
  `semantic_family(namespace_uri) == "us-gaap"` and whose `local_name`
  is `Assets`, except Clark QNames listed in `exclude_qnames`.
  That includes `{http://xbrl.us/us-gaap/2009-01-31}Assets`.
- Record the expanded Clark QName on each support (`source_qname`).
- Do **not** store the family prefix as `source.concept` identity.

`status: rejected` files are valid and must load. Resolve ignores them
for supports. The review queue (P4) reads a rejected file **only when
its `contract_hash` equals the current contract**.

Stale-hash behaviour is **not** a choice:

```text
accepted + stale contract_hash  → fatal for resolve / edgar build
rejected + stale contract_hash  → load as inactive history
                                 → does not suppress the queue
                                 → edgar rules check lists stale/review-needed
                                 → does not fail edgar build
```

Add one **broader accepted** example for `us-gaap:Revenues` / `revenue`.
That single file is the current conclusion. Do not add a second
exact/rejected file for the same key. Add a **separate** rejected
example only for a concept where no affirmative relation was chosen.

`contract_hash` must equal `definition_hash(metric)` at load time for
every decision with operational effect. Do not add `metric-v2`.

For P1 it is enough to put JPM (`0000019617`) in
`scope.exclude_ciks` on the revenue exact decision. A real SIC map waits
for P2/P6.

**Tests (no database):**

- Expansion: `{http://fasb.org/us-gaap/2022}Assets`, `.../2024}Assets`,
  and `{http://xbrl.us/us-gaap/2009-01-31}Assets` are in the expansion;
  `{http://fasb.org/us-gaap/2023}Liabilities` is not.
- Two files for the same `(metric, family, issuer_cik, local_name)` fail
  `edgar rules check` (scope is not part of the key).
- A support row carries the exact Clark QName, not `us-gaap:Assets`.
- Stale `contract_hash` on an **accepted** decision raises at resolve/build.
- Stale `contract_hash` on a **rejected** decision loads as history and is
  proven **not** to suppress review; `edgar rules check` reports it.
- Current rejected decisions without evidence fail schema validation.
- `exclude_qnames` drops that Clark QName from the expansion.
- Unknown metric key raises.
- `status: rejected` does not produce supports.
- Accepted decisions without evidence fail schema validation.
- Broader decisions never have `relation: exact`.

**Validation gate P1.2**

```bash
uv run pytest -q tests/unit/test_financials_decisions.py
uv run edgar rules check    # validates decisions + hashes; exit 0
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
| `jpm_2024q2_revenue` | `0000019617-24-000453` | `revenue` | `unsupported` (`reason=wrong_form`) |
| `ko_2024q2_revenue` | `0000021344-24-000044` | `revenue` | `unsupported` (`reason=wrong_form`) |

Selector unit tests (not gold rows) must also cover:

- `us-gaap:Revenues` is **broader**, never selected as `revenue`.
- eBay extension
  `DisposalGroupIncludingDiscontinuedOperationProductDevelopment` is **not**
  an exact decision for `research_and_development` (the FY2023 R&D slot still
  comes from the standard concept).
- Restricted cash is **related**, not exact.

JPM/KO under `annual-v1` are **form-guard** tests (`reason=wrong_form`), not
industry or missing-fact tests. Industry exclude for banks is still
worth a **unit** test with a fake 10-K. A real 10-Q must not reach
concept matching.

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
   (`semantic_family(namespace_uri) == "dei"`, not only
   `http://xbrl.sec.gov/dei/%`).
2. That fact's context is the required context. Read
   `entity_identifier`, `start_lexical`, `end_lexical` / `instant_lexical`.
3. From the same context (or any undimensioned DEI cover fact in that
   context) read `DocumentFiscalYearFocus` and `DocumentFiscalPeriodFocus`
   when present.

A gold slot may name an explicit comparative period. Selection uses the slot
period when provided, else the required-context period.

Duration metrics match context `period_kind='duration'` and start/end.
Instant metrics match context `period_kind='instant'` and
`instant_lexical == end`. Do not put `annual` / `YTD` in this field.

Entity match uses the **SEC CIK scheme plus a 10-digit identifier**, not
“strip zeros on any string”:

```text
context.entity_scheme == "http://www.sec.gov/CIK"
normalize_cik(context.entity_identifier) == filing.cik
  (10-digit zero-padded)
```

Do not treat an identifier that merely digits-equal after stripping zeros
as a match if the scheme is missing or is not the SEC CIK scheme.

**Duplicate consistency** (`financials/decimals.py`).

Implement the **XBRL OIM interval rule**. Do **not** round both values to
the coarser `decimals` with `ROUND_HALF_EVEN`. That algorithm is wrong
(see the 2500/`-2` vs 3000/`-3` counterexample below).

XBRL `decimals` is a text field (`"-6"`, `"-8"`, `"INF"`).

```text
d = int(decimals)                 # except INF
half_width = 0.5 × 10^(-d)
interval = [value − half_width, value + half_width]   # closed
INF → [value, value]

duplicates consistent ⇔
  intersection(all intervals in the group) is non-empty

additional rule:
  same decimals ⇒ reported numeric values must be equal
```

- The **survivor** of a consistent group is the most precise filed value
  (largest `decimals` integer; `INF` wins). Keep its `resolved_numeric`
  and **all** fact ids as co-supports.
- Inconsistent group → selector status `conflict`.

Unit tests that must exist:

```text
# Walmart cash (still consistent; survivor is the more precise)
9867000000 decimals=-6  vs  9900000000 decimals=-8  → consistent
survivor = 9867000000

# OIM vs rounding counterexample (must be consistent, not conflict)
2500 decimals=-2  → interval [2450, 2550]
3000 decimals=-3  → interval [2500, 3500]
intersection non-empty → consistent
ROUND_HALF_EVEN to coarsest thousand would wrongly say conflict

# same decimals, unequal values → inconsistent
100 decimals=-2  vs  200 decimals=-2  → conflict

# INF
10 INF vs 10 INF → consistent
10 INF vs 11 INF → conflict
```

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
  fact_id, accession, concept_namespace, concept_local_name, source_qname
  metric, relation, decision_id
  application_method    # curated | reviewed | continuity  (P4 fills last two)
  tier                  # 1 | 2 | 4  (P4; P1 global exact = 1)
```

A support exists when the fact's concept is in an **accepted** decision's
QName expansion (family + local_name, minus `exclude_qnames`) and the
decision's `scope` (if any) does not exclude this issuer. Resolve does
**not** look at period, unit, or dimensions. That is selection. There is
no `exclude_when` field and no `rule_id`.

**Select (`as-filed`, annual-v1).** Forms **`10-K` and `10-K/A` only**.
If `source.filing.form` is `10-Q` or `10-Q/A`, emit
`status=unsupported`, `reason=wrong_form` for every annual metric and
stop. Do not look at facts. JPM and KO are regression tests for this
guard, not annual slots. Do not invent a separate status named
`wrong_form`.

For each (accession, metric) in the build request (P1: the eight metrics ×
the three annual 10-Ks and the 10-K/A, plus gold comparative slots):

Candidates are facts that have an **exact** support and all of:

- `value_status = 'valid'` and not nil and `resolved_numeric` present;
- no `context_dimension` rows;
- entity = required-context entity (SEC CIK scheme + padded CIK, P1.4);
- **USD unit — complete structure**, not `EXISTS local_name='USD'`:
  exactly one numerator measure whose QName is ISO 4217 USD
  (`http://www.xbrl.org/2003/iso4217`, `USD`); no denominator.
  `USD/shares` must not match. Use `source.unit_measure.side`,
  `ordinal`, `measure_namespace_uri`, `measure_local_name`;
- period matches the slot / required context as in P1.4.

Then:

```text
candidates
    ↓
group by XBRL data point (exact source QName + already-matched aspects)
    ↓
OIM duplicate reduction **within each group** (P1.4)
    ↓
one survivor per exact concept
    ↓
compare exact concepts
same Decimal value → one observation, many supports
different value    → conflict
```

Do **not** run OIM across different concepts. Two exact mappings
`A=10000 d=-3` and `B=10100 d=-2` may overlap as intervals and still
**conflict**.

Then:

1. No candidate → `missing`, unless the decision's scope excludes this
   issuer → `unsupported`.
2. Never pick a `broader` / `related` / `narrower` support as the published
   value.

Observation fields (P1 minimum):

```text
cik, accession, metric, fy, report_focus, period_role
period_start, period_end
status, reason, numeric, decimals, unit
decision_ids, fact_ids, relation, tier
available_at          # source.filing.accepted_at (may be null; do not substitute)
view                  # "as-filed"
```

**SQL.** Keep it in one place (`select.py` or a `.sql` file). The experiment
in [A](../A-evidence-and-method.md) is the starting query. Replace its
`EXISTS local_name='USD'` with the complete unit-structure test above. Add
the dimensions anti-join, entity-scheme match, and `value_status` filter.

**Tests (unit, fake rows):**

- Happy path: one undimensioned USD fact (one numerator, ISO 4217 USD, no
  denominator) → `value`.
- Extra dimension → not a candidate.
- `USD/shares` (numerator USD + denominator shares) → not a candidate.
- Entity scheme not `http://www.sec.gov/CIK` → not a candidate.
- Two inconsistent values **of the same concept** → `conflict`.
- Two different exact concepts with unequal values → `conflict` even if
  OIM intervals overlap.
- Walmart pair (same concept) → `value` `9867000000`.
- 2500/`-2` vs 3000/`-3` **same concept** → `value` (OIM-consistent).
- Broader-only → not `value` (and not silently used).
- Amendment with no statement facts → `missing`.
- 10-Q form → `unsupported` / `reason=wrong_form`, even if RFCWCEAT exists.

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

Use the documentation text when writing `rationale` / evidence on
decisions (manual). Use statement roles in a unit test that eBay FY2023
has a consolidated income statement entry. Selection in P1 does **not** require statement membership
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

1. Load **decisions** + contracts; fail on hash mismatch (accepted and
   rejected).
2. For each cataloged accession (or `--accession` list), run resolve →
   select → validate.
3. Write, atomically (temp dir + rename):
   - `observations.csv` — one row per slot; `Decimal` as string.
   - `observations.json` — same content, numbers as strings.
   - `findings.json`
   - `manifest.json`: git commit, `decisions_commit`, decision file hashes,
     extractor version, accession list, built_at (UTC).

No parquet dependency in P1 (`pyarrow` is not in `pyproject.toml`). CSV +
JSON is enough. Add parquet in P3 if the storage ADR says so.

CLI belongs in `src/edgar/cli.py` as a new typer app `build`, same style as
`filings extract`. JSON-on-`--json` for the summary line.

**Validation gate P1.8**

```bash
uv run edgar build --check-gold --output-dir /tmp/edgar-p1-build
# exit 0
# observations.csv has the 15 value rows with exact Decimals
# jpm and ko 10-Qs are unsupported / reason=wrong_form
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
| JPM 10-Q under `annual-v1` | `unsupported` / `reason=wrong_form` (form guard), not an annual value |
| KO 10-Q under `annual-v1` | same form guard |
| Broader `Revenues` | never published as `revenue` |
| `make check` | green |

Paste `edgar build` summary output in the PR.

## Pitfalls

- **Using `cash_and_cash_equivalents` for the gold cash slots.** Wrong
  contract. Use the new key.
- **Treating namespace year as part of the decision.** Then eBay 2022 and
  2023 need two files. That is the failure mode 08 called out. Use
  `exclude_qnames` only when drift is detected.
- **Selecting dimensional facts.** Segment and LegalEntity breakdowns will
  look like “better” revenue. They are out of scope. Undimensioned only.
- **Picking the rounded Walmart cash (`9.9` billion).** More precise is
  `-6` → `9867000000`. Do not implement “round both to coarser decimals.”
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
