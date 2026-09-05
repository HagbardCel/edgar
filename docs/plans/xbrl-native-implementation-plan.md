# XBRL-Native Semantic Architecture — Implementation Plan

**Status:** proposed. Subject to the Phase 2C0 spike gate. Does **not** unfreeze
Phase 2D+ on its own. No production schema change in this plan is authorized
until the spike report is reviewed and a cutover decision is recorded in an ADR.

**Target architecture source:**
[`edgar_v2_1_xbrl_native_target_architecture_and_plan.md`](edgar_v2_1_xbrl_native_target_architecture_and_plan.md)
(relocated here from `docs/`).

**Authoritative project invariants:** [`../../AGENTS.md`](../../AGENTS.md),
[`../phase-2-plan.md`](../phase-2-plan.md), [`../normalization.md`](../normalization.md),
[`../data-model.md`](../data-model.md), [`../architecture.md`](../architecture.md).

---

## 0. Executive summary

The v2.1 target architecture proposes a fundamental semantic shift: **stop
building a second accounting ontology** where the FASB/SEC taxonomies already
encode the relevant accounting semantics. Instead of:

```text
source concept → canonical metric (today, Phase 2C)
```

the target is:

```text
source XBRL fact → resolved accounting meaning → analytics metric binding
                 → observation selection → canonical analytical observation
```

This inserts two new layers between the current `source.*` evidence and a
future analytical surface:

1. **`reference.*`** — official FASB/SEC taxonomy semantics, loaded via Arelle,
   regenerable, not curated by us.
2. **`semantic.*` / `analytics.*`** — regenerable SQLMesh models that resolve
   each fact to an accounting meaning, bind it to a thin analytics role, and
   select observations.

The current Phase 2C `registry.mapping_assertion` ledger maps
`source_concept_id → target_metric_key` (direct to an analytics metric). The
target splits that into two durable decisions:

```text
issuer extension QName  →  reference accounting concept   (accounting mapping)
reference concept        →  analytics metric role           (metric binding)
```

This is a **durable ledger schema change** and is the single highest-risk,
highest-effort step in the plan. The v2.1 document itself mandates a small
empirical spike (Phase 2C0) **before** any irreversible redesign, and that gate
is preserved here as Phase 2C0.

Nothing in this plan authorizes Phase 2D+ observation selection, candidate
auto-approval, or `metric_observation` publication until the spike and the 2C2
cutover ADR are both complete.

---

## 1. Current-state assessment (grounded in the actual codebase)

The v2.1 document describes a *target* and makes some assumptions about what
already exists. This section records what actually exists as of the Phase 2C
exit gate, so the plan's deltas are precise.

### 1.1 Already complete and retained

| Concern | State | v2.1 disposition |
|---|---|---|
| Immutable acquisition + FilingBundle | Phase 1A complete | Preserve (v2.1 §22.1) |
| `source.issuer` / `source.filing` / `source.document` | Phase 2B (`0001_source_v2`) | Preserve |
| `source.xbrl_report` (current extraction metadata) | Phase 2B | Preserve; no projection lifecycle |
| `source.concept` (UUID from expanded QName) | Phase 2B | Preserve; QName identity already correct |
| `source.concept_declaration` (report-scoped) | Phase 2B | Preserve |
| `source.concept_label` | Phase 2B | Preserve |
| **`source.concept_reference`** | **Phase 2B — already exists** | v2.1 §5.8 recommends adding it; **it is already present** in `0001_source_v2` with paired provenance. No new source table needed here. |
| `source.context` / `context_dimension` | Phase 2B | Preserve; dims are structured rows, not opaque JSON |
| `source.unit` / `unit_measure` | Phase 2B | Preserve |
| `source.fact` (one row per occurrence) | Phase 2B | Preserve; no economic dedup |
| `source.relationship` (presentation/calculation/definition) | Phase 2B | Preserve |
| `source.document_block` / `filing_section` | Phase 2B | Preserve |
| `source.extraction_issue` | Phase 2B | Preserve |
| `registry.canonical_metric` (YAML mirror) | Phase 2C (`0002_registry`) | **Modify** — see §1.3 |
| `registry.mapping_assertion` (append-only ledger) | Phase 2C (`0002_registry`) | **Migrate** — see §1.3 |
| `registry/metrics.yml` (~20 metric contracts) | Phase 2C | **Refactor** to thin analytics roles |
| Arelle offline extraction worker | Phase 1B/2B | Preserve; remains XBRL/DTS authority |

