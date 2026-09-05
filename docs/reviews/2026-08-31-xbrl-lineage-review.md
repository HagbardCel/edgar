# XBRL-fact → canonical-metric lineage & leanness review

**Date:** 2026-08-31
**Goal of review:** Establish whether the repository provides a clear,
correct, and transparently-lineage-traceable mapping of SEC Edgar XBRL facts
to canonical metrics, suitable as a trustworthy database for downstream
analytics — and recommend improvements, including fundamental refactors and
feature removals, to make the project as lean and maintainable as possible.
No sequenced implementation roadmap; analysis and recommendations only.

**Relation to prior work:** This review is complementary to
`docs/reviews/2026-08-22-project-assessment.md`, which catalogued dead code,
dedup clusters, and incremental cleanup (pydantic wire codecs, alembic
autogenerate). That assessment was deliberately conservative — it stayed
inside Phase 2C scope and explicitly avoided structural changes to the XBRL
adapter boundary. The owner has since asked for fundamental refactors and
feature removals. This document therefore focuses on the structural proposals
the prior review deferred, and on the lineage/analytics goal itself. Dead-code
and dedup tables are *not* repeated here; see §1 of the prior assessment.

---

## 1. The lineage question (the core goal)

### 1.1 What "transparent lineage" means here

For a canonical metric value to be trustworthy, a consumer must be able to
trace:

```
canonical_metric  →  mapping_assertion  →  source.concept  →  source.fact
                     (reviewed decision)                      ↓
                                                   source.xbrl_report
                                                     ↓
                                                   source.filing  →  source.document
                                                                       ↓
                                                                  FilingBundle bytes (SHA-256)
```

### 1.2 Assessment: lineage is audit-complete, not analytics-materialized

**What works (keep):**

- **Fact→bytes provenance is complete and queryable.** Every `source.fact`
  carries `report_id`, `source_document_id`, and a JSONB `source_locator`
  (`{document_uri, scheme, value}`). The chain
  `fact → xbrl_report → filing → document → bundle artifact → sha256` is
  fully joinable. `report_key` (SHA-256 of canonical `report_input`) makes
  re-extraction deterministic and diffable. This is genuinely strong.
- **Mapping decisions are hash-pinned and append-only.** `definition_hash`
  over the canonical metric contract (incl. `key`, excl. `name`) means "the
  metric this candidate was reviewed against" is machine-checkable forever.
  `target_definition_hash` is copied into every successor and never rewritten;
  accept fails closed on hash drift (`registry/service.py:302-314`). The
  `UNIQUE(supersedes_id)` + claim-field copy invariant prevents silent
  re-meaning. This is exactly what "transparent" should mean.
- **Concept-level mapping is the right granularity for a registry.** Mapping
  global XBRL concepts (e.g. `us-gaap:Revenues`) to canonical metrics — rather
  than mapping individual facts — keeps the ledger compact and reviewable.

**The gap (the bridge the user's goal still needs):**

- **No persisted link from a metric to the facts it covers.** Affected facts
  are computed *live* via `contains()` over `source.filing.report_period_end`
  (`db/registry.py:226-272`). This is elegant — it can never go stale relative
  to a re-extraction — but it means every analytics consumer re-derives the
  join at query time. There is no point-in-time snapshot of "which facts
  constituted `net_income` for issuer X, period Y, under the current accepted
  mapping." For *audit* that's fine; for *downstream analytics* it is the
  missing piece.
- **Dimensional facts are not distinguished by the mapping.** A concept like
  `us-gaap:Revenue` can appear with segment/product dimensions. The mapping
  links the *concept*; the dimensions live on `source.context_dimension`. An
  analytics consumer must still filter/group dimensions themselves — there is
  no canonical "revenue by segment" observation.
- **No observation-selection policy.** Phase 2C deliberately defers this. But
  the user's stated end ("perform downstream analytics") implies someone must
  eventually decide: for a duration metric, do we sum all facts in the period?
  Take the latest instant? Weight by calculation relationships? That decision
  is not yet made, and it is the substantive semantic step between "mapped
  facts" and "analytics-ready values."

**Verdict:** the foundation is trustworthy (you can *audit* any metric back to
bytes), but it is not yet *analytics-materialized*. The single highest-value
addition is a materialized observation layer (§4), not more foundation cleanup.

---

## 2. Fundamental refactors (structural, beyond the prior review)

The prior review's leanness findings were real but incremental (~3,300-3,800
LOC via dead code + dedup + pydantic codecs). The proposals below target
*structural* overhead the prior review explicitly did not touch. They are
riskier but are where the largest LOC reductions live.

