# Phased refactoring plan

**Date:** 2026-08-31
**Basis:** `docs/reviews/2026-08-31-xbrl-lineage-review.md` and
`docs/reviews/2026-08-22-project-assessment.md`
**Staging rule:** Phase 1 = all low-risk items. Later phases are staged by
ascending risk. Each item is independently shippable with its own verification.
No item depends on a later phase.

**Estimated total impact:** ~8,600-11,000 LOC removed, ~420-620 LOC added
(net ~8,000-10,400 LOC reduction, ~30-35% of `src/`), plus a materialized
analytics layer.

---

## Phase 1 — Low risk (cleanup, feature deferral, ergonomics)

All items are low-risk deletions, separable feature removals, or small
ergonomic improvements. None touch the XBRL adapter boundary or the schema
in a breaking way (one column drop, behind a migration). Can be shipped in
any order within the phase.

### 1a. Dead code deletion
- **What:** Delete verified-zero-consumer code identified in prior review §4.1:
  Phase-1 wire codecs in `records.py` (~650-700 LOC), unused
  `RoleDeclarationRecord`/`ArcroleDeclarationRecord` classes (~155 LOC),
  abandoned diagnostic channel in `worker.py`/`diagnostics.py` (~90 LOC),
  `SemanticWorkerError` alias, `LocatorProvenance`, `SecClient`/`CatalogConflict`
  aliases, `ingestion/payload.py` re-export shim, `concept_id_str`,
  `resolve_document_id`, `BundleArtifact.equality_tuple`,
  `AcquisitionObservation`.
- **Files:** `xbrl/records.py`, `xbrl/extract.py`, `xbrl/worker.py`,
  `xbrl/diagnostics.py`, `xbrl/semantic.py`, `xbrl/locators.py`,
  `sec/client.py`, `sec/__init__.py`, `ingestion/catalog.py`,
  `ingestion/payload.py`, `domain/bundle.py`, `domain/concept_id.py`,
  `db/source.py`, `db/source_schema.py`.
- **LOC:** ~1,200-1,400 removed.
- **Verify:** `grep`-clean for each deleted symbol; full test suite passes;
  no fixture/schema impact.
- **Note:** Do NOT drop `source_xbrl_report.entry_document_id` here — that's
  a schema migration, batch it into Phase 2.

### 1b. Archive `semantic-registry/` out of the tree
- **What:** Move `semantic-registry/` (Phase 2A archive, 4 JSON files +
  README) to a git tag or `archive/semantic-registry/`. Delete from working
  tree.
- **Why:** It is unloaded by production code (grep-confirmed) but taxes every
  new reader's mental model.
- **LOC:** ~0 (tree tax reduction).
- **Verify:** `grep -r "semantic-registry" src/` returns nothing; tests pass.

### 1c. Remove or defer document & section parsing
- **What:** Remove `src/edgar/parsing/` (~2,233 LOC), `xbrl/source_documents.py`
  (164 LOC), the `documents sections` CLI command, `source.document_block`
  and `source.filing_section` tables, and associated tests. Simplify
  `xbrl/source_extract.py:extract_filing` to drop the
  `extract_documents_for_filing` call (line 69) and the
  `document_blocks`/`filing_sections`/`issues` fields from `FilingExtraction`.
- **Why:** HTML document/section extraction is Phase 4+ text intelligence,
  not XBRL fact mapping. Structurally separable: the document path is a
  single call at `source_extract.py:69`, orthogonal to the XBRL report loop
  (lines 58-68). Restorable from git when text intelligence becomes a
  priority.
- **Files:** `src/edgar/parsing/` (all), `src/edgar/xbrl/source_documents.py`,
  `src/edgar/cli.py` (`documents` sub-app), `src/edgar/xbrl/source_extract.py`,
  `src/edgar/xbrl/source_records.py` (`FilingExtraction` fields),
  `src/edgar/db/source.py` (block/section persistence),
  `src/edgar/db/source_schema.py` (table defs), new Alembic migration to drop
  tables.
