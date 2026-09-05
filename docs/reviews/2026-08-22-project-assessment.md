# Project assessment — leanness, dependencies, and the mapping review loop

**Date:** 2026-08-22
**Scope:** Full-repository static assessment (all `src/`, `tests/`, docs, migrations, registry),
plus runtime health checks. Focus areas requested by the owner:

1. Depth assessment and improvement candidates.
2. Where third-party libraries or higher abstractions would make the code leaner — and where
   they would not.
3. The core deliverable: the XBRL-fact → normalized-metric mapping loop, specifically how
   reasonable and transparent it is for review by humans and AI agents.

**Method:** Every `src/` package was read in full (three parallel read-only analysis passes over
`xbrl/`, `parsing/ + sec/ + ingestion/ + storage/`, and `db/ + domain/ + migrations/`; the
`registry/` core was read line-by-line directly). Dead-code and duplication claims were
re-verified against live source with grep before inclusion; the highest-impact claims were
independently re-checked. Working notes from the analysis passes are in gitignored
`var/reports/*-scout-findings.md`; this document is self-contained.

---

## 1. Verdict

The project is in **unusually good shape for its stage**: clean lint/format/typecheck, 316/317
tests passing (the one remainder is the network-marked live smoke test), disciplined layering,
and a mapping ledger whose integrity model (Git-authoritative YAML + append-only assertion
ledger + definition-hash pinning) is genuinely well designed for reviewability.

The leanness gap is not architectural — it is **residue**: superseded Phase-1 machinery kept
next to its V2 replacement, hand-maintained duplication that already shows drift, and a handful
of speculative abstractions. Concretely:

| Opportunity | LOC (approx.) | Risk |
| --- | --- | --- |
| Dead code deletion (verified zero consumers) | ~1,200–1,400 | Low |
| Behavior-preserving dedup refactors | ~950–1,100 | Low–medium |
| Replace hand-written wire codecs with pydantic v2 (already a dependency) | ~600–800 | Medium |
| Unify dual XBRL record models (delete `_source_build.py` translation layer) | ~500 | Medium–high |
| **Total** | **~3,300–3,800 (≈17–20% of `src/`)** | staged |

On libraries: the dependency list is already lean and well-chosen. The single high-leverage
addition is **none** — instead, deeper use of **pydantic v2** (already installed) and
**alembic autogenerate** (already installed) removes the most code. Explicitly rejected below:
tenacity, cachetools, an ORM/session layer, and a generic repository framework — each would add
weight without removing proportional complexity.

On the mapping loop: integrity and auditability are strong; the main gap is **evidence
assembly ergonomics**. A reviewer (human or AI agent) must currently hand-assemble the Clark
QName and evidence JSON for a proposal. A small `mappings evidence` review-pack command plus a
documented review checklist (§3.3) closes that gap without touching Phase 2D+ scope.

---

## 2. Current state

### 2.1 Health (executed 2026-08-22)

| Check | Command | Result |
| --- | --- | --- |
| Lint | `uv run ruff check .` | All checks passed |
| Format | `uv run ruff format --check .` | 161 files formatted |
| Types | `uv run pyright` | 0 errors, 0 warnings |
| Unit/contract tests | `uv run pytest -q -m "not database and not network"` | 257 passed |
| Database tests | `uv run pytest -q -m "database and not network"` | 59 passed (local Postgres via `docker compose up -d postgres`) |
| Committed JSON Schema freshness | programmatic compare of `registry/schema/mapping-report.schema.json` vs `MappingReport.model_json_schema()` | In sync |

Test corpus: 317 collected (257 unit/contract, 59 database, 1 network-marked live smoke).

### 2.2 Shape

| Package | LOC | Role |
| --- | --- | --- |
| `src/edgar/xbrl/` | 7,687 | Arelle adapter, extraction IR, worker IPC |
| `src/edgar/db/` | 2,477 | SQLAlchemy Core schema + repositories |
| `src/edgar/parsing/` | 2,233 | HTML blocks + section boundary detection |
| `src/edgar/registry/` | 1,561 | Canonical metrics + mapping ledger (core deliverable) |
| root modules (`cli`, `corpus_*`, `config`) | ~1,526 | CLI + corpus acceptance |
| `src/edgar/ingestion/` | 1,173 | Acquisition, catalog, extract orchestration |
| `src/edgar/domain/` | 1,165 | Identifiers, bundle model, URI/decode contracts |
| `src/edgar/sec/` | 1,077 | SSRF-pinned SEC client, submissions |
| `src/edgar/storage/` | 382 | Content-addressed objects, FilingBundle publish/load |
| `tests/` | 11,514 | unit / contract / integration |