### 2.1 Reconsider the Arelle worker subprocess boundary

**Status quo:** Arelle runs in an isolated subprocess (`xbrl/worker.py` 676 LOC)
with its own XDG config (`arelle_env.py` 251), AF_INET/AF_INET6 socket denial
`network_guard.py` 148), and a hand-rolled lossless JSON wire codec
(`source_wire.py` 689). Total: ~1,764 LOC of isolation/IPC machinery.

**The case for collapse:** Arelle's own `Cntlr` supports
`disable_persistent_config=True` and offline mode. The project is Phase 2B
offline-only: the FilingBundle pre-resolves the DTS closure at *acquisition*
time (`ingestion/acquisition.py:501` calls `run_online_closure`), so by the
time extraction runs, Arelle is fed local bytes bound to canonical URIs. The
subprocess is therefore defense-in-depth against a *pinned, offline,
locally-fed* library. The residual risk it guards against — "Arelle attempts
an outbound call during a malformed load" — is mitigatable by a
process-level network allowlist or a network namespace around the *whole* CLI,
without ~1,764 LOC of bespoke IPC.

**If in-process is acceptable:** `worker.py`, `source_wire.py`,
`network_guard.py`, and most of `arelle_env.py` collapse into a ~150-250 LOC
adapter. `extract.py` emits records directly to the persistence layer; the
JSON IPC boundary and its codec disappear. This is the single largest
structural reduction available.

**Fair counter-argument:** the subprocess is a hard isolation boundary that
survives Arelle version upgrades and guarantees no Arelle object escapes. If
the team values that invariant above LOC, keep it — but make it an explicit,
documented tradeoff with a named threat model, not accidental complexity that
reads as over-engineering. Right now the rationale lives in ADR 0009 prose
but not in a live threat analysis.

**Recommendation:** spike an in-process extraction path against one filing.
If Arelle's offline mode is genuinely quiescent (no socket attempts on a
well-formed bundle), collapse the boundary. If it is not, document the threat
model and keep the machinery — but then pydantic-v2-encode the wire payload
(prior review §5.1) so the 689-LOC codec shrinks to ~150.

### 2.2 Evaluate Arelle's native export (justify or replace `extract.py`)

`xbrl/extract.py` is 1,910 LOC that walks Arelle's `ModelXbrl` and emits
records. Arelle ships its own structured-export machinery (JSON DTS export,
the inline-viewer plugin, SaveExtractDTS). If Arelle's export preserved the
project's fidelity bar, `extract.py` could shrink to a thin mapper from
Arelle's export format to `source.*` rows.

**Why this is high-risk:** the project's fidelity contract is stricter than
Arelle's export surface. Specifically required fields that are *not* standard
Arelle export outputs:

- `continuation_provenance` (inline XBRL continuation chain locators)
- exact element locators (`{scheme, value}` with `xml_id`/`unqualified_id`/
  `expanded_element_path` schemes)
- `value_status` four-state (`valid|nil|invalid|unresolved`) with nil/invalid
  row preservation
- typed-member C14N XML + sha256 (`source.context_dimension.typed_member`)
- `decimals`/`precision` as raw TEXT (INF-preserving), plus ixbrl `scale`/`sign`
- `format_namespace_uri`/`format_local_name`/`escape` (ixbrl transform qnames)

**Recommendation:** run a bounded spike — export one filing via Arelle's JSON
plugin and diff the field set against `source.fact`/`source.context`. Expect
a split verdict: Arelle's concept/context/unit/*fact-value* enumeration is
reusable; the locator/continuation/nil/ixbrl-format machinery is not and
justifies a custom extractor. *That conclusion is itself valuable* — it
converts "extract.py is obviously overbuilt" into "extract.py is justified by
a measured fidelity gap," which is the right posture for a 1,910-LOC module.

### 2.3 Remove or defer document & section parsing

`src/edgar/parsing/` (~2,233 LOC), `source.document_block`,
`source.filing_section`, the `documents sections` CLI command, and associated
tests implement HTML document-block extraction and section-boundary detection.
This is Phase 4+ text intelligence, not XBRL fact mapping.

