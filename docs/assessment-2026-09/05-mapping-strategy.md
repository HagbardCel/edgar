# 05 — Mapping strategy

Mapping is the product. This document derives a strategy from the problem and the data, rather
than from the adopted plan. It then says how its quality will be measured.

## 1. Three questions, three owners

"Mapping" bundles three different questions. They have different answers, different owners and very
different costs.

| Question | Example | Who knows the answer | How often it must be answered |
|---|---|---|---|
| **Q1 Concept meaning:** what does filed concept C mean? | `us-gaap:NetIncomeLoss` is "profit or loss … attributable to the parent" | FASB for standard concepts; the filer for extensions | Once per standard concept (per release); once per extension family |
| **Q2 Contract relation:** how does C relate to metric M? | `Revenues` is *broader* than `revenue`; `RevenueFromContractWithCustomer…` is *exact* (outside banks) | Us, as a reviewed **decision** with conditions | Once per (metric, concept family, condition) |
| **Q3 Selection:** which fact is the value for issuer × metric × period? | the undimensioned, registrant-entity, required-period fact; consistent duplicates reduced to the most precise | Deterministic policy using EDGAR and XBRL conventions | Computed for every filing; never reviewed by hand |

The adopted plan folds all three into **per-report claims with per-occurrence human
qualification**:

- extension claims default to issuer + listed reports;
- "exact" needs affirmative definition evidence per claim;
- consolidated scope, basis and sign are human conclusions per occurrence.

Human effort then grows with filings × metrics.

Separating the questions makes effort grow with *distinct semantics* instead:

- Q1 and Q2 for standard concepts are global and decided once.
- Q3 is mechanical.
- Only extensions and genuine exceptions need case-level attention.

## 2. What the data says

Local corpus of six filings (details in [A](A-evidence-and-method.md)):

- **85.6%** of facts use standard concepts. On SEC-classified primary statements, extensions are
  **2–14%** of non-abstract line items per filing (WMT 2%, KO 5%, eBay 11% in both years, JPM 14%).
- All 13 hand-verified benchmark values are standard concepts. An **eight-row global rule table** (one standard concept per metric) plus
  a selector reproduces **13/13**. The selector takes the registrant entity, no dimensions, a USD
  unit, and the period of the EDGAR required context (the context carrying
  `dei:DocumentPeriodEndDate`).
- The nine non-value cases are consistent with the rules. Broader, narrower and related concepts are
  never in the exact table. Slots without an exact undimensioned fact return `missing`: bank
  revenue, segment/YTD, the 10-K/A without statements, and Walmart R&D.
- **Two cases the manual process left open are resolvable from standards already in the bundle:**
  - *Parent net income:* the FASB documentation for `NetIncomeLoss` defines it as attributable to
    the parent. That text is in every bundle's `MetaLinks.json`. The identity
    `ProfitLoss = NetIncomeLoss + NetIncomeLossAttributableToNoncontrollingInterest` detects
    filer mis-tagging where both are present.
  - *Walmart cash:* the two facts, 9,867,000,000 at `decimals=-6` and 9,900,000,000 at
    `decimals=-8`, are **consistent duplicates**. Rounding the first to −8 gives the second. The
    XBRL duplicate-facts guidance treats them as one fact, with the more precise value
    authoritative.
- **Issuer extension local names persist across years** while the namespace date changes (eBay
  2022 → 2023). Issuer continuity is therefore a cheap, strong reuse signal.

Six filings do not prove market-scale coverage. They do show that the plan's central premise, that
safe mapping needs per-report human qualification, does not hold for the cases it was designed
around.

## 3. Evidence available for mapping

