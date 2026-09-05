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

## Second review — lifecycle, identity and review sufficiency

**Input:** user-supplied review beginning “Overall verdict: The revision is materially better,” sections 1–17 and final priority list. Reviewed against the consolidated package at `be8ab9395381912df7ee3196a489490eb4fd464f` and relevant registry code. This assessment supplements the first review above; its praise and P1/P2 labels do not constitute adoption, runtime verification or measured risk rankings.

| Review section | Disposition | Result |
|---|---|---|
| §§1–6, 14–16: native evidence, direct claims, dimensional/selection boundary, deferred enrichment and documentation | Agree; mostly confirms existing decisions | Retain the architecture and M1A/M1B/M4 boundaries |
| §7: distinguish added report coverage from correction | Agree; the prior replacement prescription was unnecessary | New reports get disjoint accepted roots; old valid roots remain accepted. Replace/revoke is for actual correction or explicit withdrawal |
| §8: explicit hash scheme | Agree | ContractRef and new claim/snapshot/export identity include `definition_hash_scheme`; preserve exact legacy verification |
| §9: small versioned review profile | Agree with bounded interpretation | One Git-authored exact-review checklist with pinned content and results; no profile database or workflow engine |
| §10: scope conjunction and redundant dates | Agree | All scope/conditions combine with AND; listed reports normally have NULL interval bounds |
| §11: remove empty dependency interface; defer separate runtime roles | Agree | No publication stub in M2. Retain DB history constraints/triggers; grants wait for an operational need |
| §12: selector first, publication lifecycle later | Agree on sequencing; partially disagree on deferring all correction support | Benchmark/query first, then export. M3 retains a minimal explicit status/notice path; automatic propagation/indexing is deferred |
| §13: accounting basis and sign semantics | Agree | Initial `us_gaap` / `reported` meanings defined; M0 freezes each contract's economic direction and reversal examples. No implicit numeric transformation |
| §17 and overall endorsement | Incorporate supported arguments, not the approval verdict | M0 adoption, real-data review and implementation tests remain outstanding |

### Coverage expansion and what the current evaluator actually does

The old prescription withdrew a valid {2024, 2025} claim merely to add 2026. Disjoint roots state the two review events more faithfully and preserve historical knowledge without extra lifecycle operations. They also avoid false correction notices on previously valid exports. The target conflict policy already permits *proven disjointness*, so the design change is small.

However, the review's statement that the evaluator “already understands finite report sets” is true only of the proposed design. Current [interval.py](../../src/edgar/registry/interval.py) and [service.py](../../src/edgar/registry/service.py) check issuer/global scope and inclusive report-period intervals. M2 must implement report-condition evaluation and disjointness tests; this cannot be treated as existing functionality. Tests now explicitly require preserving earlier accepted roots, rejecting actual intersections and preventing future coverage from entering semantic-as-of queries.

Replacement remains appropriate for an error or intentional withdrawal of authority, with a truthful reason. A contract retirement is not evidence that every old financial assertion was false. General scope compaction/reusable rules remain F1 decisions; they are not smuggled into routine annual review.

### Hash versioning without rewriting legacy claims

Current [hashing.py](../../src/edgar/registry/hashing.py) fixes semantic fields and canonical JSON behavior but has no explicit scheme field. Adding basis/sign changes the hash contract even though SHA-256 remains the digest algorithm. Explicit `metric-v1` and `metric-v2` remove the ambiguity; the [mapping contract](mapping-and-review.md#explicit-definition-hash-schemes) specifies the payload and migration boundary.

The important qualification is not to update old immutable claims with inferred meaning. M2 leaves original rows unchanged, with a documented `0002_registry` legacy decoding for the new nullable scheme field. Verified legacy exports/snapshots state `metric-v1` explicitly; unknown-origin imports cannot guess from dates or content shape. New roots and identity comparisons use explicit schemes. This is a fixed supported contract pair, not a general serialization/versioning framework.

### A checklist must not turn unknown relevance into permission

The profile makes review obligations inspectable, but the suggested “assess” category is insufficient on its own: if relevance is unknown, an agent cannot declare it irrelevant to pass the check. The [minimum profile](mapping-and-review.md#minimum-exact-review-profile) separates capability state from relevance, requires positive definition/disclosure evidence, and records inspection scope, truncation, search limits and contrary evidence. Case requirements may strengthen the base profile, never waive it because SQL lacks a table.

Profile identity belongs to review evidence, not the economic hash or a second decision ledger. A changed profile does not automatically revoke old knowledge. Evidence-only reaffirmation of an unchanged accepted claim is deliberately deferred until a future profile must apply retrospectively; its transition must be designed before such a policy activates. This avoids quietly adding an accepted-to-accepted lifecycle operation to M2 merely because profiles are versioned.

### Operational simplification has a small correctness floor

There are no publications to inspect in M2, so the empty dependency interface is deleted from that phase. The [local Compose setup](../../compose.yaml) configures one `edgar` PostgreSQL user, and current migration/runtime URLs do not establish separate writer roles. Database mutation-rejection triggers and claim constraints meet the immediate trusted-local need. They are protection against ordinary mistakes, not protection from an owner able to drop triggers; shared or untrusted writers would trigger privilege separation.

The selector should be proven before export, as the review suggests. Nevertheless, deferring *all* publication status/correction handling until after a mistake creates an avoidable gap: the first export can already contain a claim later revoked. M3 therefore includes only a bounded manifest scan, status check and explicit append-only notice command alongside immutable exports. No background propagation, dependency index, notification delivery or publication service is required. A failed notice write cannot conceal a revocation when the ledger is available; without current knowledge, status must be reported unavailable. This is the narrow disagreement with §12, not a requirement for a mature publication lifecycle.

### Economic fields have bounded meanings

For the initial direct-reported subset, `accounting_basis=us_gaap` is evidenced reporting basis, not an inference from a tag or a free-text ontology. `sign_convention=reported` preserves Arelle's resolved filed number; it neither reverses an expense sign nor takes an absolute value. Each contract still needs reviewed economic direction and legitimate negative examples. A sign interpretation that does not satisfy that contract blocks publication; a negative amount is not automatically incompatible. Other accounting bases and sign transformations remain separate future decisions.

These changes tighten the recommendation without claiming it is now frozen. No financial benchmark, inheritance trial, runtime migration, or new live mapping was executed for this review.