### 1.2 Not yet present (the v2.1 additions)

- `reference.*` schema (taxonomy releases, reference concepts/labels/references/
  relationships, deprecations, Meta Model)
- `registry.analytics_metric` and `registry.metric_binding` (durable)
- `semantic.*` SQLMesh models (fact_meaning, fact_metric, observation_candidate)
- `analytics.*` SQLMesh models (metric_observation, annual/quarterly financials)
- A reference-taxonomy loader (Arelle-driven, offline-capable, idempotent)
- CLI: `edgar concepts show|unresolved|candidates`, `edgar metrics bind|bindings`

### 1.3 The migration tension (must be resolved explicitly)

The current `registry.mapping_assertion` carries durable rows of the shape:

```text
source_concept_id  →  target_metric_key  (+ target_definition_hash)
```

i.e. a source concept is mapped **directly to an analytics metric**. The v2.1
target changes the durable assertion shape to:

```text
source_qname_id  →  target_reference_concept_id   (accounting mapping)
reference_concept  →  analytics metric key           (metric binding, separate table)
```

Existing accepted assertions therefore encode a combined (accounting + metric)
decision in one row. Per v2.1 §22.3, the cutover must:

1. preserve historical evidence immutably (no rewrite of accepted rows);
2. where the rationale supports it, identify the intended reference concept and
   split the decision into an accounting mapping + a metric binding;
3. **not** silently infer a reference target where the old rationale does not
   support one — those rows must be marked for re-review;
4. leave no dual authority after cutover.

This is a **schema migration on a durable ledger**, so it requires a new Alembic
revision, a data-migration script, and an ADR. It is **not** a rollback-friendly
change; the plan gates it behind the spike.

### 1.4 Divergences from the v2.1 document's assumptions

| v2.1 assumption | Reality | Impact |
|---|---|---|
| "New recommended source table: `source.concept_reference`" (§5.8) | Already exists with full paired provenance | Skip; reuse existing table for reference-source comparison |
| `source.qname` as a new primitive (§5.5) | `source.concept` already serves this role (UUID from expanded QName, `namespace_uri`+`local_name` unique) | Do **not** introduce a parallel `source.qname` table. Reuse `source.concept`. Q1 (global QName table) in v2.1 §26 is resolved pragmatically: keep `source.concept` as the shared QName catalog and let `reference.concept` FK to it where useful. |
| "Add `source.concept_reference`" recommended | Done | No-op |
| Implicit assumption that metric contracts carry full accounting definitions | `metrics.yml` already carries `definition`/`includes`/`excludes` | These will be thinned to analytics intent only; accounting detail moves to `reference.*` |

---

## 2. Guiding principles for this plan

Carried forward from `AGENTS.md` and the v2.1 invariants (§3):

1. **Source fidelity is non-negotiable.** No economic deduplication in `source.*`;
   every filed fact occurrence remains independently queryable.
2. **QName identity is exact.** `namespace_uri + local_name`. Prefix and
   local-name-only are never identity.
3. **Arelle remains the XBRL/DTS authority.** We do not write a second taxonomy
   parser. Reference data is loaded through Arelle from official packages.
4. **Official semantics are consumed, not duplicated.** `metrics.yml` must not
   become a second FASB ontology.
5. **Accounting meaning precedes analytics mapping.** A fact resolves to an
   accounting meaning before it is bound to an analytics role.
6. **Candidate/ambiguous never publishes.** Only `resolved_exact` meanings with
   `accepted`+`exact` bindings are eligible for downstream observation
   publication.
7. **Alembic owns durable state; SQLMesh owns regenerable state.** No
   application-specific materialization identity or projection lifecycle.