| Source | What it provides | Strength | Cost / availability |
|---|---|---|---|
| FASB documentation labels and authoritative references | Authoritative meaning of standard concepts (Q1) | Strong | In every bundle via `MetaLinks.json`; complete via taxonomy packages |
| SEC statement classification (`MetaLinks`/`FilingSummary`: `groupType`, `longName`) and EDGAR role definitions | Whether a concept is on a primary statement, and which one | Strong | In every bundle; unparsed today |
| Filer calculation linkbase | Arithmetic parent/child relations and weights in this filing | Strong for structure; filer calc errors occur | Extracted today |
| Filer presentation linkbase | Line position and order, preferred labels (e.g., negated, total) | Medium | Extracted today |
| Filer extension labels and documentation | Filer's stated meaning of extensions | Medium (free text) | Extracted today |
| Definition linkbase and dimensions | Segment vs consolidated scope; axes and members | Strong for scope | Extracted today |
| Issuer history | The same extension local name was already mapped in earlier filings | Strong when values are continuous | Free once rules exist |
| Value corroboration | The extension fact equals a standard-concept fact, a comparative or an identity residual | Strong for the specific occurrence | Cheap SQL |
| Accounting identities | Balance sheet, cash-flow roll-forward, NCI split, gross profit | Strong validators | Cheap SQL |
| SEC `companyfacts` / frames | SEC's per-concept series (standard taxonomies, non-dimensional) | Strong oracle for extraction + selection | Free API, one call per issuer |
| SEC Financial Statement Data Sets | Market-wide numbers with statement and line position, plus custom-tag labels | Strong for coverage estimation and evaluation at scale | Free quarterly downloads |
| Open-source standardization maps (e.g., EdgarTools, secfsdstools, XBRL US Fundamental Accounting Concepts) | Concept → line-item mappings | Unknown precision; usually no rationale | Free; seeds only, to be measured |
| LLM reading the evidence packet | Semantic judgement on extensions and edge cases | Medium; must be measured | Local model or API; non-deterministic |

## 4. Strategy comparison

| Strategy | Accuracy | Coverage | Explainability | Cost | External dependence | Suitable for automation | How confidence is established |
|---|---|---|---|---|---|---|---|
| **S1** Per-report human review + occurrence qualification (adopted plan) | High on reviewed cases | Very low; bounded by reviewer hours | High | Very high, O(filings × metrics) | None | No | Human attestation, unmeasured |
| **S2** Global decisions on standard concepts + deterministic selector | High; residual is filer mis-tagging | High for standard-tagged metrics; zero for extension-only | Very high (one decision, one definition) | Very low (hundreds of decisions, once) | Taxonomy only | Full | Validators, oracle agreement, gold precision |
| **S3** Issuer extension decisions by review, reused via overlap-period continuity | High | Targeted | High | Moderate, O(distinct extension patterns); amortized | None | Reuse when overlap agrees; mismatch or no overlap queues | Review + continuity checks |
| **S4** Structural proof for extensions (calc position, value equality, statement role) | Medium–high when proof conditions are strict; zeros collide | Moderate | High (the proof is recorded) | Low (code + one policy review) | None | Candidate ranking only; not auto-accept | Per-policy precision on gold before any later ADR |
| **S5** Third-party mapping tables | Unknown, varies | Broad | Low–medium | Low | Maintainer, license | Proposals only | Must be measured against gold |
| **S6** Label or embedding similarity | Low–medium (labels do not prove equivalence) | Broad | Low | Low | Embedding model | Candidate retrieval only | Not a basis for acceptance |
| **S7** Supervised classifier | Possibly good | Broad | Low | Labeled data + upkeep | Training data | Premature | Held-out precision |
| **S8** LLM proposal (one structured call per candidate) | Medium–high on semantic reading; fails on broader/narrower subtleties | Broad | Medium (rationale, not proof) | Low per call | Model, prompt version | Proposals; accept only by human review | Measured precision per model × prompt version |
| **S9** Autonomous agent framework | No gain over S8 for a bounded classification | Broad | Low (multi-step traces) | Higher; orchestration state | Framework + model | Poor | Hard to measure |
| **S10** Use `companyfacts`/FSDS as the primary source | High for what it covers | Standard concepts only; no dimensions, no extensions; no statement structure in `companyfacts` | Medium (SEC-derived) | Very low | SEC's derivation | Full | Inherits SEC's choices |

Notes on the less obvious rows:

- **S1 fails on cost, not accuracy.** At 5,000 issuers × 39 metrics × one annual filing, even one
  minute per slot is ~3,250 reviewer-hours per year, before quarterlies. Consistency across
  reviewers is not measured. Reviews also go stale when contracts change.
- **S2's main risks are known and testable:**
  - Filer mis-tagging, caught by identities and the oracle.
  - Industry semantics, such as bank revenue. These are handled by decision scope on SIC-derived
    industry, not by per-report review.
  - Taxonomy deprecations. The taxonomy table lists concepts per release, so a deprecated concept
    simply stops matching new filings. Its replacement gets a decision.
