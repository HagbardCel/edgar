# Metric Semantics and Mapping Architecture

**Purpose:** Define how filed XBRL facts become comparable financial metrics without destroying economically meaningful differences.

---

## 1. Core rule

> Preserve raw facts permanently. Treat every canonical metric as a versioned interpretation supported by explicit evidence.

Metric mapping must never overwrite, relabel, or delete the source fact.

---

## 2. Four semantic layers

```text
1. Raw fact occurrence
2. Filed economic observation
3. Canonical metric observation
4. Research feature
```

### Raw fact occurrence

Exactly what appears in the filing:

- concept
- value
- context
- unit
- dimensions
- scale/sign/precision
- document occurrence
- taxonomy relationships

### Filed economic observation

A normalized description of the filed fact without asserting broad comparability.

### Canonical metric observation

A versioned interpretation under a precise metric definition.

### Research feature

A derived variable such as growth, margin, surprise, accruals, or return predictor.

These layers must remain independently queryable.

---

## 3. Metric families and definitions

Use a hierarchy rather than one flat metric vocabulary.

Example:

```text
revenue
├── operating_company_revenue
├── banking_net_revenue
├── insurance_revenue
├── regulated_utility_revenue
└── real_estate_rental_revenue
```

A canonical metric definition is a measurement contract containing:

- economic definition
- accounting basis
- period type
- canonical unit
- entity scope
- continuing/discontinued-operations policy
- inclusion rules
- exclusion rules
- allowed dimensions
- statement-role expectations
- industry applicability
- aggregation behavior
- derivation policy
- sign convention
- definition version

---

## 4. Mapping relationship types

Mappings are typed relationships, not booleans.

| Type | Meaning |
|---|---|
| `equivalent` | Same economic definition under the mapping conditions |
| `issuer_equivalent` | Equivalent only for a particular issuer and validity period |
| `narrower_than` | Excludes part of the target definition |
| `broader_than` | Includes additional economic components |
| `component_of` | Can contribute to a derived target |
| `derived_equivalent` | Reconstructable through an approved formula |
| `presentation_alias` | Alternative presentation of the same underlying concept |
| `proxy_for` | Related but not equivalent; research use must be explicit |
| `incompatible` | Similar-looking but materially different |
| `unresolved` | Insufficient evidence |

Store negative decisions such as `incompatible`; they prevent repeated unsafe suggestions.

---

## 5. Mapping scopes

A rule may be:

- global standard-taxonomy rule
- accounting-regime rule
- industry-specific rule
- issuer-specific rule
- issuer-and-period-specific rule
- filing-specific override

Narrower rules take precedence, but every selection must retain the rule ID and rationale.

---

## 6. Mapping pipeline

### Stage A — Candidate generation

Use:

- exact taxonomy identity
- labels and references
- concept documentation
- presentation parents/children
- calculation parents/children and weights
- statement role
- period type
- units
- dimensions
- issuer history
- taxonomy transitions
- industry
- neighboring statement lines
- prior reviewed mappings

This stage favors recall and produces candidates only.

### Stage B — Hard compatibility filters

Reject candidates for:

- instant/duration mismatch
- incompatible unit
- incompatible scope or dimensions
- wrong statement role
- quarter/YTD/annual mismatch
- segment/consolidated mismatch
- continuing/discontinued-operations mismatch
- known non-GAAP definition
- broader/narrower semantics where exact equivalence is required

### Stage C — Evidence scoring

Score compatible candidates using a versioned policy:

```text
taxonomy evidence
+ definition evidence
+ statement-network evidence
+ context compatibility
+ issuer continuity
+ peer/industry evidence
```

The score is not a probability unless explicitly calibrated.

### Stage D — Accounting and longitudinal validation

Check:

- calculation-tree consistency
- balance-sheet identities
- cash-flow reconciliation
- sign and scale
- plausible ranges
- comparative-period continuity
- taxonomy transitions
- rendered-statement agreement

### Stage E — Review and approval

Ambiguous extensions enter a review queue. The reviewer sees the complete evidence packet and records:

- relationship type
- scope
- validity interval
- rationale
- confidence tier
- review status

---

## 7. Conservative acceptance policy

Default behavior:

> Keep facts separate unless equivalence is demonstrated.

Initial auto-acceptance should be limited to trusted standard concepts under compatible contexts and statement roles. Company extensions should generally require issuer-history evidence or review.

---

## 8. Observation quality tiers

### Tier A — Strict

- direct reported fact
- `equivalent` or approved `issuer_equivalent`
- high-confidence compatible context
- no unresolved semantic warnings

### Tier B — Standardized

- approved derivations
- broader mapping policy
- still supported by explicit rules

### Tier C — Proxy

- economically related but not equivalent
- never silently exposed under the strict metric name

Research datasets must state which tiers they include.

---

## 9. Proposed mapping tables

### `metric_family`

- family code
- name
- parent family
- description

### `metric_definition`

- metric code
- definition version
- family
- contract fields
- active interval

### `metric_mapping_rule`

- source concept
- target metric
- relationship type
- scope
- issuer/industry applicability
- validity interval
- conditions
- confidence
- rationale
- review status
- policy version

### `metric_candidate`

- source fact
- candidate metric
- rule
- score
- hard-check results
- evidence
- selected/rejected
- rejection reason

### `metric_observation`

- source fact or derivation
- target metric
- economic period
- value
- dimensions
- known-at timestamp
- metric-definition version
- mapping-policy version
- mapping rule
- confidence tier

### `metric_derivation`

- formula version
- input observations
- result
- calculation time
- known-at semantics

### `mapping_review`

**Phase 2A note:** This table is **not** implemented. ADR 0010 replaces it: every stored `metric_mapping_rule` is a historically human-approved decision; `reviewed_by` / `reviewed_at` are mandatory; current vs superseded is derived from the supersession graph (no `review_status` column). See [phase-2-data-model.md](phase-2-data-model.md).

Planned fields (Phase 2C+ review workflow):

- decision
- reviewer
- evidence snapshot
- notes
- timestamp

---

## 10. Local LLM role

A local LLM may:

- propose candidate mappings
- summarize taxonomy evidence
- identify possible semantic warnings
- suggest reviewer questions
- explain why concepts may differ

It may not:

- mutate raw facts
- auto-approve ambiguous extensions
- equate non-GAAP metrics with GAAP metrics by label similarity
- replace hard compatibility checks
- create source facts not present in the filing
- become required for reproducible research datasets

Every LLM call must use:

- versioned prompt
- schema-validated response
- recorded model identity
- input hash
- explicit purpose
- stored output separate from canonical mapping decisions

---

## 11. Examples of distinctions to preserve

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

---

## 12. Research robustness

Every analytical extract should expose:

- mapping confidence
- relationship type
- mapping scope
- direct versus derived
- extension concept flag
- quality tier
- definition version
- mapping-policy version

Required sensitivity analyses include:

- strict versus broad mappings
- direct-only versus derived observations
- standard concepts only versus issuer extensions
- exclusion of financial companies
- exclusion of low-confidence mappings
- alternative metric definitions

Mapping uncertainty is part of the empirical design, not merely an ETL problem.

---

## 13. Phase gates

Metric normalization may begin only when Phase 1 can provide, for a candidate fact:

- all labels and references
- statement role
- presentation and calculation neighborhood
- period and dimensions
- unit and value
- issuer history
- exact source location and artifact hash

A metric may be promoted to broad historical use only after:

- definition contract approval
- fixture coverage
- issuer-history validation
- mapping precision review
- explicit versioning
- sensitivity testing