8. **Laptop-first, offline-capable.** No cloud, no graph DB, no scheduler.
9. **Spike before schema.** No irreversible ledger rewrite until the empirical
   spike (Phase 2C0) report is reviewed.
10. **Phase scope respected.** No `semantic.*`/`metric_observation` publication,
    no LLM auto-acceptance, no candidate precedence, until a frozen Phase 2D+
    plan exists — which this document proposes to become upon ADR approval.

---

## 3. Phase sequence

The phases below mirror v2.1 §21 but are reordered/gated to fit the actual
codebase and to keep each step independently reviewable.

```text
Phase 2C0  Empirical semantic-resolution spike        (GATE — no schema change)
   │  ── review ADR gate ──
   ▼
Phase 2C1  Reference taxonomy foundation               (reference.* + loader)
   │
   ▼
Phase 2C2  XBRL-native registry cutover                (durable ledger migration)
   │  ── cutover ADR gate ──
   ▼
Phase 2D   Deterministic fact-meaning resolution       (SQLMesh semantic.*)
   │
   ▼
Phase 2E   Thin metric binding + observation selection (analytics.*)
   │
   ▼
Phase 2F   Issuer-lineage + candidate engine           (review burden reduction)
   │
   ▼
Phase 2G   Semantic benchmark + hardening
   │
   ▼
Phase 2H   Research interface                          (Parquet/DuckDB/Polars)
```

---

## 4. Phase 2C0 — Empirical semantic-resolution spike

**Goal:** validate the XBRL-native hypothesis on real filings **before** any
durable schema change. This is the mandatory gate from v2.1 §20 and §30.

**Hard scope lock:** no production schema migration, no registry cutover, no
auto-mapping rule, no `semantic.*` publication in this phase.

### 4.1 Corpus

Select ~20–30 heterogeneous issuers across 3–5 years each, spanning technology,
industrials, consumer, healthcare, financials, utilities, real estate. Include
issuers with many custom tags and issuers with relatively standard tagging.
Prefer filings already present in the project's FilingBundle/fixture
infrastructure.

### 4.2 Work

1. Inventory exact QNames and namespace families encountered.
2. For every relevant unique concept and fact occurrence, classify into the
   v2.1 §20.2 buckets:
   - A exact standard reference QName
   - B standard QName already bound to a target analytics metric
   - C exact issuer extension QName already reviewed (existing Phase 2C ledger)
   - D same issuer + same local name in another issuer namespace version
   - E new issuer extension
   - F resolvable through official `concept-dimensional-equivalent`
   - G deprecated/reference concept requiring explicit relationship interpretation
3. Measure three denominators (v2.1 §20.3): % of unique concepts, % of fact
   occurrences, % of facts relevant to the initial 30–50 analytics metrics.
4. Inspect FASB Meta Model usefulness on real examples.
5. Inspect deprecation relationships on real examples.
6. Draft initial reference-concept → analytics-metric bindings for the ~30–50
   roles in v2.1 §11.4.
7. Compare review effort against the current direct
   `source concept → canonical metric` workflow.

### 4.3 Deliverable

`docs/spikes/xbrl-native-semantic-resolution.md` with:

- coverage table (three denominators × seven buckets)
- failure examples
- recommended deterministic-resolution rules
- recommended exclusions
- schema changes validated/rejected
- a go/no-go recommendation for the registry cutover (Phase 2C2)

### 4.4 Acceptance gate

The report must answer the v2.1 §20.4 questions, in particular:

- What percentage of target financial facts use direct standard concepts?
- How often do issuer extensions repeat unchanged across filings?
- How often does same-issuer/local-name continuity correctly predict semantic
  continuity? (This gates auto-lineage in Phase 2F.)
- How many target facts need genuine semantic review?

**Do not** implement automated issuer-lineage inheritance until the spike
demonstrates a sufficiently low false-positive risk (v2.1 §20.5 gate).

### 4.5 Exit ADR

Record the cutover decision in a new ADR (next number after 0011) before
starting Phase 2C1 production work. The ADR must freeze:

- whether to proceed with the v2.1 cutover at all;
- the chosen answer to v2.1 Q1 (global QName table vs separate) — this plan
  recommends reusing `source.concept` as the shared QName catalog;
