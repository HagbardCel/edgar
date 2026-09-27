# P0 — Freeze and fix

**Duration:** about one week. **Depends on:** nothing. **Unlocks:** P1 (after
P0.1) and faster extraction (after P0.2).

## Goal

1. The project has an accepted ADR that authorizes the recommended sequence
   (rules over per-report review; measured quality; P1 before more M1A/M2
   machinery).
2. Offline 10-K extraction of Walmart (`0000104169-24-000056`) finishes in
   **≤ 25 seconds** on the same machine class used in
   [A](../A-evidence-and-method.md) (it was 93–94 s).
3. Facts, contexts, units, and relationships on the fixture corpus are
   unchanged. Declaration **and** filtered label/reference *counts* may
   fall; those changes are reviewed.
4. `make check` is green.

## Preconditions

- Working tree based on `main`.
- Local bundles for the six corpus accessions under `var/` (see
  `fixtures/corpus.toml`).
- `make check` is already green before you start. If it is not, fix that first.

## Out of scope

- Mapping rules, selection, export (P1).
- DuckDB, taxonomy packages, ledger deletion (P3).
- Remaining M1A-4 inspector, M1A-5 official-package packets, and all of M2.
  Do not implement them.

## Work items

### P0.1 — Adopt the direction (blocks P1+)

This is a documentation and governance change. A senior reviewer must accept
the ADR. You may draft it.

**Read first:** [07](../07-lean-architecture-tradeoffs.md) §3 (T2, T3, T7, T13,
T14), [08](../08-migration-plan-assessment.md),
`docs/adr/0012-adopt-bounded-financial-architecture.md`,
`docs/adr/0013-publication-critical-taxonomy-evidence.md`, `AGENTS.md`.

**Write:** `docs/adr/0014-adopt-lean-mapping-sequence.md` (next unused number
if 0014 is taken).

The ADR must state, in this order:

1. **Assurance model.** Quality is measured per policy (gold set, identities,
   oracle) rather than attested per report and occurrence. This is 07 T3.
2. **Mapping authority.** Git-reviewed **decision records** replace the
   PostgreSQL ledger as the destination of new decisions. The existing
   ledger stays readable until P3 deletes it. No new `propose`/`accept`
   features.
3. **Standard-concept continuity.** A decision keyed on namespace *family* +
   local name (`us-gaap:Assets`) applies to every US-GAAP release where that
   concept exists, minus any `exclude_qnames`. Family membership uses the
   shared prefix table (2009 `xbrl.us` **and** modern `fasb.org` /
   `xbrl.sec.gov`). Exact Clark QNames remain the *source* identity. This
   unblocks multi-year data without M5.
4. **Selection primitives.** EDGAR required context + XBRL OIM duplicate-fact
   consistency (interval overlap, not rounding-to-coarser). Affirmative
   definition evidence for standard concepts may come from `MetaLinks.json`
   or pinned taxonomy packages. Accepted decisions require at least one
   evidence pointer.
5. **Paused work.** M1A-4, M1A-5, and M2 as written are not the next
   implementation. P1–P6 in this directory replace that sequence.
6. **What is not decided yet.** Storage (PostgreSQL vs DuckDB) and taxonomy
   packages vs closure capture wait for P2 measurements and a later ADR.

**Then update, only after the ADR is accepted:**

- `AGENTS.md`: current phase becomes “P0 complete / P1 next (ADR 0014)”. Remove
  the sentence that forbids M3-style observation work ahead of M1A/M2. Keep
  every source invariant (bytes, `Decimal`, identifiers, timestamps, no dropped
  extensions).
- `docs/README.md`: point at ADR 0014 and this plan directory. Keep the target
  package as historical, not governing.
- `docs/architecture.md` (the short live-architecture note, not the 32k-word
  package): one paragraph that P1 will add resolve/select on `source.*`.

Do **not** rewrite the architecture package in this item.

**Validation gate P0.1**

```bash
# ADR exists and is linked
test -f docs/adr/0014-adopt-lean-mapping-sequence.md
rg -n "ADR 0014|P1 Walking skeleton" AGENTS.md docs/README.md
make check
```

Expected: `make check` still green (docs-only). P1 work is now authorized.

---

### P0.2 — Fix the quadratic locator scan

**Why.** `src/edgar/xbrl/locators.py` proves `id` / `xml:id` uniqueness with a
full-document XPath per element. On `us-gaap-2023.xsd` (17,221 ids) that is
~82–87 s of a ~94 s Walmart extract. A one-pass `Counter` is ~4 ms.

**Read first:** `src/edgar/xbrl/locators.py`,
`tests/unit/test_semantic_records.py` (`test_locator_prefers_unique_xml_id`,
`test_locator_falls_back_when_id_not_unique`),
`src/edgar/xbrl/extract.py` (how `extraction.locator(...)` is called).