- **LOC:** ~2,400 removed (parsing + source_documents + tests).
- **Verify:** `filings extract` still produces XBRL reports; `documents`
  CLI group removed; migration up/down on fresh DB; integration tests pass
  (minus removed document tests).
- **Caveat:** The new migration drops `source.document_block` and
  `source.filing_section`. Include downgrade logic (recreate tables) for
  reversibility per AGENTS.md migration rules.

### 1d. Split `RegistryService` (752 LOC)
- **What:** Split `registry/service.py` into three focused services:
  - `RegistrySyncService` — `sync_canonical_metrics()`
  - `MappingLedger` — `propose_mapping()`, `accept_mapping()`,
    `reject_mapping()`, conflict detection
  - `MappingInspection` — `get_mapping()`, `list_mappings()`,
    `mapping_history()`, `affected_facts()`, `export_mappings()`
- **Why:** 752 LOC in one class mixing sync, ledger writes, and read models.
  Separable concerns; improves test focus and readability.
- **Files:** `src/edgar/registry/service.py` (split into three),
  `src/edgar/cli.py` (update imports).
- **LOC:** ~0 net (readability).
- **Verify:** All registry/mapping integration tests pass unchanged; CLI
  behavior identical.

### 1e. Mapping-loop quick wins (prior review R2-R5)
- **What:**
  - **R2:** Soft propose-time warning when `rationale`/`evidence` are empty
    (print hint, still create candidate).
  - **R3:** Fact-count column in `mappings list` (or `--with-counts` flag).
  - **R4:** Short review checklist doc (`docs/mapping-review.md`): what
    `exact` requires, acceptable evidence kinds for accept, the rule that
    neither LLM nor agent may accept.
  - **R5:** One-paragraph reconciliation note in `docs/metric-semantics.md`
    marking its §4/§6 vocabulary as later-phase design, pointing to
    `normalization.md` as the implemented contract.
- **Files:** `src/edgar/cli.py`, `src/edgar/registry/service.py` (or split
  services), `docs/metric-semantics.md`, new `docs/mapping-review.md`.
- **LOC:** ~small + 1 new doc.
- **Verify:** CLI smoke for R2/R3; doc review for R4/R5.

### 1f. Affected-facts short-circuit in export
- **What:** Add a skip flag to `export_mappings` so it does not compute the
  full affected-fact list per assertion when facts aren't requested
  (`service.py:441-454` currently computes then slices to zero).
- **Files:** `src/edgar/registry/service.py` (or `MappingInspection`).
- **LOC:** ~5-10.
- **Verify:** `mappings export` without `--include-facts` produces identical
  output; integration test.

---

## Phase 2 — Low-medium risk (mechanical dedup & evidence command)

Behavior-preserving consolidation. Higher care than Phase 1 (some touches
acquisition trace JSON or wire formats) but no structural changes.

### 2a. Mechanical dedup (prior review §4.2)
- **What:** Consolidate duplicated patterns:
  - `sec/client.py`: extract `FetchHop` helper from `fetch_to_store` (241
    LOC, 6-7 nesting levels); merge five copy-pasted except blocks.
  - `xbrl/closure.py`: collapse five fatal-safeguard except blocks (~20 LOC).
  - `xbrl/worker.py` + `semantic.py`: unify structured-error result shaping.
  - `parsing/sections.py`: replace 5x-encoded section vocabularies with one
    declarative table (~110 LOC); parameterize duplicated DP core (~45 LOC,
    golden-equivalence check needed).
  - `db/source.py`: extract `_insert_rows` helper from 11 bulk-insert
    builders (~150 of ~430 LOC).
  - `_require_engine` helper shared across `catalog.py`,
    `source_extract.py`, `registry/service.py` (~40 LOC).
  - `storage/`: consolidate atomic-write/fsync skeleton (~50 LOC).
  - `domain/`: one shared `assert_sha256_hex` replacing 4 copies; use
    `uuid.UUID` for `validate_uuid4_hex` (~25 LOC).
  - `sec/`: move hardcoded URL hosts to `domain/identifiers.py`.
  - `xbrl/`: unify Clark/QName→string helpers, IXDS-surrogate predicate,
    `LocatorScheme` Literal, manual sha256 vs `sha256_of_uri`.