Runtime dependencies (11): alembic, arelle-release (pinned), filelock, httpx, lxml,
psycopg[binary], pydantic, pydantic-settings, pyyaml, sqlalchemy, typer. Dev: hypothesis,
pytest, ruff, pyright.

Architecture follows the documented layering (CLI → services → domain → adapters) with the
important invariants actually enforced in code: Arelle objects stay inside `xbrl/`, parsing is
offline, the SEC client is the only HTTP path, Decimal-only numerics, and the registry never
mutates `source.*`.

---

## 3. Core functionality: the mapping loop

**What "core" means here:** build and maintain a reviewed mapping from XBRL facts
(`source.fact` rows keyed by concept) to normalized canonical metrics (`registry/metrics.yml`),
such that every mapping decision is reasonable, traceable, and reviewable by humans and AI
agents. This is Phase 2C and it is complete; observations/applicability remain Phase 2D+ and
are correctly out of scope.

### 3.1 What is strong (keep as-is)

- **Meaning is pinned, not implied.** `definition_hash` (SHA-256 over canonical JSON of the
  contract incl. `key`, excl. `name`) makes "the metric this candidate was reviewed against"
  machine-checkable forever. `accept` fails closed when the YAML hash drifted
  (`registry/service.py:302-314`); successors copy the original hash and never rewrite it.
- **The ledger is append-only and terminal states are terminal.** `UNIQUE(supersedes_id)` +
  service checks forbid branching; `rejected` is terminal; revocation is a new row, never an
  edit. Claim identity is copied field-by-field (`CLAIM_FIELDS`), so history cannot silently
  change meaning.
- **Conflicts are prevented, not detected after the fact.** Accept takes
  `SELECT … FOR UPDATE` on the source concept and rejects a second current+accepted+`exact`
  mapping over an overlapping scope (`service.py:316-346`), with interval semantics isolated in
  tested helpers (`registry/interval.py`).
- **Review artifacts are machine-consumable.** `mappings export` emits JSON/JSONL/Markdown with
  sorted keys and deterministic ordering, and `registry/schema/mapping-report.schema.json` is a
  committed, verified-in-sync JSON Schema — this is exactly what an AI-agent review loop needs
  to consume ledger state without parsing prose.
- **Affected facts are live, never cached.** `contains()` over `source.filing.report_period_end`
  is evaluated at read time, so ledger views can never go stale relative to re-extractions.
- **39 metric contracts** in `registry/metrics.yml` carry plain-English definitions with
  explicit `includes`/`excludes` — the single most important feature for "reasonable and
  transparent": a reviewer can disagree with words, not with hashes.

### 3.2 Gaps

1. **Evidence assembly is manual.** `mappings propose` takes a Clark QName and an evidence JSON
   file the reviewer must produce by hand (`cli.py:438-474`). All the raw material exists in
   `source.*` (`source_concept`, `source_concept_label`, `source_concept_reference`,
   `source_unit_measure`, `source_fact`, `source_relationship`), but assembling it requires ad-hoc
   SQL. This is the largest friction point for both human and agent reviewers, and hand-built
   evidence is where transcription errors enter.
2. **Propose accepts empty rationale/evidence.** Correct per the contract (candidates are
   reviewable content; only accept requires evidence), but a bare candidate gives a reviewer
   nothing to start from and makes agent-assisted pre-review harder.
3. **No impact column in `mappings list`.** Affected-fact counts are only computed in `show`.
   Triage ("which candidates touch the most filings?") requires one `show` per row.
4. **Doc drift on vocabulary.** `docs/metric-semantics.md` presents a ten-term relation
   vocabulary (`equivalent`, `issuer_equivalent`, `component_of`, …) and a five-stage pipeline;
   the implemented ledger has four relations (`exact|narrower|broader|related`) and no candidate
   pipeline. `normalization.md` is normative and correct, but a reader starting at
   `metric-semantics.md` can form the wrong model of what exists today.
5. **Minor inefficiency:** `export_mappings` computes the full affected-fact list per assertion
   and then slices to zero when facts are not requested (`service.py:441-454` with
   `fact_limit=0`). Harmless at laptop scale; worth a skip flag if exports grow.

