# A — Evidence and method

All measurements were taken on 2026-09-27 against `main` at `799540d`, with a clean tree. The
environment was:

- macOS with Python 3.12 via `uv`;
- PostgreSQL 16 in the project's Docker Compose service;
- Arelle 2.43.1;
- the local data root `var/`, holding six published bundles and a 251 MiB object store.

Database access was read-only (`SET TRANSACTION READ ONLY`) against the local `edgar` database.

The scripts below are ad hoc diagnostics. They were run from the repository root with `uv run
python <script>` and kept outside `src/`, with no production dependency. They are reproduced here
so the numbers can be re-derived.

## Validation run

```text
$ make check
uv run ruff check .                  All checks passed!
uv run ruff format --check .         219 files already formatted
uv run pyright                       0 errors, 0 warnings, 0 informations
uv run edgar registry validate       metrics=39
uv run pytest -q -m "not database and not network"   398 passed, 109 deselected in 14.89s
uv run pytest -q -m "database and not network"       108 passed, 399 deselected in 23.86s
```

One network-marked test is deselected in both runs.

## Repository statistics

| Measure | Command | Result |
|---|---|---|
| History | `git log --reverse`, `git rev-list --count HEAD` | first commit 2026-07-30; 123 commits |
| Code + test churn | `git log --numstat --format= -- src tests migrations scripts` (summed) | +71,098 / −28,583 |
| Documentation churn | same, over `docs AGENTS.md README.md PLANNING-CHANGELOG.md` | +15,401 / −10,215 |
| M1A PRs #17, #18, #19 | `git diff --shortstat <merge>^1 <merge>` | +2,287/−91, +1,563/−31, +3,955/−34 |
| Documentation words | `wc -w` over `docs/architecture/*.md`, `docs/adr/*.md`, other tracked `docs/*.md`, root Markdown | 31,647; 6,392; 13,655; 3,554 |
| Benchmark | `wc -w`, `wc -l fixtures/analysis/financial-benchmark.yml` | 9,421 words; 2,924 lines; 22 cases; 8 embedded `metric-v2` contracts |
| Benchmark history | `git log -- fixtures/analysis/financial-benchmark.yml tests/helpers/financial_cases.py registry/review-profile.yml` | 12 commits, 2026-09-07 to 2026-09-20 |
| Fact-count invariant spread | `rg -l "upstream_item_fact_count\|selected_target_item_count\|arelle_item_fact_count" src migrations scripts` | 13 files |
| Benchmark use in tests | `rg -l "financial-benchmark\|financial_cases" tests src scripts` | 3 files, all static YAML validation |

## Database statistics

Output of `db_stats.py`:

```text
alembic_revision 0001_source_v2
registry_schema_present False
filings 6 · reports 6 · facts 15019 · concepts 56217 · concept_declarations 93690
relationships 18308 · labels 11664 · document_blocks 11091 · facts_undimensioned 4946
facts_by_family us-gaap 12549 · extension/other 2161 · dei 307 · srt 2
per_report_declared_vs_used
  0000019617-24-000453 (JPM 10-Q)      19213 declared / 871 used
  0000021344-24-000044 (KO 10-Q)       18809 / 376
  0000104169-24-000056 (WMT 10-K)      18565 / 410
  0001065088-23-000006 (eBay 10-K 22)  18312 / 595
  0001065088-24-000036 (eBay 10-K 23)  18527 / 591
  0001065088-24-000094 (eBay 10-K/A)     264 / 37
db_size 131.4 MB (125.3 MiB); concept_declaration 43.4 MB; concept 19.3 MB; relationship 15.1 MB; fact 13.9 MB
```

US-GAAP releases used by facts:

- 2022: eBay FY2022.
- 2023: eBay FY2023 and Walmart.
- 2024: JPM and KO.

<details><summary><code>db_stats.py</code></summary>

