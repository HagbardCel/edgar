# Documentation consolidation and retained knowledge

**Date:** 2026-09-05. **Scope:** user-requested consolidation of the target package and existing plans. This is documentation maintenance, not M0 adoption or production migration. The target package moved from root `architecture/` to `docs/architecture/`. [The documentation index](../README.md) distinguishes implementation contracts, the sole target recommendation, and historical evidence.

## Removed plans and where their value went

All seven files below are available in commit `508682a8445263e433cac93a9bf7673373ab7c68`, before consolidation. No sole copy of historical reasoning is being destroyed. Their useful requirements are retained below or in the linked current documents; their sequencing and speculative schemas are not competing implementation instructions.

| Former path | Useful content retained | Why remove the plan |
|---|---|---|
| `docs/phase-1-plan.md` | Immutable artifacts, offline replay, occurrence/Decimal fidelity, document provenance: current AGENTS/ADRs and [fixture policy](../fixture-policy.md). Corpus gates and demonstrations: notes below and [testing](testing-and-quality.md) | Old projection/attempt model, CLI and unchecked completion list contradict the Phase 2B cutover; foundations no longer need a scaffolding plan |
| `docs/phase-2-plan.md` | Completed 2A/2B/2C status and exit-contract distinctions: [index](../README.md#completed-milestones-and-current-boundary); precise live registry rules: [normalization](../normalization.md) | Short completed-phase history plus an empty next-phase placeholder; no separate forward plan remains |
| `docs/project-roadmap.md` | Long-term product intent and research safeguards: deferred requirements below; periods/restatements: [target](target-architecture.md); mapping quality: [testing](testing-and-quality.md) | Premature ontology/precedence/observation phases, stale status and a 100–300 issuer first-release scope compete with the bounded M3 milestone |
| `docs/plans/edgar_v2_target_architecture_and_plan.md` | Conservative financial contracts, source/knowledge ownership, evidence/review/history and dimensional distinctions: [data model](data-model.md) and [mapping](mapping-and-review.md) | Replaced by independently derived entities and migration sequence; no mandatory transformation platform |
| `docs/plans/edgar_v2_1_xbrl_native_target_architecture_and_plan.md` | Exact QName/declaration distinction, official taxonomy evidence, deprecation and dimensional-equivalence cautions, standard/issuer release continuity, empirical evaluation: D1/D2/D7, F1/F2/F4/F13/F14 and M5 | Mandatory reference warehouse, source→reference→metric chain and SQLMesh are not selected; proposed schemas and phase numbers are superseded |
| `docs/plans/xbrl-native-implementation-plan.md` | Actual-ledger inventory, export/restore, never rewriting claim identity, stable evidence, corpus decision gates: M0/M2 and rollback discipline | Implements the superseded v2.1 target, including incompatible ledger cutover and fixed migration names |
| `docs/reviews/2026-08-31-refactoring-plan.md` | Evidence inspector, bounded export work, dead-code candidates, schema parity and codec simplification: M1A/M2 and optional consolidation; detailed diagnostics remain in the retained August reviews | Risk/LOC-based sequence is not product priority; document deletion, in-process Arelle, and naive duration aggregation are rejected or not selected |

Recover a complete original, for example:

```bash
git show 508682a8445263e433cac93a9bf7673373ab7c68:docs/plans/edgar_v2_1_xbrl_native_target_architecture_and_plan.md
```

The same command works with any former path in the table. Earlier root `architecture/` documents are also in that commit. No tag, duplicate archive or compatibility pointer file is necessary.

## Foundation knowledge retained beyond the old phase schedule

The real corpus gate covers two annuals, two quarterlies, an amendment, multiple industries, used extensions, dimensional facts, presentation roles and a same-issuer taxonomy transition. Distinguish real-corpus evidence from constructed parser contracts and informational coverage. Awkward HTML and continuation behavior need focused fixtures even when the six-accession corpus does not demonstrate every case. Acquisition inventory/hash expectations remain separate from parser expectations. The authoritative current acceptance behavior is in [fixture policy](../fixture-policy.md), repository commands and tests; old projection-ID procedures are obsolete.

Inspection should support filing inventory; located sections; concept labels/references; role-scoped presentation and calculation neighborhoods with weights; dimensional relationships; concept facts with contexts/units; and fact-to-document/parser/artifact provenance. M1A provides a bounded review packet rather than restoring removed Phase-1 inspection commands. Missing role/footnote SQL is explicitly a capability gap, not proof of a completed foundation contract.

Semantic research should distinguish denominator populations: all fact occurrences, distinct concepts, and requested analytical slots. High all-fact coverage does not demonstrate coverage of economically important line items. Official reference packages can supply definitions, references, change metadata and Meta Model relationships, but must be pinned separately from the filing DTS. Deprecation/replacement, common local names and conceptual components do not automatically imply exact equivalence; concept/dimension substitution needs explicit consumed and residual aspects. These requirements survive without a reference-layer mandate.

## Refactoring ideas retained with limits

The two retained August reviews contain concrete dead-code and duplication locations: legacy codecs/aliases, error shaping, source insert builders, atomic-write helpers, section vocabularies and service responsibilities. They are inspection leads, not verified-zero-consumer deletion permissions forever. Recheck consumers and behavior against the implementation at the time of change.

Optional cleanup can skip affected-fact enumeration when an export does not request it, share bounded count queries, and separate registry mutation from inspection where it improves clarity. M1A's inspector and M2's evidence requirements supersede a weak “empty rationale” warning as the publication safeguard. Full source/registry schema parity and populated migration tests remain required. Do not force every migration to be autogenerated or split services merely to meet a line-count target.

Keep deterministic document parsing and Arelle process/network isolation. “No socket attempt on one successful filing” is insufficient evidence that in-process loading is a safe equivalent boundary. Keep archived semantic evidence under current AGENTS rules. Do not sum arbitrary duration facts or pick the latest instant as a generic selector. A library export replacement must pass D1's provenance/fidelity suite before adoption. LOC-reduction estimates in old reviews were not measured migration outcomes.

## Deferred product requirements from the long-term roadmap

These preserve valuable intent without freezing tables, vendors, phases or a research universe. They are not added scope for M1A–M4.

| Future capability | Requirements worth preserving | Evidence and decision trigger |
|---|---|---|
| Historical security and market joins | Registrant ≠ security/share class; dated ticker/exchange/vendor identifiers, mergers/spin-offs and delistings. Retain raw prices, dividends/splits/corporate actions, adjustment policy and vendor provenance | Named market study, licensed/available data and reviewed historical-identity examples; separate product plan before implementation |
| Filing-event outcomes | SEC acceptance time plus exchange calendar/session; explicit pre/during/after-market and non-trading-day alignment. Daily effective date is a policy; intraday studies need intraday observations | A defined return window and clock/calendar fixtures; never silently substitute filing date |
| Derived fundamentals | Quarter subtraction, trailing periods, growth, margins, accruals, cash conversion, net debt and dilution need explicit formulas and compatible basis/unit/accuracy/time inputs | Named research definition and counterexamples activate F6/M5; no formula inferred from a familiar name |
| Empirical datasets | Pin universe, source receipts, contracts/decisions, selector/formula, security/market/return policies, code and output manifest. Include missingness and mapping uncertainty; compare direct/derived and standard/extension subsets | One specified reproducible study after suitable temporal coverage; Parquet/DuckDB remain format/tool choices, not prerequisite infrastructure |
| Statistical validity | Historical universe including failed/delisted issuers; growth is not earnings surprise without an expectation model. Predefined hypotheses, time-based holdout, overlapping-return and multiple-testing controls, mapping sensitivity and transaction/liquidity assumptions when relevant | Approved study protocol determines required controls; do not build a generic statistics framework now |
| Broader acquisition | Bounded backfill, explicit coverage by issuer/industry/taxonomy era, failure accounting and sampled review. Additional forms/accounting regimes need their own extraction/section/semantic fixtures | Concrete coverage demand after narrow correctness gates; profile before adding queues/workers/partitions |
| Filing text research | Retain located text/tables, compare sections/blocks over time, distinguish regulatory format change and boilerplate from new disclosure. Any model output needs source citations, prompt/model/input provenance, evaluation and abstention | Named text question and labeled cases; embeddings only when retrieval needs them, not as a required next phase |
| Applications and deployment | Start with local inspection/exports; assess users, latency, concurrency, access and recovery needs | Demonstrated consumer need before UI, shared services, ontology inference or cloud deployment |

The old roadmap's example question—whether fundamental changes and disclosure novelty add information about post-filing outcomes—remains a possible research direction. Its ten-year/100–300 issuer universe, feature list and return windows are not commitments. M3 first delivers a defensible bounded financial comparison; market research follows a separately specified study.

## Documents retained deliberately

- `docs/architecture.md`, `data-model.md`, `normalization.md`, `development.md`, `data-quality.md` and `fixture-policy.md` document current behavior. They are not redundant with a future target. Status and navigation distinguish their authority.
- `docs/metric-semantics.md` is condensed to financial domain cautions and evidence requirements. Competing layer/table lists, scope precedence and automatic acceptance prescriptions were removed; current normalization and the target package own those decisions.
- ADRs preserve adopted decision history, including superseded decisions explicitly labeled as such. Diagnostic reviews and the offline closure spike retain code locations, historical tests and hard-won integration findings. Their recommendations do not override the target plan.
- `PLANNING-CHANGELOG.md` remains a historical change record; former filenames there describe past edits. The generated, ignored onboarding output is not planning authority and was not rewritten.

Follow future changes through the [documentation index](../README.md), not through deleted plan names. AGENTS reading instructions and repository navigation are updated accordingly. No live schema, parser, fixture, registry or runtime dependency changed during consolidation.
