# Semantic contracts, mapping, and review

**Status:** recommended. M2 implements the bounded form below; M5 features remain gated. No examples in this document constitute an accepted financial mapping.

## Define the quantity before mapping the label

The canonical registry defines economically comparable measurements, not an exhaustive accounting ontology. Keep `key`, definition, includes/excludes, period type and unit dimension. Add explicit `accounting_basis` and `sign_convention` to the initial contracts; separate economic constraints from display grouping. A statement category helps navigation but must not permanently constrain all possible monetary/shares/ratio metrics through one hardcoded matrix.

The first reviewed subset should be revenue, operating income, R&D, net income attributable to parent, total assets, cash excluding restricted cash, operating cash flow, and cash purchases of PP&E. Use existing keys only when the intended boundary can be stated precisely; broad `capital_expenditure` may need a more specific successor key. Unused existing definitions are retained but not advertised as reviewed publication contracts.

Write inclusion/exclusion boundaries that cannot change with how an issuer labels a line. For example, cash excluding restricted cash must reject a combined cash/restricted-cash line even when the issuer presents no separate split. Product revenue is narrower than total revenue, not an alternate label for the same total. A missing R&D disclosure is not zero. Accounting-basis compatibility can be a reviewed report assertion supported by DEI/disclosure evidence; neither CIK nor a us-gaap namespace alone proves it.

Contract prose is a deliberate application judgment. Cite authoritative taxonomy definitions instead of reproducing an entire taxonomy, but specify the differences the API promises to preserve. A contract revision affecting economics changes the hash and requires affected mappings to be reviewed again.

## Assertion identity and relationships

A claim is:

```text
exact source QName
→ canonical key + reviewed definition hash
with relation + issuer/report/declaration scope + semantic aspect conditions
because rationale + pinned supporting/opposing evidence
```

The immutable claim fields are copied through a revision chain. Status, actor, time, and evidence/rationale are decision-revision content. A new source/target/relation/condition creates a new root, with an explicit correction link if it replaces an earlier claim. Never reuse a revision ID for a changed case.

Use the existing four relations with a fixed direction:

| Relation | Meaning: source compared with target under conditions | Strict publication |
|---|---|---|
| `exact` | Same defined measurement; retained aspects still qualify each observation | Eligible, subject to fact and selection checks |
| `narrower` | Source excludes part of the target's economic measurement boundary | Never as target total |
| `broader` | Source includes additional economic content | Never as target total |
| `related` | Relevant association without an exact/subset/superset claim | Never as an exact value |

Scope is not a relation: “issuer exact” is `exact` plus issuer scope. Contextual equivalence is `exact` plus explicit conditions. Confidence is not a relation or permission to publish. `candidate`, `accepted`, `rejected` are review states; rejection may mean insufficient evidence, withdrawal, or incompatible economics. Record a reason code instead of inferring all rejection means permanent semantic incompatibility. Terminal rejection applies to that claim chain; new evidence may motivate a linked new root.

No transitive mapping inference is enabled. In particular, A related-to B and B exact-to C does not map A to C. Calculation weights, presentation parents, deprecation replacements, and local-name continuity are evidence, not rewrite rules.

## Bounded conditions, not a rule language

Retain the existing issuer/global columns and legacy inclusive `valid_from/valid_to` interpretation on **filing report-period end**. Display them as `report_period_end_from/to`; do not silently reinterpret old claims using fact period or acceptance time.

For new roots, add a strictly validated, immutable `conditions` object. Its schema contains:

| Field | Allowed semantics |
|---|---|
| `reports` | Nonempty finite set of accession + report-key pins, or absent for an explicitly reviewed reusable rule |
| `declaration_artifacts` | Exact schema artifact digest and declaration locator set for a reusable standard-concept claim |
| `dimensions` | Optional conjunction of explicit dimension/member equality, dimension absence, or no filed dimensions; every QName expanded |
| `context_entity` | Optional exact filed scheme/identifier when semantic scope requires it |
| `reuse_basis` | `listed_reports` or `reviewed_standard_declaration`; no default universal extension reuse |

No arbitrary Python, SQL fragments, regular-expression namespace matching, nested Boolean DSL, confidence threshold, or generic precedence field. Unknown keys fail validation. Conditions evaluate to match, no-match, or unknown; unknown never publishes. A predicate that depends on information unavailable in the source representation is unknown, not absent.

The initial `dimensions` predicates inspect the reported context, not inferred default members. Effective-default-aware equivalence requires the later aspect-comparison capability and its own reviewed condition form. Typed-member semantic predicates are deferred; typed XML remains inspectable. Required fiscal quarter/annual period and requested currency belong in selection, not reusable concept mapping. If evidence demonstrates a meaning changing by fact period within a filing, use report-specific review and keep those facts unresolved until an explicit fact-period semantic predicate is approved.