- the initial taxonomy releases to load;
- the initial analytics-metric vocabulary size.

---

## 5. Phase 2C1 — Reference taxonomy foundation

**Goal:** make official FASB/SEC taxonomy semantics queryable locally, offline,
through Arelle. No mapping decisions, no observations.

### 5.1 Schema (`reference.*`) — new Alembic revision `0003_reference`

Grains follow v2.1 §7. Reuse `source.concept` as the shared QName catalog where
practical (resolves v2.1 Q1).

```text
reference.taxonomy_release
  id, family, release, namespace_uri, entry_point_uri,
  local_package_path, sha256, published_at, loaded_at, arelle_version
  grain: one official taxonomy family release (unique: family, release)

reference.concept
  id, taxonomy_release_id, qname_id  -- FK → source.concept.id (shared QName catalog)
  data_type_qname_id, period_type, balance, abstract, nillable,
  substitution_group_qname_id, is_deprecated, deprecated_date
  grain: one concept declaration in one official release
```

Notes:
- `qname_id` and other `_qname_id` columns FK to `source.concept.id` (shared
  QName catalog). This avoids a parallel `reference.qname` table and keeps QName
  identity single-source. If benchmark queries later show friction, revisit per
  v2.1 Q1.
- `source.concept` rows needed only by `reference.*` are upserted during
  reference load (they are not filing-scoped; they are shared).

```text
reference.concept_label
  concept_id, role_uri, language, text
  grain: one label resource/use for one reference concept

reference.concept_reference
  concept_id, reference_role_uri, reference_parts_json
  grain: one reference resource/use for one reference concept
  (structured JSON parts initially — v2.1 Q2)

reference.relationship
  taxonomy_release_id, network_type, link_role_uri, arcrole_uri,
  source_qname_id, target_qname_id, order, weight, preferred_label,
  target_role, attributes_json
  grain: one relationship in one official release/network
  supports presentation / calculation / definition / deprecation / Meta Model
```

Idempotent load: reloading the same release upserts; natural uniqueness on
`(taxonomy_release_id, concept_qname_id)` etc. enforces no duplication.

### 5.2 Loader

`src/edgar/reference/load.py` (new module). Requirements:

- Input: official taxonomy package / entry point, locally cached.
- Arelle-driven; reuse the existing offline Arelle worker infrastructure.
- Immutable downloaded package with SHA-256, source URL, release identity,
  `loaded_at`, `arelle_version`.
- No network in unit tests; offline replay from a cached package.
- `LLM_ENABLED=false` must not affect this path.

CLI: `edgar reference load <family> <release>` and
`edgar reference show <family> <release>` (read-only).

### 5.3 Initial releases

Load only the releases needed by benchmark/current filings plus the current
release. Avoid "all historical taxonomy versions" as an initial requirement
(v2.1 §7.1). Initial families: US-GAAP GRT, SRT, FASB GAAP Meta Model.

### 5.4 Tests

- concept counts are stable for a fixed package (golden counts);
- known concepts locatable by exact QName;
- labels/references queryable;
- Meta Model relationships present;
- deprecation metadata queryable;
- reloading the same release is idempotent;
- offline load works with network disabled.

### 5.5 Definition of done

A query can answer: *What is this US-GAAP concept? What does FASB document about
it? What declaration properties does it have? What official
semantic/deprecation relationships does it participate in?*

---

## 6. Phase 2C2 — XBRL-native registry cutover

**Goal:** change durable semantic knowledge from direct analytics mappings to
accounting-meaning assertions, plus separate metric bindings.

**This is the highest-risk phase.** It mutates a durable ledger. Gated behind
the Phase 2C0 spike ADR. Requires its own cutover ADR before execution.

### 6.1 New durable tables — Alembic revision `0004_registry_v2_1`

```text
registry.analytics_metric         (replaces canonical_metric as the analytics API)
  key, name, statement_role, purpose
  grain: one analytics role
  regenerable: yes (registry sync from a thinned registry/metrics.yml)
  ownership: YAML mirror only

registry.metric_binding
  id, metric_key, reference_concept_id / reference_concept_series_key,
  relation, status, rationale, created_at, created_by
  grain: one governed binding from accounting meaning → analytics metric
  initial eligibility: status=accepted AND relation=exact
```