**Change:** `src/edgar/xbrl/locators.py` only, plus tests.

**Algorithm.** Build two `collections.Counter` maps with **one**
`root.iter()` pass: counts of `xml:id` and of unqualified `id`. Uniqueness is
`count == 1`. Preference order stays: unique `xml:id`, else unique `id`, else
expanded path. Locator `scheme` and `value` must be **byte-identical** to
today for every element the existing tests cover.

Cache the counters for the life of one document. Do **not** rebuild them per
`element_locator` call. Practical options (pick one):

- A dict keyed by `id(root)` held on the `_Extraction` object in `extract.py`
  and passed into `element_locator`, or
- A function on `locators.py` such as `id_index(root) -> IdIndex` called once
  per document at the start of extraction, then `element_locator(..., index=)`.

lxml elements are not reliably `weakref`-able. Do not use
`WeakKeyDictionary` on the root.

Do **not** change locator version (`ELEMENT_LOCATOR_VERSION`) if output is
identical. If you cannot keep output identical, stop and ask.

**Tests to add**

- Existing two tests stay, unchanged.
- New test: a document with 200 elements sharing no ids produces the same
  locators as today (unique `id` → `unqualified_id`).
- New test: two elements with the same `id` both fall back to
  `expanded_element_path`.
- Optional micro-benchmark in the test (not CI-failing): 500 calls on a 1k
  element tree finish in well under a second.

**Validation gate P0.2a**

```bash
uv run pytest -q tests/unit/test_semantic_records.py
uv run ruff check src/edgar/xbrl/locators.py src/edgar/xbrl/extract.py
```

Then time Walmart again (same helper idea as [A](../A-evidence-and-method.md)):

```bash
# record wall time of run_offline_extract on
# bundles/0000104169/0000104169-24-000056/<opaque>
```

Expected: locators unchanged; extract time already much lower. The ≤ 25 s
phase gate may still fail until P0.3, because unused declarations still get
located. If Walmart is already ≤ 25 s, P0.3 is still required (grain).

---

### P0.3 — Stop persisting unused standard-taxonomy declarations

**Why.** Each full report stores ~18.5k `concept_declaration` rows. Facts use
376–871 concepts. Locating the unused US-GAAP declarations is most of the
remaining extract time, and ~47% of database bytes.

**Read first:** `src/edgar/xbrl/extract.py` function `_concept_declarations`
(around line 567), `extract_report_extraction` (around 1892),
`src/edgar/xbrl/source_records.py` (`EXTRACTOR_VERSION`),
`src/edgar/corpus_acceptance.py` (declaration counts).

**First land a shared family classifier**
(`src/edgar/xbrl/taxonomy_family.py`, name is fine) so P0.3 does not treat
2009 `xbrl.us` concepts as issuer extensions:

```text
taxonomy_family(namespace_uri) -> "us-gaap" | "dei" | "srt" | "issuer"

us-gaap prefixes:  http://xbrl.us/us-gaap/     http://fasb.org/us-gaap/
dei prefixes:      http://xbrl.us/dei/         http://xbrl.sec.gov/dei/
srt prefixes:      http://fasb.org/srt/
```

P1 expansion, required-context lookup, MetaLinks joins, and P2 reporting
**must import this same function**. Do not copy prefix strings.

Unit tests (URI strings only; no full taxonomy zip):

- `http://xbrl.us/us-gaap/2009-01-31` → `us-gaap`
- `http://fasb.org/us-gaap/2023` → `us-gaap`
- `http://xbrl.us/dei/2009-01-31` → `dei`
- `http://xbrl.sec.gov/dei/2023` → `dei`
- `http://ebay.com/20131231` → `issuer`

Do **not** use a fixed-point keep-set (declaration kept because a resource
is kept, resource kept because the declaration is in the keep-set). That
can retain most of the 17k unused US-GAAP concepts.

Define the grain in one pass, no fixed point:

```text
base_concepts =
    fact concepts
  ∪ relationship endpoints
  ∪ all issuer-extension declarations
    (taxonomy_family(namespace) == "issuer")

persisted labels/references =
    resources whose subject ∈ base_concepts

persisted declarations =
    base_concepts
```

A filing-specific resource that genuinely needs another standard concept
must be added through an **explicit later resource policy**, not by
walking every collected label. Do not start from “all labels we parsed”
and close under subjects.

Do not change fact, context, unit, or relationship extraction.

**Bump** `EXTRACTOR_VERSION` from `source-extract-v5` to `source-extract-v6`.
Any output-shape change requires this (standing rule 9).

**Expected count change.** Declarations per full 10-K should drop from ~18.5k
to the size of `base_concepts` (fact concepts ∪ relationship endpoints ∪
issuer extensions), typically hundreds to low thousands depending on
relationship-endpoint volume. Facts and relationships must match the
previous extract exactly (same counts, same source locators, same values).
Label/reference counts follow `base_concepts`, not the full taxonomy.