- **S4 is evidence, not acceptance.** Examples:
  - An extension's value equals a standard-concept fact for the same context (zeros collide).
  - An extension is the calculation parent of the same children as a standard total, and the
    arithmetic verifies.

  Calculation linkbases contain filer errors, so proofs that rely on them must also verify the
  arithmetic on the facts. These proofs rank the review queue. They do not write `status:
  accepted`.
- **S8 must not decide.** It reads the evidence packet (definition, statement position, calc
  neighbours, values, prior mapping) and proposes `(metric, relation, rationale)`. Acceptance comes
  from a human only. A later ADR may allow a narrow S4 proof class only after **candidate**
  precision (reviewed exact/non-exact labels) is effectively perfect. This is consistent with
  `AGENTS.md`.
- **S9 adds nothing** that one structured LLM call plus deterministic tools does not. A
  general-purpose coding agent is useful for *investigating* the review queue through the CLI and
  SQL. Nothing in the pipeline should depend on an agent framework.
- **S10 is an excellent oracle and a poor foundation.** It covers only non-dimensional
  standard-taxonomy facts. It encodes SEC's own frame-selection choices. It cannot represent the
  counterexamples the project cares about.

## 5. Recommended staged strategy

```mermaid
flowchart TB
  F[Facts of a filing] --> T1{Standard concept<br/>with global decision?}
  T1 -- yes --> A1[Tier 1: standard decision]
  T1 -- no --> T2{Issuer decision for this<br/>extension family, overlap<br/>agrees?}
  T2 -- yes --> A2[Tier 2: continuity]
  T2 -- no --> T3{Structural proof<br/>value equality / verified<br/>calc position?}
  T3 -- yes --> Q3[Tier 3: proof on queue<br/>not accepted]
  T3 -- no --> P{On a primary statement<br/>near a missing metric?}
  P -- yes --> Q[Review queue<br/>evidence packet,<br/>optional LLM proposal]
  P -- no --> N[Ignored: not a candidate]
  Q3 --> Q
  Q -- human decision PR --> A4[Tier 4: reviewed issuer decision]
  A1 --> S[Selector]
  A2 --> S
  A4 --> S
  S --> O[Observation or typed<br/>non-publication reason]
```

**Stage 1: global decisions and selector.** Build this first.

- Global decisions for the eight benchmark contracts, then all 39. Each metric gets its exact concept
  families, plus explicit broader and related concepts that are never published as exact.
- Industry conditions from SIC for banks, insurers and REITs.
- The annual selector (section 6).
- Validators and the SEC `companyfacts` oracle.
- The gold set.
- Expected effort is a few days of decision authoring, because the decisions are decided once per concept
  family.

**Stage 2: extensions by continuity and candidates.** Rank the residual:

1. Issuer-years where a headline metric is `missing` but the matching primary statement contains an
   unmapped line item.
2. Apply Tier 2 continuity (reuse of an already-accepted issuer decision, guarded by value and
   label continuity).
3. Attach Tier 3 *proofs as evidence on queue items* (value equality, verified calc parent). These
   do **not** auto-accept. Equal numbers are not semantic identity (two zeros are not the same
   concept).
4. Generate an evidence packet for the rest: definition, labels, statement and line position, calc
   parent and children, values, prior-year mapping, prior **rejected** decisions, and the identity
   residual it would close.

Humans resolve queue items by writing decision records, which are then reused automatically when
status is `accepted`.

**Stage 3: LLM proposals for the queue.** Use a versioned prompt with a schema-validated output, and
record the model, input hash and parameters, as `AGENTS.md` requires.

Proposals only reorder or pre-fill review. A proposal becomes a decision when a human accepts it
(or, later, if a narrowly defined proof class has measured effectively-perfect gold precision —
not in the initial sequence).

Measure the proposal precision per model and prompt version. Stop using the step if it does not
save review time.

**Stage 4: harder semantics, when the data demands them.**

- Quarterly and YTD selection, with Q4 derived from the annual figure minus nine months as a
  flagged *derived* observation.
- Dimensional metrics (segments) with an explicit policy.
- Issuer-specific contract variants, such as bank revenue.

