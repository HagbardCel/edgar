# Independent architecture and implementation assessment — September 2026

**Status:** independent assessment and recommendation. **Not adopted.** Nothing here changes live
contracts, `AGENTS.md` phase gates or ADR 0010–0013. Adopting any recommendation requires a new ADR.
**Baseline:** `main` at `799540d` (clean tree), inspected and measured on 2026-09-27.

## Bottom line

1. **The evidence layer is strong in concept and worth keeping.** Immutable hashed bundles, isolated
   offline Arelle, faithful fact/context/dimension/network extraction, atomic per-filing replacement
   and a well-chosen set of edge-case fixtures are real assets. All 506 tests pass (398 offline in
   15 s, 108 PostgreSQL in 24 s); ruff, format and pyright are clean.
2. **Two months and ~71k added lines in, the system has produced no canonical financial value.**
   The adopted M1A→M4 plan makes mapping a human review process at three levels:
   - per report, for extension claims;
   - per taxonomy release, for standard concepts (exact QNames);
   - per occurrence, for qualification.

   That cannot reach the mission (market-wide research). It also contradicts the goal of minimal
   human intervention. No mapping decision has ever been recorded. The working database is still at
   revision `0001` without a `registry` schema.
3. **The hard problem is more tractable than the plan assumes.** An eight-row global rule table (one
   standard concept per metric) plus a selector of about 50 lines reproduces all **13/13**
   hand-verified M0 benchmark values from the existing source tables, with no per-report review. The
   selector is keyed on the EDGAR *required context*, the cover-page DEI context. The nine non-value cases are consistent with the same rules:
   - The questioned broader, narrower and related concepts are simply not in the table.
   - Slots without an exact undimensioned fact stay empty.

   Two of those nine were left open by the manual process although the answer is already in the
   captured bundle: the FASB definition of `NetIncomeLoss`, and a pair of *consistent* duplicate
   facts.
4. **Much of the complexity is self-created:**
   - ~3k lines of parallel DTO/wire code.
   - One fact-count invariant re-checked in 13 files.
   - A DB ledger and YAML mirror that have never held a decision.
   - Per-report storage of the entire US-GAAP taxonomy (~97% of declaration rows unused, ~47% of
     database bytes).
   - ~55k words of planning and governance prose.
5. **Scale has never been measured.** Offline extraction takes 93–105 s per 10-K. Roughly 80–90 s of
   that is a quadratic locator-uniqueness scan; Arelle's own load takes 0.8 s. At the current speed, one
   year of 10-K/10-Q filings is roughly a CPU-month.
6. **Recommended convergence** is a smaller system with one owner per kind of truth:
   - Immutable raw store and pinned taxonomies.
   - Arelle extraction into an embedded columnar store (DuckDB/Parquet).
   - Git-authored contracts, mapping rules and gold values.
   - One deterministic resolve/select engine.
   - A validation harness with independent oracles.
   - Review of exceptions only, optionally with LLM proposals.

   An estimated 9–12k of today's 23.8k production lines become removable or replaceable, and
   2.5–4k new lines add mapping, selection and validation.
7. **Re-sequence around the central risk.**
   - Stop M1A/M2 lifecycle work.
   - Ship a walking skeleton that produces values for the eight benchmark metrics on the six filings.
   - Run a 500–1,000-filing scale spike with automated oracles before building further
     infrastructure.

## Documents