Default issuer-extension claims use issuer + listed reports. This makes the starting reuse policy conservative even where issuers reuse a namespace with altered declarations or disclosure meaning. For a standard concept, a reviewer can approve reuse under exact QName and approved declaration artifact pins, with semantic rationale applicable beyond one issuer. Labels supplied by an issuer do not override the standard definition automatically; conflicting disclosure evidence causes review.

New taxonomy namespaces generate candidates, not automatic inheritance. New filings of a previously reviewed extension also generate bounded re-review; the inspector shows declaration, disclosure, network, and usage changes. Adding a new report to a claim changes its conditions, so create a new root and atomically replace the previous claim. This is intentional until measured review volume justifies broader extension reuse with a proven drift detector.

## Evidence packets

Use one `ConceptEvidence` response for humans and agents, rendered as text/Markdown or JSON. Accepted evidence stores a compact snapshot, not only a mutable query URL.

An evidence item has a discriminated kind, summary, position (`supports`, `opposes`, or `context`), typed source pins, and a payload validated for that kind. Common kinds cover declaration, label/documentation, reference parts, network path, dimensional/unit usage, reported value reconciliation, disclosure excerpt, historical comparison, and reviewer/model analysis.

Source pins include accession/report input, BundleRef, artifact SHA/path, locator and QName where appropriate. Reference evidence outside a filing pins publisher URL, package/release and acquired artifact hash. Human analysis has an actor/rationale and links to source items; it cannot masquerade as filed text. Model analysis records model identity, prompt/version, schema version, input hash, parameters, output/failure, and supporting source references. Claimed model citations are checked against the provided packet.

Acceptance requires:

1. A concrete contract snapshot and current YAML/mirror agreement.
2. At least one resolvable source evidence item and a nonempty rationale explaining economic inclusion/exclusion, not merely a label match.
3. Explicit discussion of relevant contrary evidence or a statement of what was searched and its limits.
4. Scope/condition validation, compatibility checks and affected-fact preview.
5. Conflict checks in the acceptance transaction.

Schema validation cannot prove the reviewer's economics. Actors are local audit identifiers, not cryptographic identity proof. The first implementation assumes a trusted local curator; it needs no identity service.

Do not store installation-local fact IDs anywhere in durable evidence, including nested payloads. Validate pins structurally and resolve them against immutable inputs. Representative fact snapshots are useful; copying all affected facts into an assertion is not.

## Conflicts and safe correction

Continue to reject overlapping accepted exact claims for the same source concept, including stale accepted claims, unless the overlap evaluator proves the scopes/conditions disjoint. Check finite report sets, issuer equality, report-end intervals, and the supported simple predicates. If disjointness cannot be proven, treat it as an overlap. No numeric ranking or implicit issuer override resolves it.

This prevents contradictory exact meanings before publication. Distinct source concepts can still yield contradictory values for one target slot, so the selector independently checks output conflicts. Same-source broader/narrower/related knowledge can coexist with an exact claim but does not create extra strict values. Canonical subtype relationships later provide hierarchy; do not express the same source fact as universally exact to both parent and child totals.

Keep the current state machine:

```text
candidate → accepted
candidate → rejected
accepted  → rejected   (withdrawn/revoked meaning)
```

Add `replace(old, reviewed_new_candidate)` as an atomic service transaction:

1. Lock the source concept(s) in deterministic order and relevant metric rows in the common sync/decision order; recheck current revision and definition hash.
2. Validate the new evidence/conditions and conflict query excluding only the explicitly replaced accepted claim(s).
3. Insert rejected successor(s) with revocation reason for the old accepted chain(s), and an accepted successor for the new candidate.
4. Commit all or none. Link the new root to the old root via `replaces_root_id` and include correction rationale.

Use a single-old-claim form initially; multiple replacements require explicit input and tests, not an accidental loop of partially committed changes. Independent revoke remains available for an error with no correct replacement. Concurrent replacements of one claim cannot branch; direct history UPDATE/DELETE is blocked. Definition sync and acceptance must serialize on the same contract lock, so a newly stale candidate cannot be accepted after validation against old content.

Revocation affects new queries immediately. Published datasets stay byte-identical; dependency inspection lists exports using the revoked revision and creates a withdrawal/correction notice. As-of semantic queries can still reconstruct the previous belief with a prominent historical status.

## Concrete human and agent workflows

Commands below are **proposed interfaces**, not existing commands. Preserve the existing mapping CLI where it already fits.

