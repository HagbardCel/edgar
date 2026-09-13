# Target architecture

**Status:** recommended target, not implemented. [Migration](migration-plan.md) defines staged delivery. Persistent grains are specified in [data model](data-model.md); [decisions](decisions.md) compares alternatives.

## Derivation from the product

The product answers three different questions: what was reported, what economic claim we can defend about it, and which reported value answers a particular analytical question. These require different identities but not separate services.

A minimal useful query is:

```text
issuer CIK
+ canonical measurement contract
+ exact economic period
+ entity/consolidation scope
+ dimensional slice
+ unit
+ filing/publication policy
→ value with evidence, or an explicit reason no value can be selected
```

Success means a researcher can compare the requested quantities, inspect every source occurrence used, and reproduce the selection conditions. Correct missing values are a product result. Mapping coverage alone is not success.

The first release serves US-GAAP operating-company reported metrics for a bounded filing set. Banks and other materially different revenue models remain visible in source inspection but do not inherit operating-company revenue mappings. Initial units are reported units, with no currency translation. Original report contexts define periods; neither calendar labels nor annualization manufacture observations.

## One application, three responsibilities

```mermaid
flowchart TD
    SEC[SEC submissions and artifacts] --> Fetch[Controlled acquisition]
    Fetch --> Bundle[Immutable bytes and FilingBundle]
    Bundle --> Arelle[Isolated Arelle and document parsing]
    Arelle --> Evidence[Queryable source evidence]
    Evidence --> Inspect[Concept and fact inspection]
    Inspect --> Review[Human review with optional AI proposals]
    Contracts[Git measurement contracts] --> Review
    Review --> Ledger[Durable semantic assertions]
    Evidence --> Query[Deterministic financial query]
    Ledger --> Query
    Contracts --> Query
    Policy[Period, scope and publication policy] --> Query
    Query --> Result[Values or explicit missing and conflict results]
    Result --> Export[Immutable export with lineage manifest]
```

1. **Evidence:** bytes plus a replaceable relational index of the filing's XBRL and document structure.
2. **Knowledge:** Git-authored canonical contracts, database-governed mapping decisions, and explicitly selected curator-approved qualification/coverage packets. Standalone packets are durable request inputs; their historical eligibility is limited to exact reviewed content already captured in an accepted mapping revision or completed publication by the cutoff.
3. **Queries/publications:** application of that knowledge and a declared selection policy to produce economic observations.

Keep `source` and `registry` as practical ownership namespaces. Add an `analysis` schema only for useful SQL views; initial results and exports need no durable observation tables. Names do not define the architecture. No `reference`, `semantic`, and `analytics` databases or services are required.

The six conceptual operations remain distinguishable:

| Question | Representation | Why the boundary matters |
|---|---|---|
| What did the filer report? | Artifacts and fact occurrences | No interpretation overwrites evidence |
| What does XBRL declare? | Report-scoped declarations, contexts, resources, networks | Filed DTS differs from application economic claims |
| What have we asserted? | Contracts, mapping revisions and explicitly pinned reviewed assessment inputs | Human knowledge is independently durable |
| Which assertions apply? | Query-time mapping application and predicate results | Acceptance alone does not qualify every fact |
| Which observation answers the question? | Candidate qualification and selection result | Many mapped facts are not the requested period/scope |
| What is delivered for analysis? | Long-form result and immutable publication | Dataset policy and history are explicit |

These are inspectable stages in one query, not six materialized copies of the same fact.

## XBRL-native where XBRL already provides the model