### 3.3 Recommendations (mapping loop)

All are Phase 2C-scope; none implements candidate generation, applicability, or observations.

- **R1 — `edgar mappings evidence` review-pack command (highest value).**
  Given `--concept {ns}Local [--metric KEY]`, assemble a deterministic evidence pack from
  `source.*`: concept identity, labels, reference parts, declaration (period type/balance where
  persisted), units actually used, presentation/calculation neighbors, and up to N sample
  affected facts — emitted as JSON matching the `MappingEvidenceItem` shape so it can be edited,
  attached to `propose`/`accept` via the existing `--evidence` flag, and diff-reviewed in Git.
  This is evidence assembly for a reviewer-chosen concept, not candidate suggestion, so it does
  not cross the Phase 2D boundary. It also gives AI agents a sanctioned input format (per the
  local-LLM policy: LLM may draft rationale/evidence summaries; approval stays human).
- **R2 — soft propose-time warning** when `rationale`/`evidence` are empty: print a one-line
  hint ("candidates without evidence give reviewers nothing to evaluate") while still creating
  the candidate. Keeps semantics, improves hygiene.
- **R3 — fact-count column in `mappings list`.** One aggregate `COUNT(*)` per listed assertion
  (laptop scale makes this cheap) or a `--with-counts` flag.
- **R4 — a short review checklist doc** (e.g. `docs/mapping-review.md` or an appendix to
  `normalization.md`): what `exact` requires, which evidence kinds are acceptable for accept,
  how to use the review pack, and the explicit rule that neither an LLM nor an agent may accept.
  One page; makes human and agent reviews consistent and auditable.
- **R5 — one-paragraph reconciliation note** in `metric-semantics.md` marking its §4/§6
  vocabulary and pipeline as later-phase design, with a pointer to `normalization.md` as the
  implemented contract.

---

## 4. Leanness findings

### 4.1 Dead code (verified zero consumers in `src/`, `tests/`, `scripts/`)

| Location | What | ~LOC | Note |
| --- | --- | --- | --- |
| `xbrl/records.py` | Phase-1 wire codecs (`to_dict`/`from_dict` + `_KEYS` frozensets) for 13 record types; only `ExpandedQName`, `SourceLocator`, `SemanticIssueRecord` codecs are still live | 650–700 | Worker serializes via `source_wire`/V2 DTOs (`worker.py:552`); also `RECORDS_SCHEMA_VERSION` unused |
| `xbrl/extract.py` + `records.py` | `_used_on`, `_role_declarations`, `_arcrole_declarations` + `RoleDeclarationRecord`/`ArcroleDeclarationRecord` classes and codecs | ~155 | No callers anywhere (verified) |
| `xbrl/worker.py` + `diagnostics.py` | `LoadOutcome.diagnostic_records` channel (hard-set to `[]`), its wire key, `DiagnosticRecord` codecs, `blocking_diagnostics`/`blocking_occurrence_count`/`diagnostics_allow_complete`, legacy `"uri_objects"` job branch | ~90 | Abandoned evidence channel |
| `xbrl/semantic.py`, `locators.py` | `SemanticWorkerError` alias; `LocatorProvenance`/`occurrence_provenance` | ~25 | Verified unused |
| `parsing/html.py` | `_is_block_element`, unreachable `table` branch, always-empty `_BlockBuilder.issues`, `resolve_xpath` (test helper in `src`) | ~15 | Verified |
| `sec/client.py`, `sec/__init__.py` | `SecClient` alias | ~3 | Verified unused; stale test pycache references a deleted test |
| `ingestion/catalog.py` | `CatalogConflict` alias | ~2 | Check `scripts/` before deleting |
| `ingestion/payload.py` | Pure re-export shim of `domain/payload.py` | 7 | |
| `domain/bundle.py` | `BundleArtifact.equality_tuple`; `AcquisitionObservation` (exported, never constructed — Phase-2D-shaped placeholder) | ~25 | Un-export or delete; do **not** build Phase 2D around it |
| `domain/concept_id.py`, `db/source.py` | `concept_id_str`; `resolve_document_id` (in `__all__`, no callers) | ~20 | |
| `db/source_schema.py` | `source_xbrl_report.entry_document_id` column — written only as literal `None` (`source.py:534`), never read | — | Drop via a new autogenerated migration (med risk: schema change) |