### Acceptance tiers

| Tier | Basis | Accepted by | Typical share (hypothesis, to be measured) |
|---|---|---|---|
| 1 Standard decision | FASB definition + reviewed family decision, expanded to exact QNames | Policy, automatically | Most headline observations |
| 2 Continuity | Reviewed issuer decision, same extension local name, values and labels continuous | Policy, automatically | Recurring extensions |
| 3 Structural candidate | Value equality or verified calculation position | **Queue only.** Never publishes as exact until a human accepts, or a later ADR authorizes a proof class with measured ~perfect gold precision | Some new extensions |
| 4 Reviewed | Human-reviewed issuer decision (possibly LLM-proposed) | Human | Residual |
| — Unresolved | — | Not published; queued | — |
| — Rejected | Prior decision `status: rejected` with **current** `contract_hash` | Not published; queue suppresses unless new evidence. Stale-hash rejections are history only and do **not** suppress | — |

Every observation records its tier and `decision_id`s. Datasets can filter by tier; for example, a
conservative study uses Tiers 1–2 only. Tier 3 never produces a published observation.

## 6. Observation selection (deterministic, standards-based)

The `annual-v1` selector runs only on forms `10-K` and `10-K/A`. A 10-Q is out of
scope for this policy (P5). If invoked on a 10-Q it returns `status=unsupported`,
`reason=wrong_form`, never an annual value.

1. **Filing's own report period.** Take the EDGAR required context: the undimensioned context of
   the DEI cover facts, such as `DocumentPeriodEndDate`. Duration metrics use its start and end;
   instant metrics use its end. `DocumentFiscalYearFocus` and `DocumentFiscalPeriodFocus` classify
   **this filing's own** period. They are not the identity of comparative facts in the same
   instance.
2. **Slot identity** is `(cik, metric, period_start|instant, period_end, unit, scope)`. Derived
   labels: an own-filing required context plus that filing's DEI FY/focus
   creates an issuer-period **anchor** (`fiscal_year`, `report_focus`).
   Observation `period_role` is operational (`annual | YTD | quarter |
   quarter_ytd | instant`); see P5. Context `period_kind` stays
   `duration | instant | forever`. Q1 required duration is `quarter_ytd`
   because quarter and YTD share one interval.
   A comparative fills year/focus only on a unique anchor match, otherwise
   those labels stay unknown. A FY2022 comparative inside a FY2023 10-K
   belongs to the 2022 slot.
3. **Candidates.** A candidate fact must satisfy all of the following:
   - its exact QName is in the expansion of an applicable exact decision (Tiers 1–2 or 4;
     conditions satisfied);
   - its entity uses the SEC CIK scheme (`http://www.sec.gov/CIK`) and the
     10-digit padded CIK;
   - it has no dimensions. Arelle is not allowed to invent defaults; undimensioned means the
     default (consolidated) member.
   - its unit matches the contract's unit **structure** (monetary: exactly
     one ISO 4217 USD numerator, no denominator);
   - its period matches the *requested slot period* (the filing's required context for as-filed
     current-period requests; explicit start/end for comparatives);
   - it is valid and non-nil.
4. **Duplicates** (XBRL OIM interval consistency, not rounding-to-coarser).
   Group candidates by **XBRL data point** (exact source QName / concept,
   plus the other aspects already matched). OIM overlap applies **inside**
   each group only. Two different exact concepts are not XBRL duplicates.
   - Treat each numeric as a closed interval of half-width `0.5 × 10^(-d)`.
     `INF` is `[value, value]`. Same `decimals` additionally requires equal
     reported numerics.
   - Consistent ⇔ the intersection of all intervals in the group is non-empty.
   - Survivor = most precise filed value; keep all fact ids as co-supports.
   - Otherwise that concept's group is `conflict`.
5. **Several exact concepts.** After one survivor per exact QName: same
   value → one observation, several supports; different values →
   `conflict`. There is never silent precedence via OIM across concepts.