- **LOC:** ~950-1,100 removed.
- **Verify:** Per-module unit suites; acquisition trace JSON shape
  unchanged; section golden fixtures byte-identical.

### 2b. `mappings evidence` review-pack command (prior review R1)
- **What:** New CLI command `edgar mappings evidence --concept {ns}Local
  [--metric KEY]` that assembles a deterministic evidence pack from
  `source.*`: concept identity, labels, reference parts, declaration, units,
  presentation/calculation neighbors, up to N sample affected facts. Emits
  JSON matching `MappingEvidenceItem` shape so it can be edited and attached
  to `propose`/`accept` via existing `--evidence` flag.
- **Why:** Evidence assembly is currently manual — the largest friction
  point for human and agent reviewers. All raw material exists in `source.*`;
  this command assembles it without crossing Phase 2D scope (no candidate
  suggestion, no auto-approval).
- **Files:** New `src/edgar/registry/evidence.py`, `src/edgar/cli.py`
  (new subcommand), `src/edgar/db/registry.py` (evidence query helpers).
- **LOC:** +~120 new.
- **Verify:** Integration test on constructed fixture; evidence JSON
  validates against `MappingEvidenceItem` Pydantic model.

### 2c. Drop `entry_document_id` + registry-schema parity test
- **What:** Drop `source.xbrl_report.entry_document_id` (written only as
  literal `None`, never read — prior review §4.1). Add a registry-schema
  parity test mirroring the existing `test_v2_clean_head` source parity
  check. Switch to alembic autogenerate for all *future* migrations (do not
  retrofit frozen 0001/0002).
- **Files:** New Alembic migration `0003_drop_entry_document_id.py`;
  `db/source_schema.py`; new parity test.
- **LOC:** ~0 net (schema cleanup).
- **Verify:** Migration up/down on fresh DB; parity test passes; `pyright`
  clean (column reference removed).

---

## Phase 3 — Medium risk (structural consolidation & analytics bridge)

These change the XBRL adapter's internal structure or add a new schema layer.
Each requires a version bump or migration and byte-exactness testing.

### 3a. Collapse dual XBRL record layer + pydantic v2 codecs
- **What:** Unify `records.py` (1,273 LOC) and `source_records.py` (489 LOC)
  into one record module. Have `extract.py` emit the unified record with
  logical-path provenance directly (it has the FilingBundle bindings
  available). Delete `_source_build.py`'s ten `_build_*` mappers (519 LOC).
  Replace hand-written JSON codecs in `records.py` + `source_wire.py` with
  pydantic v2 models (`ConfigDict(extra="forbid")`, `Literal[...]` fields,
  `field_serializer` for `Decimal`). Bump `SOURCE_RECORDS_SCHEMA_VERSION`.
- **Why:** ~2,970 LOC of translation between Arelle and the DB. The only
  material difference between the two record layers is canonical URI vs
  logical path — a mechanical mapping the build step already performs. The
  13 `Literal` type aliases are shared (`source_records.py:15-27` imports
  from `records.py`). pydantic v2 (already a dependency) generates the
  `to_dict`/`from_dict` that 1,100 LOC of hand-written code does manually.
- **Files:** `xbrl/records.py`, `xbrl/source_records.py`,
  `xbrl/source_wire.py`, `xbrl/_source_build.py`, `xbrl/extract.py`,
  `xbrl/worker.py` (if subprocess still exists), `db/source.py` (consumes
  records).
- **LOC:** ~2,000-2,500 removed.
- **Verify:** Byte-identical round-trip fixtures (wire payload crosses worker
  IPC boundary); `SOURCE_RECORDS_SCHEMA_VERSION` bump; full corpus
  acceptance; worker IPC E2E; fail-closed float rejection reproduced as
  strict-mode pydantic validator.
