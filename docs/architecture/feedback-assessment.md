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

## Third review — contract versions, coverage and qualification

**Input:** user-supplied review beginning “Overall assessment: This revision is substantially stronger again,” sections 1–13. Compared with package baseline `2bd8f3978075470da1d105107cbedc104f0f75ca` and the current registry conflict implementation. This is another critical design review, not adoption or implementation validation.

| Feedback | Disposition and change |
|---|---|
| §1: stale accepted claims obstruct reviewed contract upgrades | Agree. Same-key, different ContractRefs may coexist accepted after independent review. Prior claims and contract differences remain mandatory evidence; current acceptance and one-version-per-key requests stay explicit |
| §2: later unreviewed filing is not an assessed absence | Agree. M4 adds filing-by-exact-slot coverage before mapping filters; unknown later coverage blocks latest, and unknown earlier coverage blocks first |
| §3: selector-facing conclusions must be typed | Agree, with explicit scope and ownership. Qualification records accounting basis, consolidated entity basis and sign compatibility, bound to receipt/ContractRef/occurrences within the existing packet format |
| §4: publication currentness differs from validity | Agree on the distinction; do not certify financial validity from passing hashes or an absence of notices. Use independent integrity, known-issue review status and semantic currency |
| §5: notices must allow non-mapping defects | Agree. Generic reason/cause references cover contracts, extraction, code, assessments and artifacts; automatic discovery remains bounded to existing checks and explicit notices |
| §§6–12: retain explicit hash schemes, small review profile, sign semantics, M2 scope and M3 ordering | Agree; no additional frameworks or generalized profile hierarchy |
| §13 and final endorsement | Incorporate the concrete issues, not the readiness verdict. M0 must still adopt the recommendation and verify the bounded economics/corpus |

### Version coexistence needs a narrow exception, not a compatibility system

The criticism identifies a real tension. Current `_conflict_if_needed` in [service.py](../../src/edgar/registry/service.py) rejects overlapping accepted exact claims for one source concept without comparing target versions. Carrying that rule unchanged into M2 would require rejecting sound older knowledge merely to accept a new contract.