```python
"""Ad hoc read-only statistics over the local `edgar` database. Not production code."""
from sqlalchemy import create_engine, text

e = create_engine("postgresql+psycopg://edgar:edgar@localhost:5432/edgar")
Q = {
    "alembic_revision": "select version_num from public.alembic_version",
    "registry_schema_present": "select count(*) > 0 from information_schema.schemata where schema_name = 'registry'",
    "filings": "select count(*) from source.filing",
    "reports": "select count(*) from source.xbrl_report",
    "facts": "select count(*) from source.fact",
    "concepts": "select count(*) from source.concept",
    "concept_declarations": "select count(*) from source.concept_declaration",
    "relationships": "select count(*) from source.relationship",
    "labels": "select count(*) from source.concept_label",
    "document_blocks": "select count(*) from source.document_block",
    "facts_undimensioned": """select count(*) from source.fact f where not exists
        (select 1 from source.context_dimension d where d.context_id = f.context_id)""",
    "facts_by_family": """select case when k.namespace_uri like 'http://fasb.org/us-gaap/%' then 'us-gaap'
        when k.namespace_uri like 'http://xbrl.sec.gov/dei/%' then 'dei'
        when k.namespace_uri like 'http://fasb.org/srt/%' then 'srt' else 'extension/other' end, count(*)
        from source.fact f join source.concept k on k.id = f.concept_id group by 1 order by 2 desc""",
    "per_report_declared_vs_used": """select g.accession,
        (select count(*) from source.concept_declaration d where d.report_id = r.id),
        (select count(distinct f.concept_id) from source.fact f where f.report_id = r.id)
        from source.xbrl_report r join source.filing g on g.id = r.filing_id order by 1""",
    "db_size_mb": "select pg_database_size(current_database()) / 1e6",
    "largest_tables_mb": """select relname, pg_total_relation_size(c.oid) / 1e6 from pg_class c
        join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'source' and c.relkind = 'r'
        order by 2 desc limit 4""",
}
with e.connect() as c:
    c.execute(text("SET TRANSACTION READ ONLY"))
    for name, sql in Q.items():
        rows = c.execute(text(sql)).all()
        print(name, rows[0][0] if len(rows) == 1 and len(rows[0]) == 1 else rows)
```

</details>

## Extraction timing and locator cost

`time_extract.py` on the Walmart FY2024 10-K gave:

```text
us-gaap-2023.xsd id-bearing elements=17221
500 locators=2.52s -> extrapolated all=87s
one-pass id index=3.8ms
offline extraction=93.9s arelle=2.43.1   (facts=1400, contexts=378, relationships=2436)
```

An earlier run in the same session measured the following, using equivalent calls that were not
retained as a script:

- Walmart 92.9 s;
- eBay FY2023 105.0 s;
- 500 locators in 2.37 s, extrapolating to ~82 s;
- Arelle load-only replay of a captured bundle in 0.8 s.

The extrapolation assumes uniform per-element cost. The scan is `O(n)` per element over the
document, so the total is `O(n²)`.

<details><summary><code>time_extract.py</code></summary>

```python
"""Ad hoc timing: offline extraction of one bundle + locator cost on the US-GAAP schema.

Usage: uv run python time_extract.py bundles/<cik>/<accession>/<opaque>
"""
import sys
import time
from collections import Counter
from pathlib import Path

import lxml.etree as etree

from edgar.storage.objects import ObjectStore
from edgar.xbrl.extraction_receipt import load_bundle_ref
from edgar.xbrl.locators import element_locator
from edgar.xbrl.semantic import run_offline_extract

root = Path("var").resolve()
loaded = load_bundle_ref(data_root=root, bundle_dir=root / sys.argv[1])
bundle = loaded.bundle
store = ObjectStore(root)

schema = next(b for b in bundle.uri_bindings if b.document_uri.endswith("/elts/us-gaap-2023.xsd"))
data = (root / "objects" / "sha256" / schema.content_sha256[:2] / schema.content_sha256).read_bytes()
doc = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True))
with_id = [el for el in doc.iter() if isinstance(el.tag, str) and el.get("id")]
t = time.perf_counter()
for el in with_id[:500]:
    element_locator(el, document_uri=schema.document_uri)
per_500 = time.perf_counter() - t
t = time.perf_counter()
Counter(el.get("id") for el in doc.iter() if isinstance(el.tag, str))
index_s = time.perf_counter() - t
print(f"us-gaap-2023.xsd id-bearing elements={len(with_id)}")
print(f"500 locators={per_500:.2f}s -> extrapolated all={per_500 / 500 * len(with_id):.0f}s")
print(f"one-pass id index={index_s * 1000:.1f}ms")

t = time.perf_counter()
result = run_offline_extract(bundle, store)
elapsed = time.perf_counter() - t
rep = result.report
print(f"offline extraction={elapsed:.1f}s arelle={result.arelle_version}")
for name in ("facts", "concept_declarations", "contexts", "relationships"):
    value = getattr(rep, name, None)
    if value is not None:
        print(f"  {name}={len(value)}")
```