**The prior review kept parsing** and only proposed internal dedup within it
(declarative section table, DP parameterization). Given the owner's explicit
willingness to remove low-priority features for leanness, I'd go further:
**defer the entire document-parsing subsystem.** It is structurally separable
(separate package, separate tables, separate CLI group, separate tests) and
can be restored from git history when text intelligence becomes a real
priority.

**Impact:** ~2,233 LOC + tests removed; the extraction flow simplifies (no
`extract_documents_for_filing` branch in `xbrl/source_extract.py`); the
`documents` CLI group and two tables drop. The XBRL lineage goal is
unaffected.

**Caveat:** confirm no XBRL-side code imports `parsing/` before removal
(`xbrl/source_documents.py` is the boundary — verify it is only called from
the document path, not the XBRL path).

### 2.4 Collapse the dual XBRL record layer

The prior review identified this (its P3, ~500 LOC by deleting
`_source_build.py`). I agree and would go one step further.

**Current shape:** `records.py` (1,273 LOC) defines adapter-boundary records
using canonical URIs (`SourceLocator` with `document_uri`). `source_records.py`
(489 LOC) defines source-layer DTOs using FilingBundle `logical_path`
(`ElementLocator` with no URI). `_source_build.py` (519 LOC) translates
between the two via `uri_to_logical_path_map`. `source_wire.py` (689 LOC) is a
*second* codec layer for the `source_records` types. So the translation stack
is: Arelle → `records.py` types → `_source_build.py` → `source_records.py`
types → `source_wire.py` → JSON → parent → `db/source.py`. That is ~2,970 LOC
of translation between Arelle and the DB.

**The only material difference between the two record layers** is canonical
URI vs logical path — a mechanical mapping the build step already performs.
The 13 `Literal` type aliases and most field shapes are shared
(`source_records.py:15-27` imports them from `records.py`).

**Recommendation:** unify into one record module. Have `extract.py` emit the
unified record with logical-path provenance directly (it has the FilingBundle
bindings available). Delete `records.py`'s separate `SourceLocator`/codec
layer and `_source_build.py`'s ten `_build_*` mappers. Replace both codecs
with pydantic v2 models (prior review §5.1) so `to_dict`/`from_dict` is
generated, not hand-written. Combined saving: ~2,000-2,500 LOC, behind a
`SOURCE_RECORDS_SCHEMA_VERSION` bump with byte-exactness round-trip tests.

---

## 3. Smaller structural recommendations

### 3.1 Split `RegistryService` (752 LOC)

One class owns sync, propose/accept/reject, inspection/list/export. The
concerns are separable: `RegistrySyncService` (YAML→mirror), `MappingLedger`
(propose/accept/reject + conflict detection), `MappingInspection` (list/show/
export/affected-facts). Low-risk, improves test focus and readability. The
prior review did not flag this; at 752 LOC it is the largest single
non-extraction service.

### 3.2 Archive `semantic-registry/` out of the tree

The prior review noted it is "correctly archived and unloaded." It is still
*in* the working tree, which is a tax on every new reader's mental model.
Move it to a git tag or `archive/` and delete the directory. Zero production
impact (grep-confirmed no `src/` imports).

### 3.3 `service.py:441-454` affected-facts short-circuit

`export_mappings` computes the full affected-fact list per assertion then
slices to zero when facts aren't requested. Add a skip flag. Prior review §3.2
item 5; include for completeness.

---

## 4. The analytics bridge (the next real priority)

The user's end goal is "perform downstream analytics." The foundation gets
facts into `source.*` with full provenance; the mapping ledger links concepts
to metrics. But nothing *materializes* a metric value. Every consumer
re-joins `source.fact` to `mapping_assertion` via `contains()` at query time.

**Recommendation:** a materialized `metric_observation` layer should be the
next phase priority (Phase 2D), not more foundation cleanup.

**Option A — PostgreSQL materialized view (no new dependency):**
A `metric_observation` MV over `source.fact ⋈ mapping_assertion` for
accepted `exact` mappings, refreshed per extraction cycle. Gives consumers a
queryable table of (metric, issuer, period, value, fact_ids, mapping_id)
without re-deriving joins. Point-in-time snapshots via `WITH MATERIALIZED`
or a versioned snapshot table. Zero new dependencies; uses the existing
schema.

**Option B — DuckDB as an external analytics engine:**
DuckDB can attach the PostgreSQL `source.*` schema (via the `postgres`
extension) or read parquet exports, and run fast columnar OLAP without
intruding on the foundation. This is the right shape for *research* analytics
(ad-hoc cross-issuer panels, historical scans) where a materialized view is
too rigid. It does not touch `source.*` writes; it is a read-side add-on.