6. **Non-publication.** Statuses are only `value | missing | conflict |
   unmapped_candidate | unsupported`. Extra detail is `reason`, not a new
   status.
   - `missing`: no candidate from an applicable exact decision. If the only
     nearby concepts are broader, `reason=broader_only`.
   - `unmapped_candidate`: a primary-statement line item in the matching
     context has no exact decision.
   - `unsupported` / `reason=wrong_form`: form is out of policy (10-Q under
     `annual-v1`).
   - `unsupported` / `reason=decision_scope`: exact decisions exist and
     **every** one excludes this issuer. If any exact decision still
     applies and has no fact, the status is `missing`, not `unsupported`.
7. **Views.**
   - `as-filed`: the filing's own period (required context).
   - `first-reported`: earliest `available_at` that reports the slot.
   - `latest-as-of(T)`: latest `available_at` ≤ T, including comparatives in later filings.

   `available_at` is the SEC acceptance timestamp of the **supplying** filing.

   A later accession with the same value is `reported_again`, not a restatement. Set
   `value_changed` when decimals-consistent comparison fails;
   `restatement_candidate` only then. Never set restatement merely because
   `supplying_accession` ≠ the original 10-K.

Amendments need no special machinery. A 10-K/A with full statements competes like any filing. One
without statements, such as the eBay 10-K/A with 37 cover facts, contributes no candidates.

## 7. How confidence is established

Confidence is evidence, not a model score, and it is reported at three levels:

- **Decision:** rationale, evidence pointers, reviewer, and tier. Observation
  precision is measured on gold **values**. Tier-3 **candidate** precision is
  measured on reviewed exact/non-exact labels, not on published values.