</details>

## Global-rule experiment

The rules are:

- one standard US-GAAP local name per benchmark metric;
- matched on any US-GAAP release namespace;
- undimensioned facts only;
- registrant entity;
- USD unit;
- the period of the EDGAR required context (the undimensioned context of
  `dei:DocumentPeriodEndDate`), or the benchmark slot's explicit period when one is given.

Identical values consolidate; differing values give `conflict`. The experiment deliberately does
**not** implement consistent-duplicate reduction, so the Walmart cash case shows as `conflict`.

Output of `uv run python global_rule_experiment.py fixtures/analysis/financial-benchmark.yml`:

```text
OK  ebay_fy2022_revenue_value                  expected=9795000000.00   got=9795000000
OK  ebay_fy2022_total_assets_value             expected=20850000000.00  got=20850000000
OK  ebay_fy2022_operating_cash_flow_value      expected=2254000000.00   got=2254000000
OK  ebay_fy2023_revenue_value                  expected=10112000000.00  got=10112000000
OK  ebay_fy2023_total_assets_value             expected=21620000000.00  got=21620000000
OK  ebay_fy2023_operating_cash_flow_value      expected=2426000000.00   got=2426000000
OK  walmart_fy2024_revenue_value               expected=642637000000.00 got=642637000000
OK  walmart_fy2024_total_assets_value          expected=252399000000.00 got=252399000000
OK  walmart_fy2024_operating_cash_flow_value   expected=35726000000.00  got=35726000000
OK  ebay_fy2023_operating_income_value         expected=1941000000.00   got=1941000000
OK  ebay_fy2023_rnd_value                      expected=1544000000.00   got=1544000000
--  ebay_fy2023_net_income_parent_value        expected_state=review_required rule_output=2767000000
OK  ebay_fy2023_cash_excluding_restricted_value expected=1985000000.00  got=1985000000
OK  ebay_fy2023_cash_ppe_purchases_value       expected=456000000.00    got=456000000
--  ebay_fy2023_disposal_product_development_rd_extension_narrower expected_state=unsupported rule_output=1330000000
--  walmart_fy2024_revenues_broader_than_revenue_contract          expected_state=review_required rule_output=642637000000
--  walmart_fy2024_cash_excluding_restricted_accuracy_review       expected_state=review_required rule_output=conflict
--  walmart_fy2024_rnd_missing                                     expected_state=missing rule_output=missing
--  ebay_10ka_amendment_revenue_review                             expected_state=review_required rule_output=missing
--  jpm_2024q2_revenue_bank_generalization_counterexample          expected_state=unsupported rule_output=missing
--  ko_2024q2_segment_revenue_narrower_ytd_counterexample          expected_state=review_required rule_output=missing
--  ebay_fy2023_restricted_cash_fv_related_not_exact               expected_state=review_required rule_output=1985000000
value cases agreeing: 13 / 13
```

Each non-value line reports the rule output for that case's *slot*. The questioned concept is never
used, because extensions, broader and related concepts are not in the rule table. Some slots
receive a value from the correct standard concept:

- FY2022 R&D, 1,330m, from `ResearchAndDevelopmentExpense`;
- Walmart revenue, from `RevenueFromContractWithCustomerExcludingAssessedTax`;
- cash, from `CashAndCashEquivalentsAtCarryingValue`.