`registry/metrics.yml` is refactored to **thin analytics roles** (v2.1 §11.2):
`key`, `name`, `statement_role`, `purpose`. The current `definition` /
`includes` / `excludes` accounting detail moves out — authoritative accounting
semantics live in `reference.*`. Project-owned `purpose` documents analytical
intent only.

### 6.2 Mapping assertion shape change

The existing `registry.mapping_assertion` columns
`target_metric_key` + `target_definition_hash` are replaced (in a new revision)
by:

```text
target_kind              -- reference_concept initially
target_reference_concept_id   -- FK → reference.concept.id (nullable for unresolved)
relation                 -- exact | narrower | broader | related
```

The `target_definition_hash` concept (hash-stable acceptance) is preserved in
spirit by binding acceptance to the current `reference.concept` identity / series
key, not to a YAML metric hash. Exact mechanics of "stale accepted" detection
move from YAML-hash comparison to reference-concept-series comparison (v2.1 Q5,
gated on the spike).

### 6.3 Data migration (irreversible — requires ADR)

For each existing accepted `mapping_assertion` row:

1. **Preserve** the row immutably (append-only contract). Do not rewrite
   accepted history.
2. Where the rationale/evidence supports identifying a reference concept, create
   a successor assertion of the new shape pointing at
   `target_reference_concept_id`, and a `registry.metric_binding` row from that
   reference concept to the original `target_metric_key`.
3. Where the rationale does **not** support a reference target, create a
   successor marked `status=candidate` / `unresolved` for re-review. Do **not**
   silently infer a reference target.
4. No dual authority after cutover: the new assertion shape is the only live
   mapping authority. Old-shape rows remain as immutable history only.

A `registry.mapping_assertion` successor cannot branch
(`UNIQUE(supersedes_id)` is retained). The migration runs in a single
transaction per logical unit.

### 6.4 CLI

Implement the minimum review commands (v2.1 §17):

```bash
edgar concepts show <qname-or-id>
edgar concepts unresolved
edgar concepts candidates <qname-or-id>      # candidate generation in 2F; stub here
edgar mappings show/list/propose/accept/reject/supersede/export
edgar metrics show <key>
edgar metrics bindings <key>
edgar metrics bind <reference-concept> <key>
```

JSON output uses Pydantic schemas so coding agents can consume it directly.

### 6.5 Migration safety

- New Alembic revision with reviewed downgrade. Given the data migration,
  downgrade is schema-only (tables back) and does **not** reconstruct old-shape
  accepted assertions from new-shape rows. Document this as intentionally
  irreversible beyond schema.
- Integration test: load a frozen fixture ledger, run the cutover migration,
  assert (a) old rows preserved, (b) successors created, (c) no dual authority.
- Run `make check` and the phase-2 acceptance suite.

### 6.6 Definition of done

A reviewer can answer separately:

- *What does this filer concept mean?* (accounting mapping → reference concept)
- *Why do we believe that?* (evidence/rationale)
- *Which official accounting concept anchors it?* (`reference.concept`)
- *Which analytical metrics use that accounting concept?* (`metric_binding`)

---

## 7. Phase 2D — Deterministic fact-meaning resolution

**Goal:** resolve accounting meaning for facts **before** observation selection.
Regenerable SQLMesh models; no durable state.

**Phase scope note:** this phase *produces* `semantic.fact_meaning` but does
**not** publish `metric_observation`. It is the first phase that touches
`semantic.*`. It requires the frozen Phase 2D+ plan to exist — this section is
a *proposal* for that plan, not an authorization to start.

### 7.1 SQLMesh models

```text
semantic.reference_concept_series   -- family + local_name across releases
semantic.current_mapping_assertion  -- tip-of-chain accepted assertions
semantic.fact_meaning                -- one fact × resolved accounting meaning
semantic.meaning_coverage            -- coverage diagnostics
```

`semantic.fact_meaning` grain and columns (v2.1 §9.3):