- **Observation:**
  - identity checks (pass / fail / not applicable);
  - oracle agreement (equal / differs / absent);
  - duplicate consistency;
  - cross-filing stability (as-filed vs next year's comparative).
- **Dataset:** coverage, precision, conflict and unmapped rates per metric × tier × industry × fiscal
  year.

A coarse grade (for example A = Tier 1–2, identities pass, oracle agrees) is a convenience for users.
It must stay derivable from the flags.

## 8. Measuring mapping quality empirically

| Measure | Definition | Needs labels? |
|---|---|---|
| Value precision | Published values equal to gold **financial values**, per metric × publishing tier (1, 2, 4) | Gold value slots |
| Gold assertion pass | Every gold label matches (`value`, `missing`, `unsupported`, `conflict`, …) | All gold assertions |
| Tier-3 candidate precision | Reviewed Tier-3 candidates later judged `exact` ÷ reviewed Tier-3 candidates | Mapping-relation labels (exact / not exact) |
| Oracle agreement | Selected standard-concept values equal to SEC `companyfacts` for the same accession and period | No |
| Identity pass rate | Share of issuer-years where applicable identities hold within rounding | No |
| Publication rate | `n_value / n_slot_eligible` (requested metric and allowed form; decision exclusions stay in the denominator) | No |
| Selector yield | `n_value / n_decision_applicable` (≥1 exact decision whose concept exists and whose scope includes this issuer) | No |
| Conflict / unmapped rates | Typed non-publication shares | No |
| Stability | As-filed values equal to next year's comparative, or explained by a restatement flag | No |
| Review load | Queue items per 1,000 filings; resolution time; items per tier | No |

`companyfacts` / FSDS validate extraction, period matching, selected standard
facts, and cross-system agreement. They **cannot** independently prove that
concept C is semantically exact for contract M. That remains taxonomy
evidence + reviewed decisions + independently labeled gold.

**Gold set.**

- Seed it with the M0 values and counterexamples.
- Grow it to about 200 issuer-years × 8 metrics, stratified by industry, size, year and extension
  intensity.
- Label values from the SEC-rendered statements (R files), and double-label ~10% to estimate label
  error.
- Report `n`, errors, empirical precision, and breakdowns by metric / industry /
  publishing tier. Do **not** quote an IID binomial confidence interval: the
  gold set is stratified and clustered by issuer and issuer-year. Population
  intervals require a probability sample and cluster-aware estimates.
- Add a fresh stratified sample each quarter to detect drift.

**Regression discipline.**

- Every decision or selector change runs `edgar build` on the fixture corpus and the gold set in CI.
- CI emits a quality-report diff.
- A failed **gold assertion** on the union of cohort files already on
  the base branch fails the build (values and non-value statuses). A
  drop in current **value precision** after adding a new cohort file
  does not. No numeric publication floor is hardcoded; a later ADR sets
  one from P2/P6 evidence.
- The M0 counterexamples become unit tests of the selector: bank, segment, YTD, amendment, broader,
  related, narrower extension, NCI.

**Scale measurement before building Stage 2.** Run Stage 1 on 500–1,000 filings (08, P2) and report
coverage, oracle agreement and identity pass rates per metric, **and** a
bounded independent semantic audit (30–50 issuer-years on high-risk
metrics) plus a metadata-drift census across taxonomy releases. Coverage
denominators are mechanical: **publication_rate** is values over
`slot_eligible` (requested metric and supported form only — a decision's
`exclude_*` does **not** remove the slot);
**selector_yield** is values over slots with at least one applicable
exact decision (concept exists in that release and scope does not
exclude the issuer). FSDS (historical quarters, or
the extracted sample) can
estimate concept usage per era. The Stage 2 investment should be sized by
the measured residual, not by assumption.

Working hypotheses for P2 to confirm or refute:

- Total assets and operating cash flow: ≥95% **selector_yield** for non-financial issuers, with ≥99.5%
  precision.
- Revenue: 75–90% **selector_yield** where RFCWCEAT (or the era's exact
  revenue concept) exists and is relevant. 2010–2017 **publication_rate**
  will be lower until an era-appropriate decision exists.
- R&D: a low **publication_rate** can be legitimate. Correct `missing`
  stays slot-eligible. Do not drop those issuer-years as “not applicable.”

## 9. Failure modes and mitigations

| Failure mode | Where it bites | Mitigation |
|---|---|---|
| Filer mis-tags a standard concept (e.g., consolidated NI as `NetIncomeLoss`) | Tier 1 | Identities; oracle; issuer exclusion/exception on the decision |
| Standard concept broader than the contract in some industries (bank revenue) | Tier 1 | SIC conditions; `unsupported` status; separate contract |
| Extension semantics change under the same local name | Tier 2 | Overlap-period continuity (as-filed t-1 vs comparative in t); label/documentation diff triggers review |
| Calculation linkbase errors | Tier 3 | Verify arithmetic on facts, not only arcs |
| Scale/sign errors (thousands vs units; negated labels) | All | Values come from resolved XBRL (`scale` applied by the transform); sign follows the concept's definition; DQC-style sanity checks |
| Duplicate facts with inconsistent values | Selection | `conflict`, never pick |
| Wrong period (YTD vs quarter; fiscal-year shifts) | Selection | Required-context anchoring; period-length checks; quarterly policy deferred to Stage 4 |
| Contract changes silently invalidating decisions | Knowledge | Accepted stale `contract_hash` fails CI/build until re-affirmed. Rejected stale hash is inactive history: report review-needed, do not suppress the queue, do not fail the build |
| LLM plausible-but-wrong proposals | Stage 3 | Never authoritative; measured precision; human acceptance only |
| Gold labels wrong | Measurement | Double labeling; disagreements reviewed |

## 10. Human effort model

| Work | Adopted plan | Recommendation |
|---|---|---|
| Standard concepts | Claims plus per-occurrence qualification: O(filings × metrics) | ~150–300 decision records once (39 metrics × a few concept families) + industry conditions |
| Extensions | Claims scoped to issuer + listed reports; each new filing re-enters review | One decision per extension family; reuse checked automatically |
| New filings | Qualification per new report | None unless a validator fails or an unmapped candidate appears |
| Contract changes | Re-review of affected claims | Re-affirm decisions whose `contract_hash` changed (CI lists them) |
| Quality assurance | Review attestation | Measured: gold set, identities, oracle |

## 11. Policy changes this requires (ADR)

1. Replace claim-level and occurrence-level human qualification with **policy-level review plus
   measured precision**.
2. Tier 2 may reuse an already-accepted issuer decision under continuity
   guards. **Tier 3 never auto-accepts** and never publishes observations.
   LLMs never accept.
3. Accept FASB documentation, from `MetaLinks.json` or taxonomy packages, as the affirmative
   definition evidence for standard concepts. An accepted decision must carry
   at least one lightweight evidence pointer.
4. Adopt XBRL OIM duplicate-fact consistency (interval overlap) and the EDGAR required context as the selection primitives.
5. Move mapping authority from the PostgreSQL ledger to Git-reviewed **decision records**.