**Subtotal: ~1,000–1,050 LOC in `xbrl/` alone; ~1,200–1,400 overall.** All low-risk deletions
except the column drop. Git history preserves everything.

### 4.2 Duplication clusters (behavior-preserving consolidation)

| Cluster | Where | ~LOC | Risk |
| --- | --- | --- | --- |
| Migration DDL ↔ SQLAlchemy metadata (hand-duplicated schema truth) | `migrations/versions/0001_source_v2.py` (792 ln) and `0002_registry.py` (271 ln) vs `db/source_schema.py`/`registry_schema.py` | ~1,060 | See §5.2 — process fix, not a rewrite; drift guard covers `source.*` only, **no parity test exists for `registry.*`** |
| Decode-helper block duplicated verbatim | `xbrl/records.py:98-167` ≈ `xbrl/source_wire.py:60-150` | ~110 | Low |
| `FetchHop` assembly ×8, three byte-identical except handlers, backoff expr ×3 | `sec/client.py:209-449` (`fetch_to_store`, 241 lines, 6–7 nesting levels) | ~100 | Low–medium; trace JSON shape must not change |
| Five copy-pasted fatal-safeguard except blocks | `xbrl/closure.py:299-360` | ~20 | Low (well test-covered) |
| Structured-error result shaping ×4 + divergent `main()` result dict | `xbrl/worker.py`, `semantic.py:59-182` | ~40 | Low |
| Inline `br`/`wbr`/tail text collection ×4 | `parsing/html.py` | ~40 | Low–medium (fixture-covered) |
| Section vocabularies encoded 5× (persisted keys, boundary keys, mapping, two Part sets) | `parsing/sections.py:21-95, 335-345, 771-791` | ~110 → one declarative table | Low |
| DP core duplicated (already subtly diverged: forced variant lacks skip-preference) | `sections.py:538-608` ≈ `656-703` | ~45 | Medium; golden-equivalence check needed |
| 11 near-identical bulk-insert builders | `db/source.py:563-975` | ~150 of ~430 | Low (`_insert_rows` helper; keep explicit SQL — see §5.3) |
| `_require_engine` ×3 + bundle-path prelude ×2 (+ triple identity verification with `BundleRepository.load`) | `ingestion/catalog.py`, `ingestion/source_extract.py`, `registry/service.py:166-171` | ~40 | Low |
| Atomic-write/fsync skeleton ×3 + dir-fsync ×2 (+ inline `import os` in `bundles.py:184`) | `storage/objects.py`, `storage/bundles.py` | ~50 | Low — durability-critical, consolidate verbatim |
| sha256-hex validation ×4; `validate_uuid4_hex` regex dance | `domain/bundle.py`, `domain/validation.py`, `domain/identifiers.py` | ~25 | Low |
| URL hosts hardcoded outside `domain/identifiers.py` | `sec/accession.py:83`, `sec/submissions.py:116` | ~5 | Low |
| Linear `any(a.logical_path == …)` scans ×5; duplicated issue construction; passthrough except; result mutated after return | `ingestion/acquisition.py` | ~30 | Low–medium |
| Clark/QName→string helpers ×4; IXDS-surrogate predicate ×2; `LocatorScheme` Literal ×2; manual sha256 vs `sha256_of_uri` | `xbrl/*` | ~40 | Low |

**Subtotal: ~950–1,100 LOC recoverable** (excluding the migration-DDL row, which is a process
fix rather than a deletion).

### 4.3 Speculative generality (single implementation, single use)

1. **`build_semantic_config`** (`xbrl/config.py:136-176`): 16-parameter factory; every caller
   passes nothing; of `SemanticConfig`'s 15 knobs exactly one is ever read
   (`extract.py:1347`). `to_dict` has no callers. Replace with a module constant.
2. **`FetchResult`** (`sec/client.py`): 12-field return type constructed by every fetch and
   discarded by every production caller (observations flow through `FetchTrace`/sink). Slim to
   `(StoredObject, trace)` or drop.
3. **`xbrl/uri.py`** re-export shim of `edgar.domain.uri`; **`ingestion/payload.py`** shim.
4. **`arelle_env.WebCacheLike`** protocol: one implementer, one consumer.
5. **`ObservationSink`** machinery: the only sink ever installed appends to a list.
6. **Multi-item-token block support** in `sections.py` (`item_tokens`, `MULTI_ITEM_SCORE_CAP`,
   fan-out): plausible EDGAR edge case, but if fixtures show it never fires it is the largest
   removable chunk of section complexity. **Verify against fixtures before touching.**