| Task | Inputs and action | Required response |
|---|---|---|
| Inspect unknown concept | `edgar concepts show '{namespace}Name' --accession … --format json` | Exact QName, each declaration/report separately, schema origin/hash, labels and documentation, reference parts, type/period/balance, typed-domain data, role definitions, bounded network neighborhoods, dimensions/units, representative located facts, history and current proposals |
| Inspect a fact | `edgar facts show --accession … --report-key … --artifact … --locator-file …` | Source raw/resolved value, full context/unit/accuracy, Inline continuation and footnotes, declaration, all matching decisions and condition outcomes |
| Create candidate | Existing `mappings propose` extended with a validated claim/evidence input file | New candidate revision, contract snapshot, scope preview, compatibility warnings and conflict preview; no trusted value |
| Review candidate | `mappings show <id> --review --format json` | Immutable named revision, predecessor/correction chains, exact old/current contract diff, evidence for/against, declared coverage, representative cases and excluded cases |
| Accept/reject | Existing decision commands with actor/rationale/evidence | New revision and transaction outcome; no predecessor mutation |
| Revise meaning/scope | New candidate then `mappings replace <old-id> --with <candidate-id>` | Atomic withdrawal/replacement, changed coverage, affected publication references |
| Find important gaps | `concepts unmapped --corpus … --metrics …` | Unmapped source-concept/report groups prioritized by statement presence and requested-slot gaps, occurrence/issuer counts, and candidate-only/non-exact/stale status |
| Trace observation | `financials explain --publication … --row …` | Request → selected value/checks → contract/decision → all support occurrences → bytes, with saved snapshots available after re-extraction |
| Explain missing | Same financial query with `--explain` | Counts at extraction, mapping, compatibility, scope, period, unit, duplicate, and temporal stages; actionable source pins and reason codes |

The concept inspector defaults to bounded pages (for example, 25 facts and a two-hop network neighborhood); the response includes total counts, truncation flags and continuation parameters. Show all reports separately unless the caller explicitly requests a summarized comparison. Namespace “family” and extension flags are descriptive classifications derived from provenance, not QName identity.

Importance is a review-priority heuristic, not semantic confidence. Use primary-statement placement, requested metric gaps, and frequency across issuers/reports. Raw numeric magnitude is not comparable across units/scales; label similarity is only a search signal. Review queues should expose unsupported structures and missing extraction separately from unmapped concepts.

## Worked cases

**Annual and segment revenue.** A reviewed source concept maps exactly to the revenue contract for a named issuer/report. The annual consolidated and Europe facts both retain the revenue mapping plus their different dimensions. `reported-annual-v1` selects only the supported consolidated slot. It does not sum Europe and other segments.

**AdjustedNetSales.** QName and a friendly label cannot establish exactness. The packet shows the issuer's adjustment definition and a reconciliation removing an expense. A reviewer records `related` or rejects an exact candidate. The ordinary revenue query returns `non_exact_only` if no better source exists.

**Reused extension QName.** Report A defines an amount excluding a business; report B includes it under the same QName. A claim scoped to A cannot match B. A broad QName-only mapping would have silently changed economic meaning; the report condition prevents that.

**Two revenue values.** Two accepted source concepts produce the same requested aspects but different values. The query returns a conflict with both pins. Fix the economic mapping, reporting-basis qualification, or erroneous source condition; do not make source order a selection policy.

**Product/service representation.** An issuer reports a product-revenue concept; another reports total-revenue concept with ProductMember. Inspection can establish a case for comparability. M2 can guard a mapping while retaining that dimension, but does not erase it to create a scalar total. A later explicit aspect transformation may map the complete input pattern to product revenue, record which qualifier was consumed and retain all residual qualifiers. No hidden projection of dimensions is allowed.

## AI and deterministic assistance

Initially all semantic acceptance is explicit review. Deterministic code can find exact QName reuse, calculate structural diffs, validate conditions, retrieve reference definitions, and apply accepted assertions without another manual decision for each fact. A deterministic candidate rule is still a proposal unless its entire semantic acceptance policy has been separately reviewed and tested.

Optional AI sees a versioned, bounded evidence packet; it returns structured proposals with cited source pins, contrary evidence, and uncertainty. The same inspector used by a human supplies its context. It cannot approve its own output, create source facts, alter fixtures, or become required for replay/querying accepted knowledge. Keep invocation artifacts outside canonical decisions; selected analysis becomes evidence only through review.

Record rejection reasons to avoid repeating the same unsafe suggestion. Do not treat an uncalibrated model score as a probability. Measure accepted mapping precision and review effort on held-out reports before considering any expansion of automation.