- **Dependency:** If Phase 4 (in-process Arelle) is done first, `source_wire.py`
  may already be gone — adjust scope accordingly. If Phase 5 (Arelle native
  export spike) concludes `extract.py` can shrink, the unified record shape
  simplifies. Recommend doing 3a before 4/5 to reduce their scope, but either
  order works.

### 3b. Materialized observation layer (Phase 2D)
- **What:** Add a `metric_observation` materialized view (or versioned
  snapshot table) over `source.fact ⋈ mapping_assertion` for accepted
  `exact` mappings. Refresh per extraction cycle. Columns: (metric_key,
  issuer_cik, report_period_end, value, fact_ids, mapping_assertion_id,
  observed_at). Define an observation-selection policy for duration vs
  instant metrics (sum facts in period vs latest instant). Add
  `edgar observations list|show` CLI.
- **Why:** The user's stated goal is "perform downstream analytics." The
  foundation maps concepts to metrics but nothing materializes a metric
  value. Every consumer re-joins `source.fact` to `mapping_assertion` via
  `contains()` at query time. This is the bridge from "trustworthy database"
  to "analytics-ready database."
- **Files:** New Alembic migration `0004_metric_observation.py`; new
  `src/edgar/observations/` package (service + models + CLI); new
  `src/edgar/db/observations.py`; `cli.py` (new sub-app).
- **LOC:** +~300-500 new.
- **Verify:** Integration tests: observation matches live affected-facts
  query for same mapping; refresh idempotency; point-in-time snapshot
  stability; CLI smoke.
- **Note:** This is a capability addition, not a refactor. It is the
  substantive semantic step the ledger currently avoids: for a duration
  metric, do we sum facts in the period? Take the latest instant? Respect
  calculation relationships for sign? The policy decision should be
  documented in a new ADR.
- **Alternative:** If a full materialization layer is too heavy, start with
  DuckDB as a read-side analytics engine over `source.*` (no schema change,
  no new foundation dependency — DuckDB lives in the analytics layer only).

---

## Phase 4 — Medium-high risk (adapter boundary collapse)

Changes the process architecture. Requires a spike to validate Arelle's
offline mode is genuinely quiescent before committing.

### 4a. In-process Arelle (collapse subprocess + IPC)
- **What:** Spike an in-process extraction path against one filing using
  `Cntlr(offline=True, disable_persistent_config=True)`. If Arelle's offline
  mode is genuinely quiescent (no socket attempts on a well-formed bundle
  whose DTS closure was pre-resolved at acquisition time), collapse:
  - Delete `xbrl/worker.py` (676 LOC), `xbrl/network_guard.py` (148 LOC),
    most of `xbrl/arelle_env.py` (251 LOC).
  - `xbrl/source_wire.py` (689 LOC) disappears if Phase 3a already
    collapsed it; otherwise delete it here (records no longer cross a
    process boundary).
  - `extract.py` emits records directly to the persistence layer.
  - Replace subprocess isolation with a process-level network allowlist or
    network namespace around the whole CLI if defense-in-depth is still
    desired.
- **Why:** ~1,764 LOC of isolation/IPC machinery that is defense-in-depth
  against a *pinned, offline, locally-fed* library. The FilingBundle
  pre-resolves the DTS closure at acquisition time
  (`ingestion/acquisition.py:501`), so by extraction time Arelle is fed
  local bytes bound to canonical URIs.
- **Files:** `xbrl/worker.py`, `xbrl/network_guard.py`, `xbrl/arelle_env.py`,
  `xbrl/source_wire.py`, `xbrl/semantic.py`, `xbrl/closure.py`,
  `ingestion/source_extract.py`, `ingestion/acquisition.py`.
- **LOC:** ~1,400-1,764 removed.
- **Verify:** Corpus acceptance: extracted facts byte-identical to
  pre-collapse baseline; no socket attempts logged during extraction
  (instrument or `strace`); Arelle version unchanged; fail-closed quality
  posture intact.