```text
fact_id, meaning_kind, reference_concept_id, reference_concept_series_key,
resolution_method, resolution_assertion_id, resolution_relationship_id,
resolution_confidence, resolution_status, resolution_reasons
```

### 7.2 Initial resolution methods (only these)

1. `direct_reference_qname` — source concept QName equals a recognized
   reference QName.
2. `accepted_mapping_assertion` — current accepted exact assertion.
3. `concept_dimensional_equivalent` — official FASB Meta Model relationship,
   explicitly supported.
4. `vetted_lineage_rule` — minimal safe reference-concept lineage (stable
   element name across releases with no contradictory change metadata).

### 7.3 Explicit exclusions (do not auto-resolve)

- same local name only
- lexical similarity only
- AI candidate only
- broader/narrower mapping
- ambiguous deprecated replacement

Every relevant fact is classified `resolved_exact` | `candidate_only` |
`ambiguous` | `unresolved` with resolution lineage.

### 7.4 SQLMesh audits (hard)

```text
no candidate assertion in exact fact_meaning
no rejected assertion in fact_meaning
no conflicting applicable exact mappings
all mapped target concepts exist in reference.*
```

### 7.5 Tests

Unit + SQLMesh contract tests per v2.1 §19.5:

- standard QName → corresponding reference concept
- extension + accepted exact mapping → mapped reference concept
- dimensionally qualified fact matching official equivalence → equivalent concept
- candidate-only assertion → no exact fact_meaning publication

---

## 8. Phase 2E — Thin metric binding and observation selection

**Goal:** produce the first trustworthy canonical financial observations using
the revised semantic model.

### 8.1 SQLMesh models

```text
semantic.fact_metric            -- one meaning-resolved fact × applicable binding
semantic.observation_candidate  -- one mapped fact considered for one role
semantic.mapping_coverage
analytics.metric_observation
analytics.annual_financials
analytics.quarterly_financials
```

### 8.2 Selection rules (inspectable, not opaque)

Classify each candidate on (v2.1 §15.1):

```text
period_class      -- instant | quarter | year_to_date | annual | other_duration
entity_match
dimension_class   -- consolidated | segment | geography | product | other_dimensioned
unit_compatibility
filing_period_match
selection_status
selection_reasons
```

### 8.3 Ambiguity policy

If multiple incompatible facts remain equally eligible → `AMBIGUOUS`. Never
"first row after sorting wins."

### 8.4 Point-in-time

Every selected observation retains `source_filing_id` and
`knowledge_at = accepted_at`. This enables both latest-restated and
as-known-at-T views without look-ahead leakage.

### 8.5 Definition of done

A query such as:

```python
financials(cik="0000320193", metrics=["revenue", "operating_income",
                                        "net_income", "total_assets"])
```

returns historical observations with complete lineage:

```text
observation → source fact → accounting meaning resolution → reference concept
            → mapping assertion if applicable → metric binding → source filing
```

---

## 9. Phase 2F — Issuer-lineage and candidate engine

**Goal:** reduce manual review of recurring issuer extensions without weakening
correctness.

### 9.1 Candidate generators (progressively expensive)

1. same issuer + same local name across namespace versions
2. compatible declaration properties (data type, period type, balance,
   substitution group)
3. label/documentation similarity
4. authoritative-reference overlap
5. presentation/calculation structure
6. dimension usage
7. historical usage
8. AI-assisted semantic assessment (advisory only; default → `candidate`)

### 9.2 Libraries

Add `rapidfuzz` (lexical candidate reduction) and `networkx` (ephemeral
taxonomy/relationship graph analysis). No graph database (v2.1 §13.3).

### 9.3 Automation policy

```text
lineage detection → candidate            (always, initially)
lineage rule → automatic exact resolution  (only after benchmark in 2G)
```

AI output is always `status=candidate`. AI prose/similarity alone never
establishes an accepted exact assertion (v2.1 §13.4, AGENTS.md LLM policy).

### 9.4 Gate

Do not promote any lineage rule to automatic exact resolution until the Phase 2C0
spike false-positive evidence is reviewed and a benchmark in Phase 2G confirms
safety.

---

