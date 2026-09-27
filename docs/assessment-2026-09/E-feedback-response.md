# E — Response to the fourth hardening critique

**Status:** independent reply, then a last specification-hardening
revision. No architecture reopening. The feedback is not authoritative;
every item below was accepted or rejected on its own merits.

The input argued: the architecture is sound; fix three substantive
contract holes plus a few cheap ambiguities; then stop iterating and
implement P0/P1/P2.

Implementation-contract pins after this file are in
[F](F-feedback-response.md) (taxonomy origin, slot eligibility,
`period_role`, gold cohorts, Q4 dates).

## Verdict

I agree. Nothing here is a missing component. After this pass I would
**merge the assessment and treat architecture review as closed.**

The three must-fixes:

1. Tier-2 mismatch is never overridden by an identity residual.
2. P2 reports contract coverage and selector yield separately.
3. CI regression uses a frozen prior gold cohort, not the growing set.

The rest of the list is adopted in the same revision because it is cheap
and would otherwise be invented at implementation time.

## Point by point

### 1. Tier-2: overlap mismatch queues — **adopt (must-fix)**

Agreed. “Overlap agrees **or** identity residual closes” contradicted
“mismatch → queued.” An identity closing elsewhere is Tier-3-style
structural evidence, not continuity.

P4.2 is now:

```text
comparable overlap exists and agrees  → may reuse
overlap exists and disagrees         → queue
no overlap exists                    → queue
  (identities/labels are evidence, not acceptance)
```

### 2. Two coverage numbers — **adopt (must-fix)**

Agreed. Revenue still applies in 2014 without RFCWCEAT. Dropping those
years from the denominator hides a missing **era decision**.

```text
contract_coverage     = values / issuer-years where the metric applies
selector_yield        = values / issuer-years where the current
                        exact decision's concept exists and is relevant
unsupported_no_era_decision = applicable metric, no era-appropriate
                              exact decision
```

Hypotheses and the “inspect 20 missings” gate use **selector_yield**.
Publication talk uses **contract_coverage**.

### 3. Frozen-cohort regression vs growing gold — **adopt (must-fix)**

Agreed. Adding harder labels can lower overall precision without a
software regression. CI now:

- **must not** fail because the gold *population* grew;
- **must** fail if previously labeled cases change (frozen prior cohort);
- reports full current-set precision against an absolute publication
  floor, separately.

### 4. `other_standard` vs `issuer` — **adopt**

Agreed. Unknown ≠ issuer. The classifier becomes:

```text
us-gaap | dei | srt | other_standard | issuer
```

`other_standard` starts with the SEC reference families (country,
currency, exch, naics, sic, stpr) and their `xbrl.us` historical
prefixes. P0.3 keeps unused `issuer` declarations only; unused
`other_standard` is dropped like unused US-GAAP.

### 5. Tier 4 key is `(accession, source_qname)` — **adopt**

Agreed. QName-only would mark later filings as human-reviewed.

### 6. Operational `period_kind` — **adopt**

Agreed. Dates alone cannot split Q1 quarter from Q1 YTD (same interval).

```text
10-K required duration     → annual
Q2/Q3 required duration    → YTD
explicit ~3-month duration → quarter
Q1 required duration       → quarter_ytd
```

Identity remains the dates.

### 7. Derived Q4 — **adopt**

Agreed. Duration contracts only. Never run on instants. Do not copy
coarsest input `decimals` onto the output. Store `input_decimals` and a
conservative derived error bound (interval half-widths add).
`kind=derived` stays.

### 8. Oracle is taxonomy + tag — **adopt**

Agreed. `(taxonomy_family, local_name)`. Return
`hit | absent | ambiguous`; never silently pick among duplicate API
points.

### 9. Uniqueness without scope algebra — **adopt (simplify)**

Agreed. One current file per

```text
(metric, family, issuer_cik or "", local_name)
```

Scope (`exclude_ciks`, `exclude_sic_divisions`) is an **attribute of
that file**, not part of the key. No overlap algebra. Two files for the
same key fail `edgar rules check`.

### 10. “Rules” residue in 05 / P2.4 — **adopt (cleanup)**

Agreed where the sentence names the authored object.

## What I still reject

| Implication | Why |
|---|---|
| Another architecture pass | No missing component. |
| Identity residual as a Tier-2 accept path | That is structural auto-accept. |
| Fail CI when new gold lowers overall precision | Punishes the measurement. |
| Scope-overlap algebra | Too much machinery; one file per concept key is enough. |

## Documents updated in this revision

| Document | What changed |
|---|---|
| [04](04-target-architecture.md) | `other_standard`; uniqueness without scope key; period_kind |
| [05](05-mapping-strategy.md) | Coverage split; decision wording; period_kind |
| [08](08-migration-plan-assessment.md) | Pointer to this file |
| [P0](plan/P0-freeze-and-fix.md) | Classifier fallback |
| [P1](plan/P1-walking-skeleton.md) | Uniqueness key |
| [P2](plan/P2-scale-spike.md) | Two coverages; oracle identity |
| [P4](plan/P4-extensions-and-review.md) | Tier-2; occurrence key; gold CI |
| [P5](plan/P5-time-and-quarterly.md) | Operational period_kind; Q4 gates |
| [P6](plan/P6-breadth.md) | Frozen-cohort precision |
| [README](README.md) | Link to this file |