- **If the spike fails** (Arelle attempts outbound calls): keep the
  subprocess, document the threat model in an ADR, and ensure Phase 3a's
  pydantic codecs have already shrunk the wire layer.

---

## Phase 5 — High risk (extraction strategy evaluation)

Spike-gated. The outcome determines whether `extract.py` (1,910 LOC) can
shrink dramatically or is justified as-is. Do not commit to a full rewrite
until the spike concludes.

### 5a. Arelle native export spike
- **What:** Export one filing via Arelle's JSON DTS export plugin. Diff the
  field set against `source.fact`/`source.context`/`source.unit` columns.
  Specifically verify whether Arelle's export preserves:
  - `continuation_provenance` (inline XBRL continuation chain locators)
  - Exact element locators (`{scheme, value}` with `xml_id`/
    `unqualified_id`/`expanded_element_path` schemes)
  - `value_status` four-state (`valid|nil|invalid|unresolved`) with nil/
    invalid row preservation
  - Typed-member C14N XML + sha256 (`source.context_dimension.typed_member`)
  - `decimals`/`precision` as raw TEXT (INF-preserving), plus ixbrl
    `scale`/`sign`
  - `format_namespace_uri`/`format_local_name`/`escape` (ixbrl transform
    qnames)
- **Expected outcome:** split verdict — Arelle's concept/context/unit/fact-
  value enumeration is reusable; the locator/continuation/nil/ixbrl-format
  machinery is not and justifies a custom extractor.
- **If the spike favors Arelle export:** `extract.py` shrinks to a thin
  mapper from Arelle's export format to `source.*` rows. Potential saving
  ~1,000-1,500 LOC. Requires a new `EXTRACTOR_VERSION` bump and full corpus
  re-acceptance.
- **If the spike favors custom extract:** the conclusion itself is valuable
  — it converts "extract.py is overbuilt" into "extract.py is justified by a
  measured fidelity gap." No code change; document the finding in an ADR.
- **LOC:** 0 (spike) → 0-1,500 (if rewrite proceeds).
- **Verify:** If rewrite proceeds: byte-identical `source.*` rows vs
  pre-rewrite baseline on the full corpus; `EXTRACTOR_VERSION` bumped;
  golden fixtures unchanged.

---

## Dependency graph

```
Phase 1 (low risk)        Phase 2 (low-med)       Phase 3 (medium)
1a dead code ─────┐       2a dedup ───────┐      3a collapse records
1b archive ───────┤       2b evidence cmd ┤      3b observation layer
1c remove parsing ┤       2c column drop ─┘
1d split service ─┤
1e mapping wins ──┤
1f export skip ───┘
                        │                        │
                        ▼                        ▼
                 Phase 4 (med-high)      Phase 5 (high)
                 4a in-process Arelle    5a Arelle export spike
```

- **3a before 4a** is recommended (collapsing records first reduces the
  worker IPC scope), but either order works.
- **5a can run in parallel** with any phase — it is a spike, not a
  prerequisite. Its outcome may adjust 3a/4a scope.
- **3b (observation layer)** is independent of all refactors; it can start
  as soon as Phase 1 is clean. It is the highest-value item for the user's
  stated analytics goal.
- Within each phase, items are independent and can be shipped in any order.

---

## What this plan does NOT touch (load-bearing invariants)

- Immutable FilingBundle + SHA-256 content addressing
- `Decimal`/`NUMERIC` fidelity; nil/invalid fact preservation
- Append-only `mapping_assertion` ledger with hash-pinning and no-branching
- Git-authoritative `metrics.yml` + DB mirror authority model
- Provenance columns: `source_document_id`, `source_locator`, `report_key`,
  `extractor_version`, `arelle_version`, `extracted_at`
- Fail-closed quality posture (unrecognized diagnostics block "complete")

Every phase preserves these. The refactors are in the adapter translation
and feature-scope layers; the semantic invariants are upstream.