## 10. Phase 2G — Semantic benchmark and hardening

**Goal:** measure whether the system produces genuinely comparable financial
data across heterogeneous issuers.

Expand the corpus across industries and custom-tag behavior. Measure (v2.1
§18.2–18.6):

- source completeness
- reference-resolution coverage
- extension review burden
- exact mapping precision
- analytics metric coverage
- observation ambiguity
- historical continuity

Add quality diagnostics (not universal hard failures unless a rule is
sufficiently universal): balance-sheet reconciliation, subtotal relationships,
cash-flow relationships, historical discontinuity checks, unit anomalies.

**Decision gate:** only at this point evaluate whether the accounting-meaning
model requires more formal ontology machinery (LinkML, RDF, etc.) — all
explicitly out of scope until then (v2.1 §27).

---

## 11. Phase 2H — Research interface

**Goal:** expose trustworthy analytical data without changing the semantic
system of record.

Add `polars`, `pandera`, Parquet, DuckDB. Public functions: `financials()`,
`metric_history()`, `financials_as_of()`, `mapping_coverage()`,
`meaning_coverage()`, `concept_history()`. Exports:
`annual_financials.parquet`, `quarterly_financials.parquet`,
`metric_observations.parquet`. PostgreSQL remains the durable system of record;
notebooks consume released datasets, not operational tables.

---

## 12. Cross-cutting concerns

### 12.1 Documentation updates (required by AGENTS.md "Definition of done")

When each phase lands, update:

- [`../architecture.md`](../architecture.md) — add REFERENCE layer; update the
  production-flow diagram and storage table.
- [`../data-model.md`](../data-model.md) — add `reference.*` grains; document
  the `registry.mapping_assertion` shape change and `metric_binding`.
- [`../normalization.md`](../normalization.md) — rewrite the publication
  eligibility contract from `target_definition_hash == current YAML hash` to
  the reference-concept-series model; document accounting-meaning-vs-metric
  separation.
- [`../phase-2-plan.md`](../phase-2-plan.md) — replace the "Next" placeholder
  with the frozen Phase 2D+ plan reference once the 2C0 ADR is recorded.
- [`../project-roadmap.md`](../project-roadmap.md) — align Phase 2 workstreams
  with the v2.1 layer ownership table.