Use exact expanded QNames for source concept identity. Prefixes are display syntax; namespaces are not retrieval URLs and must not undergo HTTP URL canonicalization. Namespace releases remain distinct identities. A QName identifies a concept; a report-scoped declaration records how the loaded DTS declares it. Report observations must never overwrite global concept metadata. The native fact/context/unit/relationship concepts follow the [XBRL building blocks](https://specifications.xbrl.org/xbrl-essentials.html).

Use the OIM's aspect-oriented view as a guide to the analytical API: concept, entity, period, unit, language, and taxonomy dimensions describe a fact. OIM is not a replacement for the provenance-rich source store; the application also needs the original occurrence and filed declaration/network evidence. [Open Information Model](https://www.xbrl.org/Specification/oim/REC-2021-10-13/oim-REC-2021-10-13.html).

Arelle owns loading, QName resolution, DTS discovery, transformations, resolved values, and effective XBRL relationships. The adapter selects and serializes information the application needs, attaches source locations, and fails explicitly on unrepresentable mandatory information. It must not implement its own XBRL validation engine. Arelle exposes [declaration/relationship objects](https://arelle.readthedocs.io/en/latest/apidocs/arelle/arelle.ModelDtsObject.html) and [fact/context/dimension objects](https://arelle.readthedocs.io/en/latest/apidocs/arelle/arelle.ModelInstanceObject.html).

The target SQL surface is a faithful **supported subset** of XBRL, not a full serialization of ModelXbrl. It preserves all supported item occurrences, their aspects, useful DTS resources, and effective networks. Raw arc prohibition/priority history and uncommon structures remain available in immutable artifacts. Unsupported structures get explicit diagnostics and publication gates; silently treating an unsupported context as empty is forbidden.

Delivery separates preservation, inspection and indexing. M1A establishes receipts, occurrence/report integrity, complete keys for already-supported networks and a bounded inspector. Dedicated role/arcrole/footnote tables and typed-domain enrichment are case-triggered M1B, not prerequisites for every annual query. Relevant source evidence can first be delivered as a pinned packet from the bundle through a narrow offline reader. Evidence unavailable in SQL is not necessarily absent from the filing: the inspector distinguishes available, assessed-absent, not-assessed and unsupported. Unassessed relevance blocks the affected publication case. Existing fatal handling of unsupported non-dimensional contexts remains until a specific M1B preservation change is justified.

Application-specific entities are the measurement contract, semantic assertion/review, analytical request, selection explanation, publication manifest, and later formula definition. Do not add a second generic “filed economic observation” table between facts and queries.

## Dimensions and observation identity

A source dimension stays an exact dimension QName plus an explicit member QName or namespace-complete typed member XML, under a context and segment/scenario location. Preserve filed occurrences even if invalid. Default members are DTS semantics, not fabricated context rows. Effective aspect comparison may consult Arelle's dimensional interpretation while retaining the filed form. [XBRL Dimensions](https://specifications.xbrl.org/work-product-index-group-dimensions-dimensions.html).

Typed-member XML hashes provide integrity, not semantic equivalence. Prefix changes, namespace use inside content, and schema-defined typed equality require care. Initially, compare conservatively within the supported profile; refuse to merge uncertain typed values. Do not build a universal canonical member dictionary.

An analytical observation slot is:

```text
(issuer/entity identity,
 canonical key + definition hash scheme + definition hash,
 exact period,
 economic entity/consolidation basis,
 full dimensional slice,
 unit,
 reporting basis required by the contract)
```

A **reported assertion about that slot** adds the filing/report and supporting source occurrences. A **selected result** adds the query's publication policy and knowledge cutoffs. A source occurrence ID is not the slot identity; the same slot can legitimately have multiple filed assertions over time.

Consolidated revenue and Europe revenue can share the revenue concept but occupy different slots. Duration alone does not make a fact annual: January, a quarter, YTD, and FY are different periods. The source concept is not replicated as `annual_revenue`, `quarterly_revenue`, and `europe_revenue`.

Some distinctions belong inside the concept contract: gross/net, GAAP/adjusted, including/excluding goodwill, income attributable to parent/including noncontrolling interests. They cannot all be recovered from dimensions. Do not invent a generic dimension to hide an undefined metric boundary.

## Additional meaning without an ontology

Use a lightweight canonical registry with prose measurement definitions, machine-checkable compatibility fields, and cited taxonomy/document evidence. A reported metric can reference several exact standard concept QNames as evidence; that does not make all of them equivalent. Extension mappings target the reviewed contract directly.

A relational mapping graph is already a knowledge graph in the ordinary sense: source concepts, declarations, contracts, decisions, and evidence are connected. Neither graph storage nor OWL reasoning follows from that fact. Human/agent inspectors can emit a small neighborhood graph from SQL when useful.

Keep relationship purposes distinct:

| Relationship | Representation / consequence |
|---|---|
| Exact/broader/narrower/related source meaning | Reviewed mapping assertion; only exact can feed strict values |
| Alternative names | Contract aliases for search; no mapping inference |
| Product/service specialization of revenue | Optional reviewed canonical hierarchy when navigation needs it; not a sum rule |
| Accounting subtotal/component | Filed calculation network as evidence; an executable formula only after separate approval |
| Dimension/member hierarchy | Native DTS definition network; not a canonical metric hierarchy |
| Derived-from | Versioned formula and input lineage when derived values are introduced |
| Taxonomy replacement/deprecation | Reference evidence; not automatic equivalence |

Do not add all possible relationship tables now. The first release needs the assertion relation and existing source networks. Defer canonical hierarchy storage until there is a concrete navigation/query consumer.

## Mapping application is a transparent query

For every fact of a queried source concept:

1. Resolve the named semantic revision/snapshot and scheme-qualified ContractRef, including the frozen exact-review assessment. Candidates, revoked decisions, mismatched scheme/digest, and missing required review are not trusted input.
2. Evaluate its explicit issuer/report/declaration guards and any supported aspect conditions. Unknown or unsupported conditions do not match.
3. Check basic target compatibility (numeric kind, instant/duration, unit dimension); keep all original aspects and values.
4. Return application records containing the source occurrence, assertion revision, canonical definition, condition outcomes, and applicability state.

“Mapped fact” is this result, not a second permanent fact table and not yet a statement value. A non-exact assertion is valuable inspectable knowledge but cannot publish an exact canonical value. New filings outside a reviewed issuer-report scope generate review work, not silent extrapolation. Details are in [mapping and review](mapping-and-review.md).

## Deterministic selection, including the cases where there is no answer

Implement one typed `FinancialRequest` and one selector with reason-bearing stages. SQL retrieves bounded rows and joins; typed Python performs the small policy decisions. Do not implement the same policy twice in SQL and Python.

The first selection profile is `reported-annual-v1`:

1. The caller supplies an explicit filing accession, issuer, metric, exact start/end or instant, reported currency/unit, and `consolidated` scope. A convenience FY request is allowed only after an unambiguous filing-specific fiscal period has been established from filed evidence or a reviewed request manifest. No 365-day/year-end heuristic alone.
2. Require successful compatible extraction, relevant source locations, and the reviewed current contract. A context entity must agree with the registrant using its filed identifier scheme; a different entity is not relabeled with the filing's CIK.
3. Require applicable accepted exact mapping, valid non-nil numeric value, correct unit and period. Negative values are valid where the contract allows them. Preserve filed sign; never flip an expense from `balance=debit` or a calculation weight. For M3, `sign_convention=reported` is a preservation rule, not conversion; check the reviewed economic direction and evidenced `accounting_basis=us_gaap` contract. Unresolved/incompatible sign meaning blocks the slot, while a legitimate negative loss/benefit remains negative.
4. For this initial profile, require no filed dimensions, no opaque non-dimensional context qualifiers, and positive evidence that the metric/statement scope represents the requested reporting entity. Dimension absence alone is not proof of consolidation. Consume the typed, occurrence-scoped `qualification.entity_basis` conclusion in the reviewed packet; `context_entity` and reviewer prose cannot substitute for it. Require matching accounting/sign conclusions and receipt/ContractRef pins as specified in mapping and review; ambiguous entity/scope fails closed. Explicit consolidated members are initially unsupported, not stripped.
5. Preserve all qualifying occurrences. Group only demonstrably equivalent aspects; then compare values. Initially allow duplicate support only for identical Decimal value **and identical accuracy metadata**. Differing precision/decimals or merely rounding-consistent values return `accuracy_review_required`; later support may use Arelle's duplicate classification without deleting occurrences.
6. If all qualified support describes one identical value/accuracy group, return that value with **all** support occurrences. Multiple concepts mapped to the same contract can be co-support, but equal numbers alone do not prove their aspects/basis are identical. Different qualified values return `conflicting_values`; do not pick the first, largest, most precise, or standard-tagged fact.
7. A footnote or diagnostic affecting the measurement must be available for review, either through supported SQL evidence or a pinned packet. Report-level omission counts alone do not prove irrelevance to a fact. If scope/relevance cannot be assessed, return `evidence_not_assessed`; a known unsupported semantic condition yields `unsupported_semantics`. Neither publishes a trusted number. Building a complete relational footnote graph is not required when the relied-on association and resource are already inspectable and pinned.

The profile deliberately excludes dimensional totals, FX conversion, segment summation, annualization, quarter-by-subtraction, and accounting reconstruction. These are separate future products. Strictness trades coverage for a usable, defensible first result.

The result is long-form, one row per requested slot: value (Decimal string in JSON/CSV), unit, period, definition hash scheme/digest, filing/report, scope, supporting occurrence pins, and state. A missing result has a reason and counts at each filtering stage; it is never silently zero or absent from the response. Reasons include no filing, no extraction, unsupported source structure, unassessed required evidence, required review missing, unmapped, candidate only, stale definition, guard not met, non-exact only, wrong entity/period/unit/slice, nil, invalid value, accuracy review, conflicting values, and unknown availability. Multiple reasons can be reported with a primary earliest blocking stage.

## Time, amendments, and restatements

There are four different clocks:

| Clock | Meaning | Policy |
|---|---|---|
| Economic period | When the measured activity/balance applies | Context lexical values preserved; analytical date boundaries derived separately |
| Filing availability | When this submission became public | Use sourced SEC acceptance timestamp as the declared availability proxy; unknown stays unknown |
| Local availability | When this installation obtained evidence | Acquisition receipt; needed for “what could this installation have used?” |
| Semantic knowledge | When a decision became accepted/revoked locally | Immutable ledger revisions; cannot be backdated to the economic period |

`extracted_at` is none of these economic/public knowledge clocks. For date-only XBRL instant/end values, distinguish source lexical date from the XBRL boundary interpretation and an analytical inclusive reporting date. Do not make timezone-less values UTC instants by fiat.

M3 exposes per-filing assertions only. M4 introduces named policies:

- **`as-filed(accession)`**: use just that filing's assertions, including explicitly requested comparative periods.
- **`latest-reported-as-of(T)`**: among assertions for the same slot available by T, consider the latest acceptance-time cohort. Within that cohort, run qualification and conflict checks. If the latest report contains a relevant but invalid/conflicting claim, surface that state; do not silently fall back to a prettier older value. Only a later filing assessed to contain no relevant claim for this exact slot permits fallback; unmapped or unreviewed coverage is unknown, not absence.
- **`first-reported`**: choose the earliest available reporting cohort for that slot, then apply the same conflict rules. “First” is relative to an explicitly enumerated corpus, not all SEC history unless coverage proves it.

Before choosing a time cohort, build a **filing × exact requested slot** coverage result over the declared issuer/form/corpus and time cutoffs, including catalogued filings with failed/missing extraction. Never discover this set solely by joining accepted mappings. The slot includes the exact economic period: a 2023 amount cannot fill a 2024 slot. A 2024 filing can instead change a 2023 slot by reporting a 2023 comparative.

| Coverage result | Temporal treatment |
|---|---|
| `assessed_no_relevant_claim` | Advance past this filing only with a pinned, scoped negative assessment or a sound explicit exclusion; a zero mapped-row count is insufficient |
| `unmapped_or_unreviewed` | Stop with `coverage_unknown` / `review_required`, including missing extraction, unresolved extension drift or insufficient inspection |
| `relevant_claim_invalid` | Surface invalid/unsupported qualification; do not fall back |
| `relevant_claim_conflicting` | Surface conflict; do not fall back |
| `valid_claim` | Apply the normal slot qualification/co-support rules within the selected cohort |

Scan acceptance-time cohorts newest-to-oldest for latest and oldest-to-newest for first. Skip a cohort only if every potential filing is assessed irrelevant for the slot. Unknown coverage in a cohort blocks selecting another member's valid value as unambiguously latest/first; invalid/conflicting relevant claims also block a successful value. Unknown earlier cohorts therefore prevent an unsupported “first” claim. `as-filed` assesses only its named filing. Conservative bounds may exclude filings only under an explicit justified policy; lack of a known mapped concept is never such a bound.

M4 uses a `slot_coverage` section of the same reviewed assessment packet for human negative conclusions, bound to report/receipt, ContractRef, exact slot, search scope/method, evidence pins and limits. Positive/invalid/conflict states derive from inspected source/application results; absent or incomplete assessment remains unknown. No completeness claim across all issuers or a new coverage table. Corrections, packet hashes and semantic/local availability follow the qualification-packet rules. A future negative assessment cannot be used to skip an earlier unknown filing in a strict semantic-as-of query. Standalone packets without a qualifying accepted revision or prior completed publication return `knowledge_time_unknown`; authored dates and an undefined local receipt are not substitutes. Publications retain the skipped and blocking cohort assessments as well as selected support.

A latest reported comparative is not necessarily a restatement: it can be a reclassification or another basis change. No automatic filing-wide supersession. Store an evidence-backed `amends` edge when justified, but replacement occurs at observation scope. Partial amendments do not erase unchanged original observations. A formal `restates` classification requires evidence of affected metrics/periods/basis and is deferred until needed.

Separate two historical questions in the API:

```text
public_as_of=T, semantic_snapshot=current
    = historical filings interpreted with today's reviewed knowledge

public_as_of=T, semantic_as_of=S, acquired_as_of=A (optional)
    = constrained public, semantic, and optionally local knowledge
```

The first is retrospective normalization, not a claim that today's mapping existed at T. A semantic-as-of request must also specify the ContractRef for each metric (or a saved semantic/publication manifest containing those refs). Do not infer the historically active YAML contract from Git author dates or today's mirror. Require evidence that the contract content was recorded by S, such as a retained decision revision or publication. An explicitly requested retired contract is a historical meaning, not the current metric definition.

Select each mapping chain's latest revision within S, not today's tip filtered afterward, and require its target scheme and hash to match the requested ContractRef. Unknown historical contract content blocks the historical query. Equal timestamps are disambiguated by chain/revision order, not by treating independent conflicting decisions as interchangeable. A simple semantic cutoff does not reconstruct an unrecorded historical deployment: the query uses a declared parser/selector implementation over constrained evidence. Exact prior system outputs require a saved publication manifest. Automatic reconstruction of which YAML version was deployed at every past instant is deliberately not promised, so no contract-activation event framework is required.

A dataset manifest pins all clocks/policies, the examined corpus, and code/semantic inputs. No single `known_at` column can honestly replace them. Later trading datasets must additionally define dissemination/tradability assumptions, securities, prices, and delistings; these are outside this release.

## Durability and lineage

Keep raw bundles, Git contracts, mapping history, and exported publications. Current extraction tables, affected-fact queries, evidence previews, application results, and candidate qualification are regenerable. A result's lineage is:

```text
publication + row key + request/policy
 → canonical contract snapshot + mapping revision(s) + evidence
 → selected/supporting source occurrences with preserved aspect/value snapshot
 → accession + report input + bundle descriptor pin
 → artifact relative path + SHA-256 + locator
 → original bytes (and continuation/footnote/taxonomy evidence)
```

Exports retain compact snapshots of the occurrences actually used and the complete selection outcome. They do not embed every fact affected by a mapping. This allows current parser rows to be replaced without breaking old published lineage. A pointer to a bigint source fact is a live convenience only. An export can still be inspected if its parser environment is unavailable; exact replay additionally requires the saved code/lockfile and bundle inventory. Inspection and executable replay are different guarantees.

Publish from a consistent DB read snapshot and a single loaded contract snapshot; verify YAML/mirror coherence. Write output and manifest to a temporary directory, hash contents, then publish atomically through storage utilities. Prove the selector/benchmark before the export work. M3 includes a bounded explicit manifest scan and separate notice command for erroneous publications; automatic propagation and a dependency index are deferred. Revoke an erroneous mapping by appending history, recompute new results, and record withdrawal/correction in a notice referencing the publication, whether the cause is a mapping, contract, extraction, selector, manual review or artifact defect. Status/explain checks the current ledger and available notices, reporting status unavailable if those cannot be inspected. Ledger revocation and filesystem notice writes are not a distributed transaction; a failed notice write cannot hide a revoked input when the ledger is available. Byte integrity, known problems and semantic currentness are separate status fields (see data model); a contract upgrade alone is not withdrawal. Never edit the old dataset bytes or retroactively pretend they were correct.

## Growth without replacing the foundations

Add metrics by writing contracts and reviewed assertions. Add dimensions first as preserved query slices, then reviewed canonical member associations only where comparison needs them. Add derivations as formulas over explicit input observations. Add official taxonomy packages as pinned evidence attachments if the filing DTS lacks required material; no fake filing should own them. Add a relational package index only once repeated queries justify it.

When data volume makes bounded live queries too slow, materialize the same application/selection contracts with measured invalidation requirements. If a substantial dependency graph emerges, reassess SQLMesh/dbt. Neither change alters source identity, assertion meaning, or publication lineage. External datasets later enter with their own source identities and availability clocks; they do not overwrite filed facts.