The Walmart cash conflict consists of two facts, listed below. They are consistent under XBRL
decimal rounding.

```text
CashAndCashEquivalentsAtCarryingValue, 2024-01-31, undimensioned
  9867000000  decimals=-6  lexical "9,867"  scale=6  locator f-171
  9900000000  decimals=-8  lexical "9.9"    scale=9  locator f-492
```

The eBay FY2023 `MetaLinks.json` (`accession/MetaLinks.json`, sha256 `adf1b6a8…`) contains the
evidence the parent-NI case asked for:

```text
us-gaap_NetIncomeLoss  crdr=credit  monetaryItemType  auth_ref=[r195, r208, r252, …]
  "The portion of profit or loss for the period, net of income taxes, which is attributable to the parent."
us-gaap_Assets         crdr=debit   monetaryItemType
  "Sum of the carrying amounts as of the balance sheet date of all assets that are recognized. …"
statements: 0000003 - Statement - CONSOLIDATED BALANCE SHEET; 0000005 - Statement - CONSOLIDATED
  STATEMENT OF INCOME; 0000008 - Statement - CONSOLIDATED STATEMENT OF CASH FLOWS; …
```

<details><summary><code>global_rule_experiment.py</code></summary>

```python
"""Ad hoc experiment: global standard-concept rules + EFM required-context selector.

Read-only against the local `edgar` database. Not production code.
"""
import sys
from decimal import Decimal

import yaml
from sqlalchemy import create_engine, text

RULES = {  # metric -> ordered standard local names considered exact under the benchmark contracts
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax"],
    "total_assets": ["Assets"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "operating_income": ["OperatingIncomeLoss"],
    "research_and_development": ["ResearchAndDevelopmentExpense"],
    "net_income_attributable_to_parent": ["NetIncomeLoss"],
    "cash_excluding_restricted_cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "cash_purchases_of_ppe": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}
INSTANT = {"total_assets", "cash_excluding_restricted_cash"}

e = create_engine("postgresql+psycopg://edgar:edgar@localhost:5432/edgar")
bench = yaml.safe_load(open(sys.argv[1]))

def required_context(c, accession):
    # EFM: dei cover facts sit in the document's required context (fiscal period of the report).
    row = c.execute(text("""
        select x.start_lexical, x.end_lexical, x.entity_identifier
        from source.fact f
        join source.concept k on k.id = f.concept_id
        join source.context x on x.id = f.context_id
        join source.xbrl_report r on r.id = f.report_id
        join source.filing g on g.id = r.filing_id
        where g.accession = :a and k.local_name = 'DocumentPeriodEndDate'
          and k.namespace_uri like 'http://xbrl.sec.gov/dei/%'
          and not exists (select 1 from source.context_dimension d where d.context_id = x.id)
    """), {"a": accession}).one()
    return row

def candidates(c, accession, local_names):
    return c.execute(text("""
        select k.local_name, f.resolved_numeric, x.period_kind, x.start_lexical, x.end_lexical,
               x.instant_lexical, x.entity_identifier, f.decimals
        from source.fact f
        join source.concept k on k.id = f.concept_id
        join source.context x on x.id = f.context_id
        join source.xbrl_report r on r.id = f.report_id
        join source.filing g on g.id = r.filing_id
        where g.accession = :a and k.namespace_uri like 'http://fasb.org/us-gaap/%'
          and k.local_name = any(:names) and f.value_status = 'valid'
          and f.resolved_numeric is not null
          and not exists (select 1 from source.context_dimension d where d.context_id = x.id)
          and exists (select 1 from source.unit_measure m where m.unit_id = f.unit_id
                      and m.measure_local_name = 'USD')
    """), {"a": accession, "names": local_names}).all()

results = []
with e.connect() as c:
    c.execute(text("SET TRANSACTION READ ONLY"))
    for case in bench["cases"]:
        exp = case["expected"]
        metric = case["contract_ref"]["metric_key"]
        acc = case["report"]["accession"]
        slot = case.get("slot") or {}
        per = slot.get("period") or {}
        names = RULES.get(metric, [])
        try:
            start, end, entity = required_context(c, acc)
        except Exception:  # noqa: BLE001
            results.append((case["case_id"], exp.get("state"), exp.get("value"), "no-required-context", None))
            continue
        # benchmark may request a comparative period; honour the slot's explicit period when given
        want_start = per.get("start", start)
        want_end = per.get("end", per.get("instant", end))
        vals = set()
        for ln, v, kind, s, en, inst, ent, dec in candidates(c, acc, names):
            if ent.lstrip("0") != entity.lstrip("0"):
                continue
            if metric in INSTANT:
                if kind == "instant" and inst == want_end:
                    vals.add(Decimal(v))
            elif kind == "duration" and s == want_start and en == want_end:
                vals.add(Decimal(v))
        got = ("conflict" if len(vals) > 1 else (str(vals.pop()) if vals else "missing"))
        results.append((case["case_id"], exp.get("state"), exp.get("value"), got, names))

agree = 0
for cid, state, value, got, names in results:
    if state == "value":
        ok = got not in ("missing", "conflict") and Decimal(got) == Decimal(value)
        agree += ok
        print(f"{'OK ' if ok else 'XX '} {cid:60s} expected={value} got={got}")
    else:
        print(f"--  {cid:60s} expected_state={state} rule_output={got}")
print("value cases agreeing:", agree, "/", sum(1 for r in results if r[1] == "value"))
```