### 4.4 Longest functions (AST-measured)

| LOC | Function | Location |
| --- | --- | --- |
| 359 | `_acquire_body` | `ingestion/acquisition.py:231` |
| ~340 | `extract_filing_sections` (incl. 92-line nested `end_for`) | `parsing/sections.py:942` |
| 241 | `fetch_to_store` | `sec/client.py:209` |
| 195 | `run_online_closure` (incl. 89-line nested `handle_fetch`) | `xbrl/closure.py:229` |
| 134 | `_assign_item_parts` | `parsing/sections.py:737` |
| 124 | `run_offline_extract` | `xbrl/semantic.py:59` |
| 121 | `_run_load` | `xbrl/worker.py:469` |
| 116 | `_global_monotonic_dp` | `parsing/sections.py:538` |
| 111 | `_fact_record` | `xbrl/extract.py:1162` |
| 109 | `extract_report_extraction` | `xbrl/extract.py:1799` |

Nesting is generally shallow (≤4); the offenders are long flat guard-branch chains. Highest
split value: `_acquire_body` (per-artifact body → helper), `fetch_to_store` (hop executor →
helper), `persist_extraction` (101 lines; fatal-precheck and report loop → helpers).

---

## 5. Third-party libraries and abstractions

### 5.1 Adopt (all already installed — zero new dependencies)

1. **pydantic v2 for the XBRL wire codecs — the single biggest lever.** ~1,100 LOC of
   hand-written JSON codecs across `xbrl/records.py` + `xbrl/source_wire.py` map almost 1:1
   onto pydantic: `ConfigDict(extra="forbid")` ≙ `require_exact_keys`; `Literal[...]` fields ≙
   the 13 parallel `_KEYS` frozensets + `_require_literal`; `field_serializer` on `Decimal` ≙
   `_decimal_to_str`/`_nullable_decimal`; `RootModel[JsonValue]` ≙ the recursive `_require_json_value`.
   Converting `source_records.py` + `source_wire.py` alone removes ~600–800 LOC and eliminates
   the verbatim-duplicated decode-helper block. Caveats: fail-closed float rejection must be
   reproduced (a strict-mode validator), and round-trip fixtures must be byte-compared — the
   wire payload crosses the worker IPC boundary and `SOURCE_RECORDS_SCHEMA_VERSION` exists
   precisely for this. Do it as one sweep with byte-exactness tests, not piecemeal.
   (Do **not** churn `parsing/records.py` or `domain/decode.py` separately: `decode.py` is 102
   tidy lines guarding a frozen ADR-0009 wire format — leave it.)
2. **alembic autogenerate for all future migrations.** `env.py` already sets
   `target_metadata = metadata`. Stop hand-writing DDL that duplicates `*_schema.py`
   (~1,060 LOC duplicated today; the two schema modules already diverged stylistically —
   `autoincrement` vs `Identity()`). Add a registry-schema parity test mirroring the existing
   `test_v2_clean_head` source parity check. Do **not** retrofit frozen 0001/0002.
3. **stdlib round-trips:** `uuid.UUID(name, version=4).hex == name` for `validate_uuid4_hex`;
   one shared `assert_sha256_hex` (regex `re.fullmatch("[0-9a-f]{64}")` or reuse
   `SHA256_CHECK`) replacing four copies; `hashlib.file_digest`/`sha256_of_uri` for the manual
   digests in `xbrl/worker.py`.

### 5.2 Explicitly reject (would add weight, not remove it)

- **tenacity / custom-retry replacement:** the SEC loop cannot use `follow_redirects=True`
  because every hop needs fresh DNS resolution, IP pinning, Host-header override, and per-hop
  observation records (`sec/client.py:230-240`). tenacity would replace ~10 lines of backoff
  and hide the hops. **Keep the loop**; the only genuine gap is honoring `Retry-After` on 429
  (SEC fair-access policy) — add that inline.
- **cachetools / a caching layer:** there is no cache to shrink; the content-addressed
  ObjectStore *is* the cache, which is correct for provenance.
- **SQLAlchemy ORM / mapped classes / session-per-repository:** the Core + dict-row +
  caller-owned-transaction style (`engine.begin()` around one repository call; zero
  Sessions/savepoints repo-wide) is the lean correct shape for append-only provenance rows. A
  generic reflection-based row-builder would hide which columns persist. Only extract the tiny
  `_insert_rows` guard/execute helper.
