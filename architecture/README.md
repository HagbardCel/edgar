# Independent target architecture and migration plan

**Date:** 2026-09-05. **Baseline:** `536ee25002bccfb72b50e02cf8397c2e3972635d`.
**Status:** independent recommendation for decision; no production changes or phase gate changes are made by this package. “Decision made” means this recommendation has resolved the architectural question, not that the owner has adopted it. Deferred decisions have explicit evidence triggers.

## Recommendation

Keep the immutable FilingBundle, Arelle, and the relational XBRL source model. Add a small, precise canonical vocabulary, auditable conditional mapping assertions, and an explicit financial observation query. Preserve every source occurrence; make normalization an additional interpretation of its complete aspects.

Use one Python application, one local PostgreSQL database, and the filesystem. Continue Git authority for metric contracts and database authority for semantic decisions. Use ordinary SQL and typed Python for mapping application and selection. Do not require an ontology, reference-taxonomy warehouse, SQLMesh, graph database, or a second accounting-to-metric mapping ledger.

This retains parts of the implementation because they solve the problem well, rather than because an earlier plan selected them. It rejects the mandatory reference-concept intermediary proposed in the historical v2.1 plan: a reference taxonomy is valuable evidence, but it cannot eliminate the application's responsibility to define comparability.

## Read this package

| Document | Decision it supports |
|---|---|
| [Current assessment](current-state-assessment.md) | What actually exists, what is missing, and what deserves preservation |
| [Target architecture](target-architecture.md) | Product boundary, semantic stages, observation selection, and time |
| [Data model](data-model.md) | Entity grains, identities, ownership, durability, and lineage |
| [Mapping and review](mapping-and-review.md) | Meaning contracts, assertion conditions, conflicts, corrections, human/AI workflows |
| [Decisions and technology](decisions.md) | Credible alternatives, recommendations, trade-offs, and deferred decisions |
| [Migration plan](migration-plan.md) | Repository-specific implementation phases and removal work |
| [Testing and quality](testing-and-quality.md) | Semantic acceptance gates, benchmark, self-review, and validation performed |

## The shortest useful route

1. **M0:** adopt the selected decisions and a bounded financial benchmark; inventory and back up actual local semantic decisions.
2. **M1:** close specific source lineage gaps and provide an inspectable concept/fact evidence packet.
3. **M2:** tighten measurement contracts, retain definition snapshots, and add conservative report-scoped mapping conditions and atomic corrections.
4. **M3 — first useful financial release:** query selected reported annual values across the existing annual filings, with exact periods, explicit missing/conflict results, and portable lineage. Deliver JSON/CSV and an immutable export manifest together.
5. **M4:** add explicit historical publication policies, quarter/YTD distinction, amendment evidence, and strict point-in-time modes.
6. **M5:** expand only where benchmark failures justify dimensional equivalence, derivations, taxonomy-package evidence, or AI assistance.

M3 is a financial analysis tool for a bounded set of companies and metrics. It is not a market-wide historical database or a backtest-ready dataset. Reaching it does not require a 20–30 issuer semantic research program, an ontology, or a rewrite of acquisition.

## Consequential departures from earlier proposals

- A canonical metric remains a **measurement contract**, not merely a thin alias for a FASB element. Several existing contracts are too permissive and need narrower definitions.
- Concept identity, source declaration, and economic meaning remain distinct. Do not add another global QName catalog.
- A mapping normally targets a canonical contract directly. Reference-concept comparisons are evidence, without an obligatory second review chain.
- Context-sensitive mappings are guarded assertions; they do not silently discard dimensions. Dimensional rewriting is a separate, deferred capability.
- There is no automatic “more specific mapping wins,” “latest fact wins,” or score-based tie-breaker.
- Current source tables remain replaceable. Published results retain small immutable snapshots and evidence pins, rather than preserving every parser execution in a new versioning framework.
- Retain the offline subprocess and document parser. Simplify redundant DTO/codec code separately, after financial value is delivered.

## Confidence and limitations

The recommendation is grounded in code/schema/test inspection, historical plan comparison, primary XBRL/Arelle/SEC documentation, and 51 passing focused offline tests. The current YAML contains **39** metrics; historical references to 20 are stale. The six-accession corpus is a starting point, not a demonstrated normalization benchmark.

No local ledger contents or live corpus outputs were audited, no financial mappings were approved, and no PostgreSQL integration suite was run for this documentation change. Coverage, latency, and review-effort targets in this package are acceptance targets, not measured results. See [validation and limitations](testing-and-quality.md#validation-performed-for-this-package).