**Tests**

- Unit: `taxonomy_family` on the 2009 / 2011 / modern URIs listed above.
- Unit: a small in-memory or rich-xbrl fixture where a standard concept is
  declared but unused is omitted; a used standard concept is kept; an unused
  extension is kept; a 2009 `xbrl.us` unused standard concept is **not**
  kept as an issuer extension.
- Contract / corpus: review changed declaration counts. **Do not** silently
  refresh goldens. The PR description lists old vs new counts per accession.

**Validation gate P0.3**

```bash
uv run pytest -q -m "not network" tests/contract/test_arelle_report_extraction.py
uv run pytest -q -m "not network" tests/unit/test_source_extract_adapt.py
# after extract of the six corpus filings:
#   facts, contexts, units, relationships unchanged vs previous persist
#   concept_declaration and unused-standard label/reference counts fall
#   concept_declaration count per full report << 18500
```

If any fact, context, unit, or relationship locator or value changed,
revert and fix. The allowed extract delta is **declaration cardinality
and filtered label/reference counts**, not facts/contexts/units/relationships.

---

### P0.4 — Delete unused aliases (not live types)

**Why.** Cheap hygiene. Do this after P0.2/P0.3 so the diff stays readable.

**Delete only these aliases and unused exports.** Confirm with
`rg` that nothing in `src/` or `tests/` needs the old name.

| Symbol | File | Action |
|---|---|---|
| `SecClient` | `src/edgar/sec/client.py`, `sec/__init__.py` | Delete the alias. Keep `ControlledFetcher`. |
| `CatalogConflict` | `src/edgar/ingestion/catalog.py` | Delete the alias. Callers already use `SourceCatalogConflict`. |
| `SemanticWorkerError` | `src/edgar/xbrl/semantic.py` | Delete the alias. Keep `SourceExtractWorkerError`. |
| `concept_id_str` | `src/edgar/domain/concept_id.py` | Delete if `rg` shows no callers. Keep `concept_id`. |
| `resolve_document_id` | `src/edgar/db/source.py` | Delete if no callers (it is in `__all__` only). |
| `AcquisitionObservation` | `src/edgar/domain/bundle.py`, `domain/__init__.py` | Delete the unused class and export. |

**Do not delete** (they are live):

- `WebCacheLike` — protocol used by `arelle_env.py`.
- `LocatorProvenance` / `occurrence_provenance` — defined and used in
  `locators.py`. If `rg` shows no callers *outside* that file, you may delete
  them **only** together with `occurrence_provenance` and its tests. Prefer
  leaving them if unsure.
- `entry_document_id` — schema column. Dropping it needs a new Alembic
  revision. **Defer to P3** unless you are already writing a migration for
  another reason. Continue writing `None`.

**Validation gate P0.4**

```bash
rg -n "SecClient|CatalogConflict|SemanticWorkerError|concept_id_str|resolve_document_id|AcquisitionObservation" src tests
# expect no matches (except this assessment directory)
make check
```

---

### P0.5 — Pause leftover M1A/M2 in agent instructions

If P0.1 is accepted, this is already done. If you did P0.2–P0.4 first, now
align `AGENTS.md` so the next authorized work is P1, not M1A-4.

Do not delete the architecture package. Leave it as historical.

**Validation gate P0.5**

```bash
rg -n "next: M1A|Do not implement M2/M3/M4" AGENTS.md
# those lines must be gone or rewritten to point at P1
```

## Phase exit gate

```bash
make check
```

Expected: ruff, format, pyright, `edgar registry validate`, 398 offline tests,
108 database tests — all pass.

Plus a recorded timing:

```text
Walmart 0000104169-24-000056 offline extract (no DB write): ≤ 25 s
Fact count: unchanged vs pre-P0 persist
Relationship count: unchanged
EXTRACTOR_VERSION: source-extract-v6
```

Put the timing command and output in the PR.

## Pitfalls

- **Changing locator output.** If a test or persist golden wants a path where
  it previously wanted an `id`, the index is wrong (you treated a duplicate
  as unique, or the reverse).
- **Filtering declarations before relationships exist.** `base_concepts` must
  include relationship endpoints or presentation trees lose declaration
  metadata.
- **Dropping extension declarations.** Issuer-extension declarations are
  always in `base_concepts`, even when unused by facts.
- **Editing migration `0005`.** Never. Grain changes are extractor-only in
  P0.
- **Starting P1 before the ADR.** Project rules will fight you, and reviewers
  will reject the PR.

## Stop and ask if

- Walmart extract is still > 25 s after P0.2 and P0.3 (profile before adding
  more machinery).
- Fact or relationship counts move.
- You think `entry_document_id` must be dropped to hit the gate (it must not).