</details>

## Primary-statement extension census

Method:

1. Take statement roles from each bundle's `MetaLinks.json` where `groupType == "statement"`.
2. In those roles, take non-abstract presentation-arc targets as line items.
3. Classify line items by namespace: US-GAAP, DEI and SRT are standard; everything else is an
   extension.

Output:

```text
0000019617-24-000453 (JPM)       statement_roles=7 line_items=145 extension=20 share=14%
0000021344-24-000044 (KO)        statement_roles=5 line_items=97  extension=5  share=5%
0000104169-24-000056 (WMT)       statement_roles=6 line_items=110 extension=2  share=2%
0001065088-23-000006 (eBay FY22) statement_roles=6 line_items=129 extension=14 share=11%
0001065088-24-000036 (eBay FY23) statement_roles=6 line_items=131 extension=15 share=11%
0001065088-24-000094 (eBay 10-K/A) no statements
```

An earlier exploratory variant of this census gave 15% for JPM and 12% for eBay FY2023. It was not
retained, and its exact line-item definition differed. The retained method above is authoritative
for this assessment.

<details><summary><code>statement_extension_census.py</code></summary>

```python
"""Ad hoc census: extension share of non-abstract line items on SEC-classified primary statements."""
import json
from pathlib import Path

from sqlalchemy import create_engine, text

from edgar.xbrl.extraction_receipt import load_bundle_ref

STANDARD = ("http://fasb.org/us-gaap/", "http://xbrl.sec.gov/dei/", "http://fasb.org/srt/")
root = Path("var").resolve()
e = create_engine("postgresql+psycopg://edgar:edgar@localhost:5432/edgar")
with e.connect() as c:
    c.execute(text("SET TRANSACTION READ ONLY"))
    reports = c.execute(text("""
        select g.accession, r.id from source.xbrl_report r join source.filing g on g.id = r.filing_id
        order by g.accession""")).all()
    for accession, report_id in reports:
        cik = accession.split("-")[0]
        bundle_dirs = sorted((root / "bundles" / cik / accession).glob("*"))
        bundle = load_bundle_ref(data_root=root, bundle_dir=bundle_dirs[-1]).bundle
        art = next((a for a in bundle.artifacts if a.logical_path.endswith("MetaLinks.json")), None)
        if art is None:
            print(accession, "no MetaLinks.json")
            continue
        sha = art.content.sha256
        meta = json.loads((root / "objects" / "sha256" / sha[:2] / sha).read_bytes())
        roles = {
            rep["role"]
            for inst in meta["instance"].values()
            for rep in inst["report"].values()
            if rep.get("groupType") == "statement"
        }
        rows = c.execute(text("""
            select distinct k.namespace_uri, k.local_name
            from source.relationship rel
            join source.concept k on k.id = rel.target_concept_id
            join source.concept_declaration d on d.report_id = rel.report_id and d.concept_id = k.id
            where rel.report_id = :r and rel.network_type = 'presentation'
              and rel.link_role_uri = any(:roles) and coalesce(d.abstract, false) = false
        """), {"r": report_id, "roles": list(roles)}).all()
        ext = sum(1 for ns, _ in rows if not ns.startswith(STANDARD))
        share = f"{ext / len(rows):.0%}" if rows else "n/a"
        print(f"{accession} statement_roles={len(roles)} line_items={len(rows)} extension={ext} share={share}")
```

