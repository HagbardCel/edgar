# Financial metric semantics

**Status:** financial domain reference, condensed during the 2026-09-05 planning consolidation. This is not a separate architecture or implementation plan. The implemented ledger contract is [normalization](normalization.md); proposed mapping, selection and phase decisions live in the [target package](architecture/README.md).

## Source meaning and comparable measurement

Keep immutable source artifacts and every supported fact occurrence with its original QName, declaration, context, unit, dimensions, accuracy/nil state and source locator. Current extraction tables are regenerable; “preserve source truth” does not require keeping every SQL extraction forever. Interpretation must never overwrite the evidence it explains.

A canonical financial meaning is a precise measurement contract. Industry-specific revenue, continuing/discontinued operations, controlling/noncontrolling scope and GAAP/non-GAAP basis can differ materially. A familiar name or taxonomy label does not establish equivalence. A hierarchy may help navigation later, but is not required to define correct contracts now.

Review two questions separately: what the source expresses, and why it satisfies the particular contract. Declarations, documentation, accounting references, networks, source disclosures, dimensional usage and historical examples provide evidence. A reference taxonomy is useful without requiring a second source-to-reference ledger. See [mapping and review](architecture/mapping-and-review.md).

## Mapping is separate from selection

A concept may be correctly mapped while none of its facts satisfies the requested period, unit, entity, reporting basis or dimensional slice. Annual, quarter and YTD observations are not interchangeable. Statement placement supports interpretation but is not universal proof of meaning or a reason to discard a valid concept automatically.

Current ledger relationship types are `exact`, `narrower`, `broader`, and `related`. The target retains exact equivalence under explicit conditions and distinguishes non-publishable relationships from review status. Issuer scope is a condition, not a separate equivalence type; an unresolved candidate is a workflow state, not a financial meaning. Keep rejections and contrary evidence so bad suggestions need not be rediscovered.

The target does not use “more specific mapping wins,” automatic label-based acceptance, or generic score-based selection. Candidates never publish as trusted values; accepted claims still need fact qualification. A conditional mapping preserves dimensions. Any later transformation must identify consumed and residual aspects. Derived and proxy quantities remain explicitly distinguishable from reported ones; wider definitions do not become equivalent by being called a quality tier.

## Evidence and financial validation

Useful review evidence includes exact taxonomy identity and origin; labels/references; declaration properties; role-scoped presentation/calculation and dimensional relationships; unit/period/scope; issuer history; rendered statement lines and disclosure text; and previous decisions, including contrary cases. Packet capability status distinguishes inspected absence from unassessed omissions. Required evidence must be accessible and pinned even if it lacks dedicated SQL tables.

Reconciliations and longitudinal checks can uncover mistakes, but cannot approve a mapping on their own. Check compatible accounting scope, periods, currency, sign and accuracy before comparing assets with liabilities/equity, reconciling cash flows, or interpreting changed comparative values. A calculation edge does not authorize summing all facts; an unchanged value does not prove unchanged accounting meaning. A score is not a probability without calibration and never substitutes for evidence.

## Distinctions to preserve


### Revenue

Potentially related, not universally equivalent:

- `SalesRevenueNet`
- `Revenues`
- `RevenueFromContractWithCustomerExcludingAssessedTax`
- issuer-defined revenue extensions
- bank net revenue
- insurance premiums and investment income

### EBITDA

Keep separate:

- EBITDA
- adjusted EBITDA
- segment adjusted EBITDA
- covenant EBITDA

### Capital expenditure

Keep separate until a research definition is selected:

- cash purchases of PP&E
- additions to PP&E
- capitalized software
- finance-lease additions
- intangible-asset purchases

### Debt

Preserve components:

- short-term borrowings
- commercial paper
- current portion of long-term debt
- long-term debt
- finance leases
- operating leases

### Share counts

Never conflate:

- period-end shares outstanding
- weighted-average basic shares
- weighted-average diluted shares

## Optional AI assistance

An AI may summarize pinned evidence, suggest concepts or contrary cases, and help a reviewer articulate uncertainties. Candidate generation remains deferred under current project scope. It cannot invent filed facts, mutate raw evidence, silently equate GAAP/non-GAAP measures, or approve its own uncertain proposals. A deterministic standard-QName match still requires an approved economic rule before publication.

Code-mediated calls require explicit purpose, versioned prompt, validated response, model identity, input hash, parameters/failures and separately retained outputs. Ingestion, tests and core review must work with models disabled. [Mapping workflows](architecture/mapping-and-review.md) define the planned human/agent interface without making a model the authority.

## Research use and expansion

Analytical exports should expose the exact contract and decision, relationship/scope, source extension status, reported/derived origin, policy and missing/conflict explanations. Do not fabricate a numerical confidence field where no calibrated judgment exists.

A later study should assess sensitivity to definitions, direct versus derived values, standard versus extension mappings, industry scope and uncertain cases. Broad historical use requires evidence across issuers, taxonomy releases and changed-meaning counterexamples. Mapping uncertainty is part of the research design. The [testing plan](architecture/testing-and-quality.md) defines the bounded first-release gates; [retained roadmap requirements](architecture/documentation-consolidation.md#deferred-product-requirements-from-the-long-term-roadmap) cover later market/text research without authorizing it now.