| Document | Question it answers |
|---|---|
| [01 Goals and principles](01-goals-and-principles.md) | What must the system accomplish, and how should it be built? |
| [02 Current-state assessment](02-current-state.md) | What is valuable, what is accidental, what the measurements show |
| [03 Capability and code-size inventory](03-capability-inventory.md) | Where the code is, by function, and what kind of code it is |
| [04 Recommended architecture](04-target-architecture.md) | Components, ownership, data flow, durable vs derived state, interfaces |
| [05 Mapping strategy](05-mapping-strategy.md) | How to reach high-confidence mappings at scale with little human effort, and how to measure it |
| [06 Gaps and opportunities](06-gaps-and-opportunities.md) | Prioritized architectural issues and optional refinements |
| [07 Trade-offs of a lean architecture](07-lean-architecture-tradeoffs.md) | What the adopted plan and this recommendation give up |
| [08 Migration plan assessment](08-migration-plan-assessment.md) | What to keep, cut or move in M1A–M5; revised sequence |
| [Implementation sequence](plan/README.md) | Junior-implementable steps P0–P6, one file each, with validation gates |
| [A Evidence and method](A-evidence-and-method.md) | Commands run, raw measurements, experiment scripts |
| [B Feedback response](B-feedback-response.md) | Independent reply to a hybrid-architecture critique; records what changed |
| [C Hardening response](C-feedback-response.md) | Second critique: specification holes closed; architecture not reopened |
| [D Hardening response](D-feedback-response.md) | Third critique: family namespaces, OIM grouping, P2 audit; architecture settled |
| [E Hardening response](E-feedback-response.md) | Fourth critique: last contract pins; architecture review closed |
| [F Contract notes](F-feedback-response.md) | Implementation-contract pins; architecture review stays closed |
| [G Contract bugs](G-feedback-response.md) | Issuer expansion, slot eligibility, gold union; architecture stays closed |
| [H Contract cleanup](H-feedback-response.md) | Stale rejection, `broader_only`, multi-decision scope; architecture stays closed |
| [I Baseline pins](I-feedback-response.md) | Baseline assertions, no `unsupported` decision; architecture stays closed |

Read 01 → 02 → 05 → 04 → 08 for the argument; 03, 06, 07 and A are reference
material. Implement from [plan/](plan/README.md). Revisions after critique:
[B](B-feedback-response.md) through [I](I-feedback-response.md).

## Key measurements (2026-09-27, local corpus of six filings)

| Observation | Value |
|---|---|
| Hand-verified benchmark values reproduced by an eight-row global rule table + required-context selector | 13 / 13 |
| Mapping decisions recorded in any database | 0 |
| Offline extraction time per 10-K (Walmart, two runs; eBay) | 92.9 s / 93.9 s; 105.0 s |
| … of which Arelle load | 0.8 s |
| … of which locator uniqueness scans over the US-GAAP schema (extrapolated, two runs) | ~82–87 s |
| Concept declarations stored per report vs concepts used by facts | ~18.5k vs 376–871 |
| Share of database bytes in `concept_declaration` + `concept` | 59 of 125 MiB (47%) |
| Facts using standard (US-GAAP/DEI/SRT) concepts | 85.6% |
| Extension share of primary-statement line items | 2–14% per filing |
| Production / test lines (physical, incl. migrations and scripts) | 23,771 / 18,657 |
| Lines added by M1A work packages 1–3 (receipts, link/arc QNames, integrity; code, tests, docs) | +7,805 |
| Planning/governance documentation | ~55k words |

This directory is itself a temporary decision aid. Once its recommendations are accepted or
rejected through ADRs, it should be archived like the rest of the planning material (principle 11 in
[01](01-goals-and-principles.md)).

## Method and limits

The assessment is based on these inputs:

- A full read of the adopted architecture package, ADRs 0009–0013, the August reviews, and the core
  source modules, schema, registry, benchmark and tests.
- Execution of the test suites and static checks.
- Read-only queries against the local `edgar` database.
- Timing of real offline extractions.
- Two ad hoc experiments, kept outside `src/`: the global-rule benchmark reproduction and a
  primary-statement extension census.

Commands and scripts are in [A](A-evidence-and-method.md).

The evidence corpus is the project's six filings. Everything stated about market scale is either
arithmetic from measured per-filing costs or a hypothesis. The recommended scale spike exists to
confirm or refute those hypotheses. No production code, schema, fixture or registry content was
changed.