- New docs proposed by v2.1 §24: `xbrl-model.md`, `reference-taxonomies.md`,
  `semantic-resolution.md`. Create these only when there is real content for
  them (AGENTS.md: "Do not create modules until there is real implementation
  content").

### 12.2 ADRs required

- **ADR 0012 (Phase 2C0 exit):** go/no-go on the v2.1 cutover; freeze Q1 (QName
  table), initial releases, initial metric vocabulary size.
- **ADR 0013 (Phase 2C2 cutover):** the irreversible ledger migration; data
  migration rules; downgrade-is-schema-only acknowledgment.
- Additional ADRs for any Phase 2F auto-lineage promotion or Phase 2G ontology
  decision.

### 12.3 Testing posture (AGENTS.md "Testing rules")

- **Unit:** QName normalization, taxonomy-family detection, Arelle
  reference-taxonomy extraction, mapping service behavior, metric registry
  validation, deprecation relationship interpretation. No network or DB.
- **Property (Hypothesis):** prefix changes never change QName identity;
  local-name equality never proves exact mapping; candidate mappings never
  publish; source dimensions never disappear; fact occurrence multiplicity
  survives; ambiguous exact mappings never silently choose one.
- **Integration (Testcontainers PostgreSQL):** reference taxonomy load, source
  filing load, mapping decision, SQLMesh transformation, lineage query,
  migration rollback (schema-only).
- **Contract tests against Arelle:** ordinary US-GAAP, issuer extensions,
  explicit/typed dimensions, presentation/calculation/definition networks,
  IXDS, duplicate fact occurrences, taxonomy imports, annual namespace changes.
- **SQLMesh audits:** hard audits per v2.1 §19.6.

### 12.4 SEC access and offline discipline

Reference-taxonomy packages are downloaded once through the shared SEC/FASB
client (identified user agent, bounded rate, retries, caching) and thereafter
loaded offline. No live SEC/FASB calls in unit/default integration tests. Live
tests are opt-in and marked (AGENTS.md "SEC access rules").

### 12.5 LLM policy

Any AI-assisted candidate generation uses the existing LLM policy framework:
explicit purpose, versioned prompt, schema validation, model identity, input
hash, recorded parameters/failures, storage separate from canonical decisions.
`LLM_ENABLED=false` must not break reference load, ingestion, parsing, mapping,
or tests (AGENTS.md "Local LLM policy"; ADR 0003).

---

## 13. Open questions explicitly deferred to the spike (v2.1 §26)

Do not freeze these until Phase 2C0 reports:

- **Q1** Global QName table vs separate — *this plan recommends reusing
  `source.concept` as the shared QName catalog; confirm during 2C1
  implementation.*
- **Q2** Exact storage shape of concept references — *start with structured
  JSON parts (already the `source.concept_reference` shape); normalize only if
  benchmark queries demand it.*
- **Q3** Physical `semantic.fact_aspect` table/view — *the semantic requirement
  is mandatory; the storage shape is not. Start with wide fact/context joins,
  not a physical `fact_aspect` table.*
- **Q4** Automatic issuer concept-lineage inheritance — *blocked on spike
  false-positive evidence; Phase 2F gate.*
- **Q5** Metric bindings target exact release concepts or concept-series —
  *likely concept series for stable analytics; verify edge cases around
  deprecation/semantic changes.*
- **Q6** Which deprecation relationship types are safe for deterministic exact
  resolution — *relationship-specific, post-spike only.*
- **Q7** Which FASB Meta Model arcroles materially improve the first 30–50
  metrics — *do not build generic business logic for every arcrole before
  seeing real benefit.*

---

## 14. Explicitly out of scope until justified

Carried forward from v2.1 §27 and AGENTS.md "Active foundations scope":

- full IFRS normalization
- formal ontology framework / LinkML / RDF / triple store / graph database
- LLM autonomous acceptance
- all-taxonomy historical warehouse
- universal accounting reasoning engine
- cross-company segment ontology
- automatic derivation of arbitrary ratios
- scheduler / orchestrator / cloud data platform
- security-master or market data (roadmap Phase 5, separate)
- additional filing forms beyond 10-K/10-Q and amendments

---

## 15. Completion criteria for the overall initiative

The v2.1 end state (§29) is achieved when:

- one filing can be ingested from raw SEC files with every Arelle fact occurrence
  preserved and every source concept retaining exact expanded QName identity;
- official FASB/SEC taxonomy releases are reproducibly loadable and queryable
  (concepts, labels, authoritative references, Meta Model relationships,
  deprecations with their specific semantics);
- direct standard concepts resolve without manual mapping; reviewed issuer
  extensions resolve to reference accounting concepts; exact issuer QName
  decisions are automatically reusable; cross-version issuer continuity surfaces
  as candidates; local-name similarity alone never establishes truth;
- fact meaning is resolved before analytics mapping; dimensional equivalence
  can participate in meaning resolution; unresolved/ambiguous meanings remain
  visible;
- analytics metrics are thin stable API roles; accounting concept → analytics
  metric bindings are explicit and governed; observation selection is separate
  from semantic resolution; dimensioned/segment facts never silently become
  consolidated observations;
- every canonical observation traces to source fact + accounting meaning
  resolution + reference concept + mapping assertion (if applicable) + metric
  binding + source filing;
- mapping history is durable and reviewable; semantic/analytics tables are
  regenerable through SQLMesh; no parallel home-grown accounting ontology and no
  custom XBRL parser or graph database exists;
- a heterogeneous benchmark demonstrates useful coverage for the initial 30–50
  financial metrics, with manual review concentrated on genuinely novel issuer
  extensions, and source code remains materially leaner than a bespoke semantic
  platform.

---

## 16. Recommended immediate next action

Start Phase 2C0 — the empirical XBRL-native semantic-resolution spike using real
filings already present in the project's FilingBundle infrastructure. Do **not**
begin Phase 2C1 production schema work until the spike report and ADR 0012 are
complete.