- **Unit-of-work / repository base classes / DI framework:** three services sharing five lines
  of `_require_engine` is a function-extraction problem, not a framework problem.
- **rich/structlog/click upgrades:** typer already covers the CLI surface; output is
  deliberately plain and deterministic (export stability is a feature for agent diffing).

### 5.3 Higher abstractions that would *not* reduce code

- Unifying `records.py`/`source_records.py` by *adding* a shared base model: the win comes from
  deleting one model, not from a common superclass. The coherent cut is to have `extract.py`
  produce V2 DTOs directly (it already resolves logical paths), deleting `_source_build.py`'s
  ten `_build_*` mappers (~500 LOC) — a separate, schema-version-bumped change.
- Collapsing `registry` view models into dicts: the frozen pydantic views are what make
  `MappingReport` schema-stable and export-deterministic; they are load-bearing.

---

## 6. Prioritized plan

| P | Action | LOC | Risk | Verification |
| --- | --- | --- | --- | --- |
| **P0** | Delete dead code (§4.1) except the column drop; delete `SecClient`/`CatalogConflict`/`SemanticWorkerError` aliases, shims, `uri_objects` branch | ~1,200–1,400 | Low | grep-clean + full suite; no fixture/schema impact |
| **P0** | Mapping-loop quick wins R2–R5 (§3.3) | ~small | Low | CLI smoke + doc review |
| **P1** | Mechanical dedup: client.py hop helper + merged excepts; closure except collapse; error-shaping helpers; sections declarative table; `_insert_rows`; `_require_engine` helper; atomic-write primitive; sha256/uuid predicates; URL hosts | ~950–1,100 | Low–medium | Unit suites per module; acquisition trace JSON unchanged |
| **P1** | `mappings evidence` review-pack command (R1) | +~120 new | Low–medium | Integration test on constructed fixture; evidence JSON validates against `MappingEvidenceItem` |
| **P2** | pydantic wire-codec migration for `source_records` + `source_wire` | ~600–800 | Medium | Byte-identical round-trip fixtures; worker IPC E2E |
| **P2** | Drop `entry_document_id`; registry-schema parity test; autogenerate workflow for future migrations | — | Medium (schema) | Migration up/down on fresh DB; parity tests |
| **P3** | Unify dual record models; delete `_source_build.py` | ~500 | Medium–high | `SOURCE_RECORDS_SCHEMA_VERSION` bump; full corpus acceptance |
| **P3** | Split `_acquire_body`/`fetch_to_store`; sections DP parameterization; `Retry-After` support | — | Medium | Golden fixture equivalence; live-SEC opt-in test |

Suggested sequencing rule: never mix P0 deletions into P1 refactors; each row is an
independently shippable change with its own verification.

---

## 7. Documentation observations

- Docs are a strength: ADRs record supersession honestly (ADR 0010's Phase 2C amendment),
  `normalization.md` is a genuine normative contract, and `ONBOARDING.md` names complexity
  hotspots. Keep this discipline as the P0–P2 changes land: the dead-code deletions in
  particular should be mentioned in `PLANNING-CHANGELOG.md` so the historical narrative stays
  accurate.
- `docs/metric-semantics.md` should gain the implemented-vs-later-phase note (§3.2 item 4) — it
  is the one doc where a new reader (human or agent) can currently derive a wrong model.
- `semantic-registry/` (52K) and `scripts/spikes`-era material are correctly archived and
  unloaded by production code; no action.

---

## Appendix A — Commands executed for this assessment

```bash
uv run ruff check .                       # pass
uv run ruff format --check .              # pass (161 files)
uv run pyright                            # 0 errors
uv run pytest -q -m "not database and not network"   # 257 passed
docker compose up -d postgres
EDGAR_TEST_DATABASE_URL=... uv run pytest -q -m "database and not network"  # 59 passed
# programmatic check: registry/schema/mapping-report.schema.json == MappingReport JSON Schema
# grep verification of every dead-code claim against live sources (pycache excluded)
```

## Appendix B — Detailed working notes

Full per-finding analysis (with line-level evidence for every table row above) is preserved in
gitignored working files: `var/reports/xbrl-scout-findings.md`,
`var/reports/parsing-ingest-sec-scout-findings.md`, `var/reports/db-scout-findings.md`. This
document is the authoritative summary; the working notes are scratch.