**Recommended sequencing:** Option A first (it lives in the existing schema
and gives the ledger a durable, queryable output). Add DuckDB later when the
research layer needs columnar scans over historical facts. Neither requires
touching the immutable foundation.

**Observation selection policy (the hard semantic step):** materializing
observations forces a decision the ledger currently avoids: for a duration
metric, do we sum facts in the period? Take the latest instant? Respect
calculation relationships for sign? This is a genuine semantic phase, not a
refactor — and it is where "trustworthy database" becomes "analytics-ready
database."

---

## 5. Third-party libraries (delta from prior review)

The prior review's library findings are endorsed and not repeated: adopt
pydantic v2 for wire codecs, adopt alembic autogenerate, reject tenacity/
cachetools/ORM/session frameworks. Two additions:

- **DuckDB** — the one new dependency worth considering, *for the analytics
  layer only* (§4 Option B). Not a foundation dependency. It is the leanest
  path to fast cross-issuer analytics without a warehouse.
- **Do not switch from Arelle.** python-xbrl and alternatives are strictly
  less capable (no calculation/definition linkbases, no typed-dimension C14N).
  Arelle is the reference implementation; the project's choice to pin it
  (`arelle-release==2.43.1`) is correct. The leverage opportunity is *deeper*
  use of Arelle's own export (§2.2), not replacement.

No other new dependencies are warranted for the foundation.

---

## 6. Risk/impact summary

| Proposal | Risk | Est. LOC saved/added | Prior review? |
| --- | --- | --- | --- |
| **2.1** In-process Arelle (collapse subprocess + IPC) | Medium-high | ~1,400-1,764 | **New** (bolder) |
| **2.2** Arelle native export spike | High | 0-1,500 (spike-gated) | **New** |
| **2.3** Remove document & section parsing | Low | ~2,233 + tests | **New** (prior kept it) |
| **2.4** Collapse dual record layer + pydantic codecs | Medium | ~2,000-2,500 | Partial (prior P2/P3) |
| **3.1** Split `RegistryService` | Low | ~0 (readability) | **New** |
| **3.2** Archive `semantic-registry/` | Low | ~0 (tree tax) | Prior noted |
| **4** Materialized observation layer (Phase 2D) | Medium | +~300-500 new | **New** (prior stayed 2C) |
| Prior P0 | Low | ~1,200-1,400 | Endorsed |
| Prior P1 dedup | Low-med | ~950-1,100 | Endorsed |
| Prior P2 pydantic wire | Medium | ~600-800 | Endorsed (fold into 2.4) |

**Bolder-than-prior total (2.1 + 2.3 + 2.4 + split): ~5,600-6,500 LOC removed,
~15-20% of `src/`.** The prior review's incremental track removes a further
~3,000-3,800. The two tracks are largely non-overlapping and can combine.

---

## 7. What to preserve (do not break)

These are the load-bearing invariants. None of the proposals above touch them;

the refactors are all in the *adapter translation* and *feature scope* layers.

- Immutable FilingBundle + SHA-256 content addressing (`storage/objects.py`,
  `domain/bundle.py`)
- `Decimal`/`NUMERIC` fidelity; nil/invalid fact preservation (`db/source.py`,
  `xbrl/extract.py:1136-1147`)
- Append-only `mapping_assertion` ledger with hash-pinning and no-branching
  (`registry/service.py`, `db/registry_schema.py`)
- Git-authoritative `metrics.yml` + DB mirror authority model
- The provenance columns: `source_document_id`, `source_locator`,
  `report_key`, `extractor_version`, `arelle_version`, `extracted_at`
- Fail-closed quality posture (unrecognized diagnostics block "complete")

---

## 8. Bottom line

The repository is an unusually faithful provenance platform. Its weakness for
the stated goal is not incorrectness — it is that it stops one phase too early:
facts are mapped at the concept level but not materialized at the metric
level, so "downstream analytics" still requires hand-joining per query. The
highest-value next step is the observation layer (§4), not more cleanup.

For leanness, the prior review's incremental track is correct but cautious.
The bolder structural moves — collapsing the Arelle subprocess/IPC stack,
removing document parsing, and unifying the dual record layer — remove
roughly as much code again as the entire incremental track, and they target
the complexity that is hardest to reason about (the adapter translation
boundary). They deserve the owner's "fundamental refactor" appetite.