</details>

## LOC inventory script

The output is the table in [03](03-capability-inventory.md). The only unassigned file is the empty
`tests/helpers/__init__.py`.

<details><summary><code>loc_inventory.py</code></summary>

```python
"""Assign tracked Python files to capabilities; count physical and non-blank/non-comment lines."""
import re, subprocess, collections
files = subprocess.run(["git","ls-files","*.py"], capture_output=True, text=True, check=True).stdout.split()
CAPS = [
 ("A SEC access & acquisition", [r"src/edgar/sec/", r"src/edgar/ingestion/acquisition\.py", r"src/edgar/ingestion/report_input\.py",
   r"tests/unit/test_acquisition_hardening", r"tests/unit/test_ssrf", r"tests/unit/test_report_input", r"tests/unit/test_accession_reconcile", r"tests/contract/test_live_sec_smoke", r"tests/unit/test_payload_budget", r"tests/unit/test_identifiers"]),
 ("B DTS closure capture & offline replay", [r"src/edgar/xbrl/closure\.py", r"src/edgar/xbrl/arelle_env\.py", r"src/edgar/xbrl/network_guard\.py", r"src/edgar/xbrl/replay", r"src/edgar/domain/uri\.py", r"src/edgar/xbrl/uri\.py",
   r"tests/contract/test_arelle_closure_replay", r"tests/unit/test_closure_safeguards", r"tests/helpers/arelle_cache_fetcher", r"tests/unit/test_payload_and_uri", r"tests/unit/test_residue_deny_list"]),
 ("C Immutable storage & bundle model", [r"src/edgar/storage/", r"src/edgar/domain/(bundle|validation|decode|payload|identifiers|report_key|concept_id|issues|__init__)\.py", r"src/edgar/ingestion/payload\.py",
   r"tests/unit/test_object_store_and_bundles", r"tests/unit/test_bundle_integrity", r"tests/unit/test_bundle_fingerprint"]),
 ("D XBRL extraction (Arelle adapter)", [r"src/edgar/xbrl/(extract|locators|resolved_text|config|diagnostics|target_identity|worker)\.py", r"src/edgar/xbrl/__init__\.py",
   r"tests/contract/test_arelle_report_extraction", r"tests/unit/test_invalid_base_set_qname", r"tests/unit/test_semantic_", r"tests/unit/test_resolved_text", r"tests/unit/test_report_input_target", r"tests/helpers/(rich_xbrl|ixds_xbrl|invalid_transform|linkbase_qnames|xbrl_bundles)", r"tests/unit/test_source_datetime"]),
 ("E Extraction IR & wire codecs", [r"src/edgar/xbrl/(records|source_records|source_wire|_source_build)\.py", r"tests/unit/test_semantic_records", r"tests/unit/test_source_extract_adapt"]),
 ("F Extraction verification, receipts & orchestration", [r"src/edgar/xbrl/(upstream_inventory|integrity|extraction_receipt|report_set|semantic|source_extract)\.py", r"src/edgar/provenance\.py", r"src/edgar/ingestion/source_extract\.py", r"src/edgar/ingestion/__init__\.py",
   r"tests/unit/test_upstream_inventory", r"tests/unit/test_xbrl_integrity", r"tests/unit/test_extraction_receipt", r"tests/helpers/extraction_receipt", r"tests/unit/test_report_set", r"tests/unit/test_source_extract_orchestration", r"tests/unit/test_cli_extract_json", r"tests/unit/test_source_identity", r"tests/integration/test_source_extract\.py", r"tests/contract/test_frozen_slice0"]),
 ("G Source persistence (PostgreSQL + migrations)", [r"src/edgar/db/(source|source_schema|source_persist|schema|engine|check|__init__)\.py", r"src/edgar/ingestion/catalog\.py", r"migrations/",
   r"tests/integration/test_source_persist", r"tests/integration/test_source_catalog", r"tests/integration/test_v2_clean_head", r"tests/integration/test_migration_", r"tests/helpers/(migration_0005|preflight_0005|database|network_identity)", r"tests/integration/test_network_identity", r"tests/unit/test_catalog_service", r"tests/unit/test_v2_migration_freeze", r"tests/unit/test_database_guard"]),
 ("H Document structure & sections", [r"src/edgar/parsing/", r"src/edgar/xbrl/source_documents\.py", r"tests/unit/test_document_", r"tests/unit/test_source_documents", r"tests/helpers/document_fixtures"]),
 ("I Metric registry & mapping ledger", [r"src/edgar/registry/", r"src/edgar/db/registry", r"tests/unit/registry/", r"tests/integration/test_mapping_", r"tests/helpers/mapping_source_fixture", r"tests/unit/test_cli_metrics_mappings"]),
 ("J M0 benchmark validation", [r"tests/helpers/financial_cases", r"tests/unit/test_financial_benchmark"]),
 ("K Corpus acceptance", [r"src/edgar/corpus_", r"scripts/phase1_corpus_acceptance", r"tests/unit/test_corpus_manifest", r"tests/integration/test_source_corpus_acceptance", r"tests/unit/test_document_inventory_digest"]),
 ("L CLI & settings", [r"src/edgar/cli\.py", r"src/edgar/config\.py", r"src/edgar/__init__\.py"]),
]
def count(path):
    phys = code = 0
    for line in open(path, encoding="utf-8"):
        phys += 1
        s = line.strip()
        if s and not s.startswith("#"):
            code += 1
    return phys, code
agg = collections.defaultdict(lambda: [0,0,0,0])
unassigned = []
for f in files:
    if f.startswith("var/"): continue
    cap = next((name for name, pats in CAPS if any(re.search(p, f) for p in pats)), None)
    if cap is None:
        unassigned.append(f); continue
    p, c = count(f)
    is_test = f.startswith("tests/")
    agg[cap][2 if is_test else 0] += p
    agg[cap][3 if is_test else 1] += c
tot = [0,0,0,0]
print(f"{'capability':52s} {'prod_phys':>9s} {'prod_code':>9s} {'test_phys':>9s} {'test_code':>9s}")
for name, _ in CAPS:
    v = agg[name]; tot = [a+b for a,b in zip(tot,v)]
    print(f"{name:52s} {v[0]:9d} {v[1]:9d} {v[2]:9d} {v[3]:9d}")
print(f"{'TOTAL':52s} {tot[0]:9d} {tot[1]:9d} {tot[2]:9d} {tot[3]:9d}")
print("unassigned:", unassigned)
```

</details>

## Limitations

- **The corpus is six filings.** Market-scale statements are arithmetic on measured per-filing costs
  or explicit hypotheses, and are marked as such.
- **LOC estimates are approximate.** Capability assignment is by path, and deletion and replacement
  estimates are ranges from the per-file inventory.
- **Two judgements are the assessor's own.** The parent-NI case rests on the FASB definition, and
  the Walmart cash case on the XBRL duplicate-fact consistency rule. Both are argued in
  [05](05-mapping-strategy.md). The benchmark authors reached a different, more conservative
  conclusion.
- **Not measured:**
  - taxonomy-package parity;
  - DuckDB storage and throughput;
  - `MetaLinks.json` availability before Inline XBRL;
  - `companyfacts` agreement.

  All are scheduled for P2 in [08](08-migration-plan-assessment.md).
