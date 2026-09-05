# Assessment of external AI feedback

**Date:** 2026-09-05. **Input:** user-supplied review beginning “Yes — that changes the comparison materially,” sections 1–25, commenting on the package committed as `508682a8445263e433cac93a9bf7673373ab7c68`. The attachment is external review material, not an implementation test, authoritative standard or owner adoption decision. Section numbers below identify its arguments without copying the review into the repository.

The main criticism holds: the original M1 bundled too much new persistence before financial utility. The revised plan separates publication-critical M1A from case-triggered M1B. The architectural recommendation otherwise remains direct guarded mappings to precise measurement contracts, with source aspects retained and observation selection separate.

## Disposition

| Feedback | Assessment | Plan treatment |
|---|---|---|
| §§1–17: native identities, direct contracts, additive interpretation, query results, lineage and explicit clocks | Agree with the reasoning; comparative praise is not additional evidence | Retain D1–D8; no new layer or rewrite |
| §§18–19: split M1 into essential integrity/inspection and richer evidence | Agree except for deferring the complete identity of existing networks | [M1A/M1B](migration-plan.md) now distinguish receipt/integrity/inspector from optional resource persistence |
| §20: measure repeated extension review effort from M3 | Agree, with independently defined denominators and honest unmeasured values | [Review-effort report](testing-and-quality.md#review-effort-and-taxonomy-continuity-measurement); no measurement service or mandatory inheritance experiment |
| §21: measure standard release continuity before concept series | Agree | D/F13 and M5 separate release transitions from issuer recurrence |
| §22: distinguish source meaning from fit to a contract | Agree | [Two required rationale sections](mapping-and-review.md#two-review-questions-one-durable-claim), one durable claim |
| §23: comparative ratings of fidelity, risk and robustness | Not established empirically | Do not convert ratings into acceptance results or migration estimates |
| §24: preferred architecture diagram | Consistent with the selected design | No further persistence layer needed |
| §25: recommended sequence | Agree through M3; do not interpret optional M1B/M5 as prerequisites for M4 | Mandatory M0 → M1A → M2 → M3 → M4; additional evidence activated only where needed |

## Why full network identity stays in M1A

The feedback groups full link/arc QNames with new evidence enrichment. In the current [extractor](../../src/edgar/xbrl/extract.py), `_exact_base_set_keys` and `_relationship_projection` already use `(arcrole, linkrole, link QName, arc QName)` to ask Arelle for a specific relationship set. The projection drops the last two fields. Retaining them carries an identity already used by extraction through the wire and persistence boundary; it does not introduce a generic QName registry or a new network model.

Two sets can differ in those fields while sharing role and arcrole. The proposed collision fixture tests whether that distinction survives. This is a code-supported representational risk, **not a claim that production corpus corruption was observed**. The implementation should remain bounded to propagating the existing key, with focused tests. Dedicated role/arcrole declaration tables and full footnote tables can wait.

## Deferring storage must not defer relevant evidence review

The feedback explicitly allows bringing evidence work forward when needed; we agree. The additional constraint is how to establish that need. Raw bytes make recovery possible, but an omitted SQL relationship does not tell a reviewer that a footnote is absent or irrelevant. Current [configuration](../../src/edgar/xbrl/config.py) excludes fact-footnote arcs, and omission counts are not fact-specific relevance judgments.

The revised packet records `available`, `assessed_absent`, `not_assessed` or `unsupported`, the inspected scope and any truncation. A bounded offline Arelle reader or pinned disclosure excerpt can supply evidence without dedicated tables. Actual XBRL associations must be resolved by Arelle, not inferred from XML proximity. If an omission is known only at report level, the application must not claim fact-specific irrelevance. Required evidence that cannot be assessed blocks that case. This is a qualification of the storage deferral, not a blanket footnote-graph requirement.

The original plan also required opaque non-dimensional context storage too early. Current `_mark_non_dimensional_content` and [its contract test](../../tests/contract/test_arelle_report_extraction.py) reject unsupported content. Keeping that behavior already prevents it from masquerading as a consolidated context. SQL preservation can wait for a named blocked filing; if introduced, it must retain financial disqualification until the semantics are supported.

## Review measurements do not establish economic equivalence

The proposed “unchanged declaration/economics” percentage combines two different observations. Structural equality can be measured mechanically; unchanged economics needs a reviewed disclosure comparison. Report them separately, including inconclusive and unassessed cases. Equal QNames or declaration properties cannot certify future applicability.

Similarly, rejected proposed exact inheritances divided by adjudicated proposed exact inheritances estimates a false-discovery proportion. A classical false-positive rate needs the denominator of actual negative cases under a defined evaluation population. Neither quantity can be reported without adjudication. M3 need not build an inheritance generator to measure a hypothetical error rate: report “not measured” and run a bounded shadow trial only if later justified.

Issuer recurrence, standard release transitions and reuse across multiple analytical contracts create different costs. High recurrence alone does not justify a reference-concept intermediary. Measure which work would actually disappear and which extra review chains factoring would introduce.

## Keep illustrative conditions from becoming selection shortcuts

The review's guarded-mapping and `CloudRevenue` examples illustrate structure; they are not reviewed financial assertions. A product revenue concept might fit a product-specific contract or be a component of total revenue. The name cannot establish exactness to consolidated total revenue.

Likewise, “no filed dimensions” belongs by default to the initial observation-selection profile. It becomes a mapping guard only if the economic equivalence itself depends on that condition. Putting it on every mapping would again confuse source meaning with the choice of analytical observation. Even dimension-free contexts still require entity, reporting-basis and period qualification.

## Optional enrichment need not delay temporal policies

The feedback's final list puts M1B/M5 before M4. Read literally as a dependency, this would make optional concept-series or dimensional work delay direct quarter and point-in-time queries. There is no general dependency. M4 follows the proven M3 selector; a particular missing piece of evidence can block a particular case at any phase. The migration diagram now makes those branches explicit.

## Comparative endorsement is not validation

Keeping the ledger and extending it avoids a second durable migration, which is a concrete reason to prefer this design. It does not establish a measured “low–moderate” migration risk, strongest fidelity, or robust historical financials. The earlier 51 passing tests concern selected existing behavior; the new selector, migrations and temporal policies remain unimplemented. No actual local ledger restore or financial benchmark was performed in this documentation revision.

The package remains a recommendation pending M0 adoption and benchmark review. Consolidating superseded documents does not itself freeze implementation scope. [Documentation consolidation](documentation-consolidation.md) records what was retained from old plans and why competing plans were removed.