The revised [conflict table](mapping-and-review.md#conflicts-and-safe-correction) permits coexistence for different versions of the **same metric key**. The new version must be independently reviewed; the exception asserts neither equivalence nor inheritance between versions. An actual discovered error still requires explicit correction. Original version-specific history and publications remain explainable.

I do not adopt a blanket “different ContractRefs cannot conflict” rule, nor a new mechanism for classifying all pairs of current meanings as compatible. Different keys remain conservatively conflicting under overlapping scope; same-reference duplicate roots also conflict. This preserves correctness without introducing an ontology or compatibility matrix. Query-time checks use the requested knowledge snapshot rather than treating today's registry as historical truth. The Phase 2C rule stays implemented until the explicitly adopted M2 change.

### Temporal absence must be evaluated for the exact observation slot

The principle in §2 is sound, but its year-to-year example needs qualification: a 2023 value cannot fill a 2024 slot at all. The actual fallback problem arises when a later filing might contain a revised **2023 comparative** for the same requested period, unit, entity and contract.

M4 now starts from the declared filing corpus/catalog, including failed or missing extraction, rather than discovering filings through successful mappings. A later unresolved extension cannot disappear through an inner join and become “no claim.” Only a pinned assessment of absence or a sound explicit exclusion permits skipping that filing. A tied cohort containing both a valid claim and unknown coverage cannot be presented as unambiguously latest. The same reasoning applies in reverse to first-reported queries. Negative review knowledge is subject to the semantic cutoff too; a later review cannot retroactively establish that a filing was known to be irrelevant.

These are M4 query/assessment rules, not a prerequisite for completing a market-wide coverage ledger before M3. Completeness is always relative to the named corpus and inspected slot. The [target](target-architecture.md#time-amendments-and-restatements) specifies the states and scan behavior; no coverage table or automatic semantic resolver is added.

### Typed review results must not become universal mapping assertions

The missing deterministic boundary is real: consolidated scope, accounting basis and economic sign cannot be read from free-form rationale. The [qualification packet](mapping-and-review.md#typed-conclusions-for-observation-qualification) now carries explicit states, values, evidence pins and exact occurrence coverage. An entity identifier is not proof of consolidation; one reviewed statement occurrence does not qualify every fact in a report.

A reusable standard-concept mapping cannot absorb every future issuer's report-specific qualification without confusing the two concerns again. The same packet format therefore supports explicitly supplied reviewed JSON inputs as well as existing mapping evidence. Their authored contents are durable knowledge, requests pin them and publications retain snapshots. No new table, service, general scope language or evidence-only mapping transition is required. Draft/model-only packets are ineligible, conflicting inputs fail, and strict historical use requires recording evidence rather than a manually entered review date. This is an explicit ownership boundary for already-required judgments, not a second concept-mapping ledger.

### “No known issue” is more honest than an automatic “valid” flag

I agree that an old contract can remain defensible without being current. I qualify the suggested `valid|withdrawn|unknown` vocabulary: neither a live ledger check nor a verified checksum proves that no economic, parser or selection error exists. The model instead reports `integrity`, `review_status` and `semantic_currency` independently, with checked scope/time. `no_known_issue` is a limited diagnostic, not a correctness certificate.

Notices can identify a publication-specific problem caused by a mapping, contract, parser, selector, manual assessment or source artifact. They reuse existing typed references; there is no causal graph or promise to automatically find every export affected by every code revision. A new parser or contract version alone is not evidence of an error. Explicit notices and the bounded mapping scan remain sufficient for the first local product.

The test plan now includes these distinctions as implementation acceptance cases. No runtime tests, financial benchmarks, ledger migrations or source re-extractions were performed during this documentation revision.

## Fourth review — assessment authority and stable metric keys

**Input:** user-supplied review beginning “Overall verdict: The updated plans are now very close to implementation-ready,” sections 1–10 and final recommendations. Reviewed against `dbf87bfcffcfcd0590ab2097f02789fbf4582013`. The two substantive points hold; the preferred implementation of the first is not necessary yet.

| Feedback | Disposition |
|---|---|
| §5: standalone packets are authored knowledge outside the mapping database | Agree. README, target, data model and D6 now name Git-authored contracts, database-governed mapping decisions, and curator-approved assessment inputs explicitly |
| §5: undefined recording receipt leaves historical availability underspecified | Agree. Remove that option; strict M4 requires the exact reviewed packet in an accepted mapping revision or previously completed immutable publication by the cutoff |
| §5 preferred `registry.assessment_record` | Defer. Select the review's leaner alternative first; F17 records the evidence needed to justify dedicated recording later |
| §6: distinguish a contract revision from a new metric key | Agree. M0 records intended quantity, changed boundaries and the key decision for each initial metric |
| §§1–4, 7–10: retain the principal architecture and bounded review/selection design | Agree. No further ontology, transformation platform, generic workflow or parser redesign is introduced |
| “Freeze and implement” and readiness ratings | Not adoption or empirical validation. Keep the recommendation stable unless concrete evidence triggers reconsideration; implementation remains subject to M0 and the user's scope |

### Acknowledging ownership is better than claiming two universal authorities

Qualification and negative-coverage conclusions are real human judgments. Calling them request inputs does not make them disposable parser output. Their approved content is durable, must be backed up and is snapshotted in publications. The revised ownership description makes that explicit without forcing unrelated report qualification into the concept-mapping ledger. A packet cannot override mapping status or redefine a contract, and a file's presence, digest or claimed review flag does not constitute curator approval.

The existing [registry service](../../src/edgar/registry/service.py) stamps mapping revisions with application UTC time. No equivalent implemented standalone-assessment recording path exists. The earlier phrase “local recording receipt” therefore implied a capability the plan had not defined. The [revised timing rule](mapping-and-review.md#typed-conclusions-for-observation-qualification) now enumerates only two permitted records: an accepted revision containing the exact reviewed content, or an earlier completed publication that used it as reviewed input. Check the containing record, content and time; do not use a draft snapshot, bare digest, manually entered date, file metadata or Git author date. These remain trusted-local audit semantics, not tamper-proof timestamp certification.

M3 can use explicitly pinned approved files without a historical claim. M4 rejects an unanchored packet with `knowledge_time_unknown`, rather than pretending it was known earlier. A changed packet needs its own qualifying record. A new export cannot use itself to satisfy an earlier cutoff. Unknown legacy recording provenance remains unknown. Qualification and negative coverage follow the same rule.

### Why not add the proposed recording table now?

An append-only digest/time record is a credible future option, not intrinsically excessive. But it also needs retained content, provenance, correction behavior and a tested relationship to request selection. There is not yet a measured case showing that the limited prior-revision/publication route obstructs this project's historical research workflow.

The chosen restriction closes the correctness gap while keeping M3 and initial M4 smaller. F17 is activated by named strict historical queries materially blocked by missing anchors and evidence of the resulting workload. At that point, decide a small recording contract and migration. Do not create fake mappings or a generic event system simply to obtain timestamps. The trade-off—less convenient historical assessment reuse—is stated rather than hidden.

### Canonical-key continuity is economic governance

The review's coexistence test is useful: if both quantities are legitimate simultaneous requests, separate keys are usually appropriate. Cash including restricted cash and cash excluding it illustrate different measurements. Formalizing the evidenced original intent of one quantity may instead retain the key and create a new ContractRef.

The [governance rule](mapping-and-review.md#stable-metric-keys-versus-contract-revisions) adds two qualifications. First, the test is a review aid, not an automatic algorithm: ambiguous historical prose does not prove a precise original intention. Second, key reuse must not be chosen merely to bypass cross-key conflict checks. Preserve old definitions as written; record the M0 rationale and review mappings independently. Example names in the feedback are not adopted keys, and no current YAML definition is changed by this documentation task.

Further infrastructure remains evidence-triggered. The next meaningful validation is the bounded corpus, actual local ledger and initial contract review described in M0—not another confidence rating of the documents. This turn changes plans only.
